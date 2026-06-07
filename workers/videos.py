# -*- coding: utf-8 -*-
"""Видео-воркер: скачать mp4 из VK → перезалить в группу → wall post."""

import json
import random
import time
from pathlib import Path

import requests as req_lib
import vk_api

from config import app_state, STORAGE_DIR
from vk.api import get_vk_api, vk_call_safe, normalize_owner_id, send_critical_alert


# ── Seen IDs ──────────────────────────────────────────────────────

def _seen_file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'seen_videos.json'


def _load_seen() -> set:
    f = _seen_file()
    if f.exists():
        try:
            return set(json.loads(f.read_text(encoding='utf-8')))
        except Exception:
            pass
    return set()


def _add_seen(key: str):
    seen = _load_seen()
    seen.add(key)
    if len(seen) > 10000:
        seen = set(list(seen)[-8000:])
    try:
        f = _seen_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(list(seen)), encoding='utf-8')
    except Exception:
        pass


# ── Скачать mp4 через yt-dlp ──────────────────────────────────────

def _download_video(video_owner: int, video_id: int, dest: Path,
                    quality: str = '720', max_mb: int = 500) -> bool:
    """Скачать VK-видео через yt-dlp по публичному URL."""
    url = f'https://vk.com/video{video_owner}_{video_id}'
    # Высота качества
    try:
        h = int(quality)
    except ValueError:
        h = 720

    ydl_opts = {
        'format': f'best[ext=mp4][height<={h}]/best[height<={h}]/best',
        'outtmpl': str(dest.with_suffix('')),   # yt-dlp добавит расширение
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        },
    }

    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # yt-dlp может добавить расширение .mp4 или .webm
            actual = Path(ydl.prepare_filename(info))
            if actual.exists() and actual != dest:
                actual.rename(dest)
            elif not dest.exists():
                # Попробуем найти скачанный файл рядом
                for ext in ('.mp4', '.webm', '.mkv'):
                    candidate = dest.with_suffix(ext)
                    if candidate.exists():
                        candidate.rename(dest)
                        break

        if not dest.exists():
            return False

        size_mb = dest.stat().st_size / 1024 / 1024
        if size_mb > max_mb:
            app_state.add_log(f'Видео: {size_mb:.0f}МБ > лимита {max_mb}МБ, пропускаю', 'warning')
            dest.unlink(missing_ok=True)
            return False
        return True

    except Exception as e:
        app_state.add_log(f'Видео скачивание {video_owner}_{video_id}: {e}', 'warning')
        dest.unlink(missing_ok=True)
        return False


# ── Загрузить видео в группу ──────────────────────────────────────

def _upload_video(vk_user, gid_num: int, video_path: Path, title: str, desc: str,
                  is_clip: bool = False) -> tuple:
    """Вернуть (owner_id, video_id) или (None, None)."""
    params = {
        'name': title[:120],
        'description': desc[:1000] if desc else '',
        'group_id': gid_num,
        'wallpost': 0,
        'is_private': 0,
    }
    if is_clip:
        params['is_reels'] = 1

    save_resp = vk_call_safe(vk_user.video.save, **params)
    upload_url = save_resp.get('upload_url')
    if not upload_url:
        return None, None

    with open(video_path, 'rb') as fh:
        up_resp = req_lib.post(
            upload_url,
            files={'video_file': (video_path.name, fh, 'video/mp4')},
            timeout=600,
        ).json()

    vid_id   = up_resp.get('video_id') or save_resp.get('video_id')
    owner_id = up_resp.get('owner_id') or save_resp.get('owner_id') or f'-{gid_num}'
    return owner_id, vid_id


# ── Основная логика скачивания ────────────────────────────────────

def _download_videos_source(community_id: str, count: int,
                             max_duration: int = 0, max_mb: int = 500,
                             quality: str = '720', is_clips_mode: bool = False):
    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    api_ver = vk_cfg.get('api_version', '5.131')

    flag = 'is_downloading_clips' if is_clips_mode else 'is_downloading_videos'
    queue_dir = app_state.clips_queue_dir if is_clips_mode else app_state.videos_queue_dir
    files_dir = app_state.clip_files_dir  if is_clips_mode else app_state.video_files_dir

    if not user_token:
        app_state.add_log(f'{"Клипы" if is_clips_mode else "Видео"}: User Token не задан', 'error')
        return

    vk = get_vk_api(user_token, api_ver)
    owner_id = normalize_owner_id(community_id)
    seen = _load_seen() if not is_clips_mode else _load_clips_seen()
    downloaded = skipped = 0
    offset = 0
    label = 'Клипы' if is_clips_mode else 'Видео'

    app_state.add_log(f'{label}: загрузка {count} из {owner_id}', 'info')

    while downloaded < count and getattr(app_state, flag):
        try:
            resp = vk_call_safe(
                vk.video.get,
                owner_id=owner_id,
                count=min(200, count - downloaded),
                offset=offset,
                extended=1,
            )
        except vk_api.exceptions.ApiError as e:
            code = getattr(e, 'code', 0)
            if code == 204:
                app_state.add_log(f'{label} VK API {code}: {e}', 'warning')
                break
            app_state.add_log(f'{label} VK API {code}: {e}', 'error')
            if code in (5, 28):
                send_critical_alert(f'Токен недействителен ({code}). {label} остановлен.')
                setattr(app_state, flag, False)
            break

        items = (resp.get('items', []) if isinstance(resp, dict) else [])
        if not items:
            app_state.add_log(f'{label} {owner_id}: больше нет', 'info')
            break

        for video in items:
            if not getattr(app_state, flag) or downloaded >= count:
                break

            vid_id   = video.get('id')
            vid_owner = video.get('owner_id')
            key = f'{vid_owner}_{vid_id}'

            if key in seen:
                skipped += 1
                continue

            duration = video.get('duration', 0)
            # Для клипов фильтруем по длительности
            if is_clips_mode:
                if max_duration > 0 and duration > max_duration:
                    skipped += 1
                    continue
                if duration > 180:
                    skipped += 1
                    continue
            else:
                if duration < 10:
                    skipped += 1
                    continue

            dest = files_dir / f'{key}.mp4'
            if not _download_video(vid_owner, vid_id, dest, quality, max_mb):
                skipped += 1
                continue

            meta = {
                'id': vid_id,
                'owner_id': vid_owner,
                'title': video.get('title', ''),
                'description': video.get('description', ''),
                'duration': duration,
                '_local_file': str(dest),
                '_source_cid': community_id,
                '_is_clip': is_clips_mode,
            }
            meta_file = queue_dir / f'{key}.json'
            meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')

            if is_clips_mode:
                _add_clips_seen(key)
            else:
                _add_seen(key)

            downloaded += 1
            if downloaded % 5 == 0 or downloaded == 1:
                app_state.add_log(f'{label} [{owner_id}] {downloaded}/{count}', 'info')

            time.sleep(random.uniform(1, 3))

        offset += len(items)
        if len(items) < 200:
            break

    app_state.add_log(f'{label} [{owner_id}]: {downloaded} скачано, {skipped} пропущено', 'info')


def download_videos_worker():
    profile = app_state.profile
    sources = [s for s in profile.get('sources', []) if s.get('enabled')]
    cfg = profile.get('videos_settings', {})
    count  = int(cfg.get('videos_per_run', 10))
    max_mb = int(cfg.get('max_filesize_mb', 500))
    quality = cfg.get('quality', '720')

    if not sources:
        app_state.add_log('Видео: нет активных источников', 'warning')
        app_state.is_downloading_videos = False
        return
    try:
        for src in sources:
            if not app_state.is_downloading_videos:
                break
            cid = str(src.get('community_id', ''))
            app_state.add_log(f'Видео: источник {src.get("name", cid)}', 'info')
            _download_videos_source(cid, count, max_mb=max_mb, quality=quality, is_clips_mode=False)
    except Exception as e:
        app_state.add_log(f'Видео загрузка: {e}', 'error')
    finally:
        app_state.is_downloading_videos = False


# ── Публикация видео ──────────────────────────────────────────────

def publish_videos_worker(count: int, is_clips_mode: bool = False):
    label = 'Клипы' if is_clips_mode else 'Видео'
    flag  = 'is_publishing_clips' if is_clips_mode else 'is_publishing_videos'
    queue_dir = app_state.clips_queue_dir if is_clips_mode else app_state.videos_queue_dir
    cfg_key   = 'clips_settings' if is_clips_mode else 'videos_settings'

    try:
        profile = app_state.profile
        vk_cfg = profile.get('vk', {})
        cfg = profile.get(cfg_key, {})

        user_token  = vk_cfg.get('user_token', '').strip()
        group_token = vk_cfg.get('group_token', '').strip()
        group_id    = vk_cfg.get('group_id', '').strip()
        api_ver     = vk_cfg.get('api_version', '5.131')

        if not user_token or not group_id:
            app_state.add_log(f'{label} публикация: токены не заданы', 'error')
            return

        vk_user  = get_vk_api(user_token, api_ver)
        vk_group = get_vk_api(group_token, api_ver) if group_token else vk_user
        gid_num  = int(group_id.lstrip('-'))
        owner_id = f'-{gid_num}'

        create_wall = cfg.get('create_wall_post', True)
        delay_min   = int(cfg.get('publish_delay_min', 3600))
        delay_max   = int(cfg.get('publish_delay_max', 7200))
        if delay_min > delay_max:
            delay_min, delay_max = delay_max, delay_min

        queue = sorted(queue_dir.glob('*.json'))[:count]
        if not queue:
            app_state.add_log(f'{label}: очередь пуста', 'warning')
            return

        app_state.add_log(f'{label}: публикация {len(queue)}', 'info')
        published = failed = 0
        from workers.photos import _get_next_ts
        next_ts = _get_next_ts(delay_min, delay_max)

        for meta_file in queue:
            if not getattr(app_state, flag):
                break
            try:
                meta = json.loads(meta_file.read_text(encoding='utf-8'))
                video_path = Path(meta.get('_local_file', ''))

                if not video_path.exists():
                    app_state.add_log(f'{label}: файл не найден {video_path.name}', 'warning')
                    meta_file.unlink(missing_ok=True)
                    continue

                # Антиплагиат: кроп, вырез фрагмента, лого, метаданные через ffmpeg
                try:
                    from services.video_transform import transform_from_profile
                    if transform_from_profile(
                        video_path, profile,
                        title=meta.get('title', ''),
                        is_clip=is_clips_mode,
                    ):
                        app_state.add_log(f'{label}: антиплагиат применён к {video_path.name}', 'info')
                except Exception as e:
                    app_state.add_log(f'{label}: обработка видео {e}', 'warning')

                vid_owner, vid_id = _upload_video(
                    vk_user, gid_num, video_path,
                    title=meta.get('title', 'Видео'),
                    desc=meta.get('description', ''),
                    is_clip=is_clips_mode,
                )
                if not vid_id:
                    app_state.add_log(f'{label}: загрузка не удалась', 'error')
                    failed += 1
                    continue

                att = f'video{vid_owner}_{vid_id}'

                if create_wall:
                    from services.content_library import compose_caption
                    processing = profile.get('processing', {})
                    text = compose_caption(
                        '',
                        add_tags=True,
                        profile_tags=processing.get('hashtags', []),
                        add_profile_tags=processing.get('add_hashtags', False),
                    )

                    now = int(time.time())
                    if next_ts <= now:
                        next_ts = now + random.randint(delay_min, delay_max)

                    params = {
                        'owner_id': owner_id,
                        'message': text,
                        'attachments': att,
                        'publish_date': next_ts,
                    }
                    vk_call_safe(vk_group.wall.post, **params)
                    from datetime import datetime
                    from services.storage import write_last_scheduled
                    app_state.add_log(
                        f'{label}: → {datetime.fromtimestamp(next_ts).strftime("%d.%m %H:%M")}',
                        'info'
                    )
                    write_last_scheduled(next_ts)
                    next_ts += random.randint(delay_min, delay_max)

                video_path.unlink(missing_ok=True)
                meta_file.unlink(missing_ok=True)
                published += 1

            except vk_api.exceptions.ApiError as e:
                code = getattr(e, 'code', 0)
                app_state.add_log(f'{label} VK API {code}: {e}', 'error')
                failed += 1
                if code in (5, 28):
                    setattr(app_state, flag, False)
                    break
            except Exception as e:
                app_state.add_log(f'{label} ошибка поста: {e}', 'error')
                failed += 1

        app_state.add_log(f'{label}: {published} опубликовано, {failed} ошибок', 'info')
        if published > 0 and profile.get('storage_cleanup', {}).get('clean_orphans_after_run', True):
            try:
                from services.cleanup_storage import cleanup_junk
                junk = cleanup_junk()
                removed = sum(int(v or 0) for v in junk.values())
                if removed:
                    app_state.add_log(f'{label} автоочистка: удалено {removed} остаточных файлов/папок', 'info')
            except Exception as e:
                app_state.add_log(f'{label} автоочистка: {e}', 'warning')

    except Exception as e:
        app_state.add_log(f'{label} публикация критическая ошибка: {e}', 'error')
    finally:
        setattr(app_state, flag, False)


# ── Clips seen IDs ────────────────────────────────────────────────

def _clips_seen_file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'seen_clips.json'

def _load_clips_seen() -> set:
    f = _clips_seen_file()
    if f.exists():
        try:
            return set(json.loads(f.read_text(encoding='utf-8')))
        except Exception:
            pass
    return set()

def _add_clips_seen(key: str):
    seen = _load_clips_seen()
    seen.add(key)
    if len(seen) > 10000:
        seen = set(list(seen)[-8000:])
    try:
        f = _clips_seen_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(list(seen)), encoding='utf-8')
    except Exception:
        pass


# ── Скачивание топ видео конкурентов по ER ────────────────────────

def download_top_competitor_videos(count: int = 5, is_clips_mode: bool = False) -> int:
    """Скачать топ-видео конкурентов по Engagement Rate.

    Использует данные из competitor_data.json (накопленные competitor_scan_loop).
    Отбирает видео из top20 конкурентов с наивысшим ER, которых ещё нет в seen.
    Возвращает количество скачанных видео.
    """
    from services.competitor import _load_data
    from vk.api import get_vk_api, normalize_owner_id

    profile = app_state.profile
    profile_id = app_state.active_profile_id
    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    if not user_token:
        app_state.add_log('Топ видео конкурентов: user_token не задан', 'error')
        return 0

    cfg_key = 'clips_settings' if is_clips_mode else 'videos_settings'
    cfg = profile.get(cfg_key, {})
    max_mb = int(cfg.get('max_filesize_mb', 500))
    quality = cfg.get('quality', '720')
    max_duration = int(cfg.get('max_duration_sec', 180)) if is_clips_mode else 0

    competitor_data = _load_data(profile_id)
    if not competitor_data:
        app_state.add_log('Топ видео конкурентов: нет данных по конкурентам (сканирование ещё не прошло)', 'warning')
        return 0

    # Собираем кандидатов из top20 каждого конкурента (только посты с видео)
    candidates: list[dict] = []
    for cid, source in competitor_data.items():
        for post in source.get('top20', []):
            if post.get('type') != 'video':
                continue
            candidates.append({
                'cid': cid,
                'post_id': post['post_id'],
                'er': post['er'],
                'owner_id': int(normalize_owner_id(cid).replace('-', '-')),
            })

    # Сортируем по ER, берём лучших
    candidates.sort(key=lambda x: x['er'], reverse=True)

    seen = _load_seen() if not is_clips_mode else _load_clips_seen()
    queue_dir = app_state.clips_queue_dir if is_clips_mode else app_state.videos_queue_dir
    files_dir = app_state.clip_files_dir if is_clips_mode else app_state.video_files_dir
    label = 'Топ клипы' if is_clips_mode else 'Топ видео'

    try:
        vk = get_vk_api(user_token, vk_cfg.get('api_version', '5.131'))
    except Exception as e:
        app_state.add_log(f'{label}: VK API init error: {e}', 'error')
        return 0

    downloaded = 0
    for cand in candidates:
        if downloaded >= count:
            break

        cid = cand['cid']
        post_id = cand['post_id']

        # Получаем видео-аттачменты поста
        try:
            from vk.api import vk_call_safe, normalize_owner_id
            owner_str = normalize_owner_id(cid)
            resp = vk_call_safe(
                vk.wall.getById,
                posts=f'{owner_str}_{post_id}',
                extended=0,
            )
            items = resp.get('items', []) if isinstance(resp, dict) else (resp or [])
            if not items:
                continue
            post = items[0]
            atts = post.get('attachments', [])
            vid_atts = [a for a in atts if a.get('type') == 'video']
        except Exception as e:
            app_state.add_log(f'{label}: getById {cid}_{post_id}: {e}', 'warning')
            continue

        for va in vid_atts:
            vid_obj = va.get('video', {})
            vid_id = vid_obj.get('id')
            vid_owner = vid_obj.get('owner_id')
            if not vid_id or not vid_owner:
                continue

            key = f'{vid_owner}_{vid_id}'
            if key in seen:
                continue

            duration = vid_obj.get('duration', 0)
            if is_clips_mode:
                if duration > 180 or (max_duration > 0 and duration > max_duration):
                    continue
            else:
                if duration < 10:
                    continue

            dest = files_dir / f'{key}.mp4'
            if not _download_video(vid_owner, vid_id, dest, quality, max_mb):
                continue

            meta = {
                'id': vid_id,
                'owner_id': vid_owner,
                'title': vid_obj.get('title', ''),
                'description': vid_obj.get('description', ''),
                'duration': duration,
                '_local_file': str(dest),
                '_source_cid': cid,
                '_is_clip': is_clips_mode,
                '_competitor_er': cand['er'],
            }
            meta_file = queue_dir / f'{key}.json'
            meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')

            if is_clips_mode:
                _add_clips_seen(key)
            else:
                _add_seen(key)

            downloaded += 1
            app_state.add_log(
                f'{label}: скачал {key} (ER={cand["er"]:.2f}%, из {cid})',
                'info'
            )
            time.sleep(random.uniform(1, 2))
            break  # один видео на пост

    app_state.add_log(f'{label} конкурентов: {downloaded} скачано', 'info')
    return downloaded
