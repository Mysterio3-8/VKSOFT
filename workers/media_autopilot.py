# -*- coding: utf-8 -*-
"""Циклы автопилота по типам медиа: посты, фото, видео, клипы.

Каждый тип — свой поток-цикл: скачать → обработать (антиплагиат внутри
publish-воркеров) → опубликовать → пауза → повтор. Циклы независимы и могут
работать параллельно: время публикаций координируется через общий
last_scheduled + fetch_last_postponed_from_vk, поэтому слоты не конфликтуют.

Останавливается сбросом app_state.media_loops[media_type].
"""

import time
from datetime import datetime

from config import app_state

MEDIA_TYPES = ('posts', 'photos', 'videos', 'clips')

_LABELS = {'posts': 'посты', 'photos': 'фото', 'videos': 'видео', 'clips': 'клипы'}

_DEFAULT_INTERVAL_MIN = 180


def loop_interval_min(media_type: str) -> int:
    """Интервал цикла для типа: autopilot.intervals.{type}, иначе общий дефолт."""
    intervals = app_state.profile.get('autopilot', {}).get('intervals', {})
    try:
        value = int(intervals.get(media_type, 0))
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else _DEFAULT_INTERVAL_MIN


def _positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    return parsed if parsed > 0 else default


def loop_download_count(media_type: str) -> int:
    profile = app_state.profile
    if media_type == 'posts':
        return _positive_int(profile.get('download_settings', {}).get('posts_to_download'), 100)
    if media_type == 'photos':
        cfg = profile.get('photos_settings', {})
        return _positive_int(cfg.get('photos_download_per_run', cfg.get('photos_per_run')), 50)
    if media_type == 'videos':
        cfg = profile.get('videos_settings', {})
        return _positive_int(cfg.get('videos_download_per_run', cfg.get('videos_per_run')), 10)
    if media_type == 'clips':
        cfg = profile.get('clips_settings', {})
        return _positive_int(cfg.get('clips_download_per_run', cfg.get('clips_per_run')), 10)
    return 1


def loop_publish_count(media_type: str) -> int:
    profile = app_state.profile
    if media_type == 'posts':
        return _positive_int(profile.get('publishing_settings', {}).get('posts_to_publish'), 100)
    if media_type == 'photos':
        cfg = profile.get('photos_settings', {})
        return _positive_int(cfg.get('photos_publish_per_run', cfg.get('photos_per_run')), 50)
    if media_type == 'videos':
        cfg = profile.get('videos_settings', {})
        return _positive_int(cfg.get('videos_publish_per_run', cfg.get('videos_per_run')), 10)
    if media_type == 'clips':
        cfg = profile.get('clips_settings', {})
        return _positive_int(cfg.get('clips_publish_per_run', cfg.get('clips_per_run')), 10)
    return 1


def _set_state(media_type: str, **kwargs) -> None:
    app_state.media_loop_state.setdefault(media_type, {}).update(kwargs)


def _set_progress(media_type: str, *, phase: str, current: int, total: int, label: str = '') -> None:
    """Обновить прогресс текущего прохода цикла.

    phase: 'download' | 'publish' | 'idle'.
    total=0 — фронт скрывает числа/проценты, показывает '—'.
    """
    _set_state(media_type, progress={
        'phase': phase,
        'current': current,
        'total': total,
        'label': label,
    })


def _cycle_posts() -> None:
    from workers.download import download_all_worker
    from workers.publish import publish_worker

    if app_state.is_downloading or app_state.is_publishing:
        app_state.add_log('Цикл постов: загрузка/публикация уже идёт, пропускаю проход', 'warning')
        return
    app_state.is_downloading = True
    download_all_worker()
    if not app_state.media_loops.get('posts'):
        return
    pending = len(list(app_state.posts_dir.glob('*.json')))
    if pending > 0:
        count = loop_publish_count('posts')
        app_state.is_publishing = True
        try:
            publish_worker(min(count, pending))
        finally:
            app_state.is_publishing = False


def _cycle_photos() -> None:
    from workers.photos import download_photos_worker, publish_photos_worker, queue_count

    if app_state.is_downloading_photos or app_state.is_publishing_photos:
        app_state.add_log('Цикл фото: воркер уже занят, пропускаю проход', 'warning')
        return
    app_state.is_downloading_photos = True
    download_photos_worker()
    if not app_state.media_loops.get('photos'):
        return
    if queue_count() > 0:
        count = loop_publish_count('photos')
        app_state.is_publishing_photos = True
        publish_photos_worker(count)


def _learning_prefers_video() -> bool:
    """Learning engine рекомендует видео-контент (по данным конкурентов)."""
    try:
        from services.learning import get_learning_state
        return bool(get_learning_state(app_state.active_profile_id).get('prefer_video'))
    except Exception:
        return False


def _cycle_videos() -> None:
    from workers.videos import (
        download_top_competitor_videos,
        download_videos_worker,
        publish_videos_worker,
    )

    if app_state.is_downloading_videos or app_state.is_publishing_videos:
        app_state.add_log('Цикл видео: воркер уже занят, пропускаю проход', 'warning')
        return
    app_state.is_downloading_videos = True
    download_videos_worker()
    if not app_state.media_loops.get('videos'):
        return
    if _learning_prefers_video():
        app_state.add_log('Learning: видео в топе у конкурентов, качаю их топ', 'info')
        download_top_competitor_videos(count=3, is_clips_mode=False)
    pending = len(list(app_state.videos_queue_dir.glob('*.json')))
    if pending > 0:
        count = loop_publish_count('videos')
        app_state.is_publishing_videos = True
        publish_videos_worker(count, is_clips_mode=False)


def _assemble_slideshows_if_needed() -> None:
    """Дособрать slideshow-клипы из фото, если очередь клипов проседает.

    Фото расходуются только при запасе (≥6 в очереди) — фото-цикл не голодает.
    """
    cfg = app_state.profile.get('clips_settings', {})
    if not cfg.get('slideshow_auto', True):
        return
    pending_clips = len(list(app_state.clips_queue_dir.glob('*.json')))
    target = loop_download_count('clips')
    if pending_clips >= target:
        return
    photos_pending = len(list(app_state.photos_queue_dir.glob('*.json')))
    if photos_pending < 6:
        return
    per_cycle = min(int(cfg.get('slideshow_per_cycle', 2)), target - pending_clips)
    from services.clip_assembler import assemble_slideshow_from_photo_queue
    for _ in range(per_cycle):
        result = assemble_slideshow_from_photo_queue(
            int(cfg.get('slideshow_photos', 3)),
            float(cfg.get('slideshow_duration', 12)),
        )
        if result.get('status') != 'ok':
            break


def _cycle_clips() -> None:
    from workers.clips import download_clips_worker
    from workers.videos import download_top_competitor_videos, publish_videos_worker

    if app_state.is_downloading_clips or app_state.is_publishing_clips:
        app_state.add_log('Цикл клипов: воркер уже занят, пропускаю проход', 'warning')
        return
    app_state.is_downloading_clips = True
    download_clips_worker()
    if not app_state.media_loops.get('clips'):
        return
    if _learning_prefers_video():
        app_state.add_log('Learning: клипы качаю у топ конкурентов', 'info')
        download_top_competitor_videos(count=3, is_clips_mode=True)
    try:
        _assemble_slideshows_if_needed()
    except Exception as e:
        app_state.add_log(f'Цикл клипов: slideshow {e}', 'warning')
    pending = len(list(app_state.clips_queue_dir.glob('*.json')))
    if pending > 0:
        count = loop_publish_count('clips')
        app_state.is_publishing_clips = True
        publish_videos_worker(count, is_clips_mode=True)


_CYCLES = {
    'posts': _cycle_posts,
    'photos': _cycle_photos,
    'videos': _cycle_videos,
    'clips': _cycle_clips,
}


def media_loop_worker(media_type: str) -> None:
    """Бесконечный цикл одного типа медиа. Запускается в daemon-потоке."""
    label = _LABELS[media_type]
    app_state.add_log(
        f'Автопилот ({label}): цикл запущен, интервал {loop_interval_min(media_type)} мин', 'info'
    )
    try:
        while app_state.media_loops.get(media_type):
            _set_state(
                media_type,
                phase='working',
                last_start=datetime.now().strftime('%d.%m %H:%M'),
                next_run='',
            )
            _set_progress(media_type, phase='idle', current=0, total=0)
            try:
                _CYCLES[media_type]()
            except Exception as e:
                app_state.add_log(f'Автопилот ({label}): ошибка прохода: {e}', 'error')
                _set_progress(media_type, phase='idle', current=0, total=0)

            try:
                from services.publish_log import rotate_old_logs
                rotate_old_logs()
            except Exception:
                pass

            if not app_state.media_loops.get(media_type):
                break
            interval_sec = loop_interval_min(media_type) * 60
            next_run = datetime.fromtimestamp(time.time() + interval_sec).strftime('%H:%M')
            _set_state(media_type, phase='sleeping', next_run=next_run)
            # Спим короткими шагами, чтобы стоп срабатывал быстро
            deadline = time.time() + interval_sec
            while time.time() < deadline and app_state.media_loops.get(media_type):
                time.sleep(5)
    finally:
        app_state.media_loops[media_type] = False
        _set_state(media_type, phase='stopped', next_run='')
        _set_progress(media_type, phase='idle', current=0, total=0)
        app_state.add_log(f'Автопилот ({label}): цикл остановлен', 'info')


def stop_loop(media_type: str) -> None:
    """Остановить цикл и прервать текущую работу этого типа."""
    app_state.media_loops[media_type] = False
    if media_type == 'posts':
        app_state.is_downloading = False
        app_state.is_publishing = False
    elif media_type == 'photos':
        app_state.is_downloading_photos = False
        app_state.is_publishing_photos = False
    elif media_type == 'videos':
        app_state.is_downloading_videos = False
        app_state.is_publishing_videos = False
    elif media_type == 'clips':
        app_state.is_downloading_clips = False
        app_state.is_publishing_clips = False


def loops_status() -> dict:
    return {
        media_type: {
            'running': bool(app_state.media_loops.get(media_type)),
            'interval_min': loop_interval_min(media_type),
            'download_count': loop_download_count(media_type),
            'publish_count': loop_publish_count(media_type),
            **app_state.media_loop_state.get(media_type, {}),
        }
        for media_type in MEDIA_TYPES
    }
