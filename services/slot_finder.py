"""
Поиск пустых слотов в очереди VK и заполнение их постами из локальной очереди.

Алгоритм:
1. Получить все отложенные посты из VK (wall.get filter=postponed)
2. Сгруппировать по дням
3. Найти дни где постов меньше max_posts_per_day
4. Для каждого такого дня найти свободные окна (с учётом min_gap)
5. Вернуть список (дата, час) куда можно вставить посты
"""
import logging
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def _get_tz_offset(timezone: str) -> int:
    TZ_OFFSETS = {
        'Europe/Moscow': 3,
        'Europe/Samara': 4,
        'Asia/Yekaterinburg': 5,
        'Asia/Omsk': 6,
        'Asia/Krasnoyarsk': 7,
        'Asia/Irkutsk': 8,
        'Asia/Yakutsk': 9,
        'Asia/Vladivostok': 10,
        'Asia/Magadan': 11,
        'Asia/Kamchatka': 12,
    }
    return TZ_OFFSETS.get(timezone, 3)


def fetch_postponed_timestamps(vk_group, group_id: str) -> list[int]:
    """Получить Unix timestamps всех отложенных постов из VK."""
    timestamps = []
    offset = 0
    gid = abs(int(group_id))

    while True:
        try:
            result = vk_group.wall.get(
                owner_id=f'-{gid}',
                filter='postponed',
                count=100,
                offset=offset,
            )
            items = result.get('items', [])
            if not items:
                break
            for item in items:
                ts = item.get('date') or item.get('publish_date')
                if ts:
                    timestamps.append(int(ts))
            if len(items) < 100:
                break
            offset += 100
        except Exception as e:
            logger.warning(f"slot_finder: ошибка получения отложенных постов: {e}")
            break

    return sorted(timestamps)


def _learned_peak_hours(profile_id: str, timezone: str) -> list[int]:
    """Топ часов для слотов — из обученного heatmap (трекер + конкуренты).

    Fallback: статичные MSK-пики если обучения ещё нет.
    """
    try:
        from services.learning import get_learning_state
        state = get_learning_state(profile_id)
        blended = state.get('blended_heatmap', {})
        if blended:
            ranked = sorted(
                ((int(h), float(v)) for h, v in blended.items()),
                key=lambda x: x[1],
                reverse=True,
            )
            return [h for h, _ in ranked[:8]]
    except Exception:
        pass

    # Нет данных обучения — статичные пики
    try:
        from services.smart_scheduler import _peaks_for_timezone
        return _peaks_for_timezone(timezone)
    except Exception:
        return [8, 10, 12, 14, 17, 19, 21]


def find_empty_slots(
    postponed_timestamps: list[int],
    profile: dict,
    model: dict,
    max_slots: int = 20,
    profile_id: str = '',
) -> list[dict]:
    """
    Найти пустые слоты в очереди постов.

    Часы выбираются по обученному heatmap (трекер + конкуренты),
    а не по статичным MSK-пикам.

    Возвращает список слотов:
    [{'date': '2026-06-07', 'hour': 14, 'ts': 1234567890}, ...]
    """
    from services.smart_scheduler import _compute_min_gap

    pub = profile.get('publishing_settings', {})
    timezone = pub.get('timezone', 'Europe/Moscow')
    window_start = pub.get('publish_hours_start', 0)
    window_end = pub.get('publish_hours_end', 23)
    max_per_day = pub.get('max_posts_per_day', 24)
    offset_hours = _get_tz_offset(timezone)
    min_gap = _compute_min_gap(model)
    now_ts = int(time.time())

    # Обученные пики — основной источник приоритетов часов
    learned_peaks = _learned_peak_hours(profile_id, timezone)

    # Сгруппировать занятые timestamps по дням (локальное время)
    occupied_by_day: dict[Any, list[int]] = defaultdict(list)
    for ts in postponed_timestamps:
        local_dt = datetime.utcfromtimestamp(ts) + timedelta(hours=offset_hours)
        occupied_by_day[local_dt.date()].append(ts)

    # Определить горизонт: от сегодня до последнего поста в очереди + 1 день
    today = (datetime.utcnow() + timedelta(hours=offset_hours)).date()
    if postponed_timestamps:
        last_local = datetime.utcfromtimestamp(max(postponed_timestamps)) + timedelta(hours=offset_hours)
        end_date = last_local.date() + timedelta(days=1)
    else:
        end_date = today + timedelta(days=7)

    slots = []
    scan_day = today

    while scan_day <= end_date and len(slots) < max_slots:
        day_occupied = occupied_by_day.get(scan_day, [])

        if len(day_occupied) < max_per_day:
            occupied_hours = set()
            for ts in day_occupied:
                local_dt = datetime.utcfromtimestamp(ts) + timedelta(hours=offset_hours)
                occupied_hours.add(local_dt.hour)

            # Кандидаты: сначала обученные пики, потом остальные часы в окне
            candidate_hours = []
            for h in learned_peaks:
                if window_start <= h <= window_end and h not in occupied_hours:
                    candidate_hours.append(h)
            for h in range(window_start, window_end + 1):
                if h not in occupied_hours and h not in candidate_hours:
                    candidate_hours.append(h)

            slots_today = 0
            needed = max_per_day - len(day_occupied)

            for hour in candidate_hours:
                if slots_today >= needed:
                    break

                # Собрать UTC timestamp для этого слота
                minute = random.randint(0, 59)
                second = random.randint(0, 59)
                local_dt = datetime(scan_day.year, scan_day.month, scan_day.day, hour, minute, second)
                utc_dt = local_dt - timedelta(hours=offset_hours)
                candidate_ts = int(utc_dt.timestamp())

                if candidate_ts <= now_ts:
                    continue

                # Проверить зазор со всеми существующими
                conflict = any(abs(candidate_ts - occ) < min_gap for occ in postponed_timestamps)
                if conflict:
                    continue

                slots.append({
                    'date': scan_day.isoformat(),
                    'hour': hour,
                    'ts': candidate_ts,
                    'display': f"{scan_day.strftime('%d.%m')} {hour:02d}:{minute:02d}",
                })
                # Добавить в occupied чтобы не конфликтовать внутри дня
                postponed_timestamps = sorted(postponed_timestamps + [candidate_ts])
                occupied_hours.add(hour)
                slots_today += 1

        scan_day += timedelta(days=1)

    logger.info(f"slot_finder: найдено {len(slots)} пустых слотов")
    return slots


def fill_slots_with_queue(
    slots: list[dict],
    posts_dir: Any,
    vk_user: Any,
    vk_group: Any,
    group_id: str,
    profile: dict,
    add_log: Any,
) -> dict:
    """
    Опубликовать посты из локальной очереди в найденные слоты.
    Возвращает {'filled': N, 'failed': M}.
    """
    import json
    from pathlib import Path
    from vk.api import vk_call_safe
    from workers.publish import (
        _compose_publish_text,
        _prepare_local_photos_for_publish,
        _upload_local_photos_with_fallback,
    )

    posts_dir = Path(posts_dir)
    post_files = sorted(posts_dir.glob('*.json'))

    if not post_files:
        add_log('Слоты: нет постов в очереди для заполнения', 'warning')
        return {'filled': 0, 'failed': 0}

    filled = 0
    failed = 0
    gid = abs(int(group_id))
    profile_id = ''
    try:
        from config import app_state
        profile_id = app_state.active_profile_id
    except Exception:
        pass

    def move_failed_post(post_file: Path):
        try:
            failed_dir = posts_dir.parent / 'failed_posts'
            failed_dir.mkdir(exist_ok=True)
            dest = failed_dir / post_file.name
            if dest.exists():
                dest = failed_dir / f'{post_file.stem}_{int(time.time())}{post_file.suffix}'
            post_file.replace(dest)
            add_log(f'[Слоты] Битый пост перенесён в failed_posts: {post_file.name}', 'warning')
        except Exception as e:
            add_log(f'[Слоты] Не удалось перенести битый пост {post_file.name}: {e}', 'warning')

    post_index = 0
    for slot in slots:
        while post_index < len(post_files):
            post_file = post_files[post_index]
            post_index += 1
            try:
                if not post_file.exists():
                    add_log(f'[Слоты] Файл уже отсутствует, пропускаю: {post_file.name}', 'warning')
                    continue

                post_data = json.loads(post_file.read_text(encoding='utf-8'))
                text = _compose_publish_text(post_data, profile, profile_id)
                local_photos, all_local_photos = _prepare_local_photos_for_publish(
                    post_data.get('_local_photos', []),
                    profile,
                    add_log,
                )
                attachments = _upload_local_photos_with_fallback(
                    vk_user,
                    gid,
                    local_photos,
                    all_local_photos,
                    add_log,
                )
                if all_local_photos and not attachments:
                    add_log(f'[Слоты] Пост {post_file.stem}: фото не загрузились, беру следующий пост', 'error')
                    move_failed_post(post_file)
                    failed += 1
                    continue

                for vid_ref in post_data.get('_vk_videos', []):
                    attachments.append(vid_ref)

                params: dict = {
                    'owner_id': f'-{gid}',
                    'from_group': 1,
                    'message': text,
                    'publish_date': slot['ts'],
                }
                if attachments:
                    params['attachments'] = ','.join(attachments)

                result = vk_call_safe(vk_group.wall.post, **params)
                post_id = result.get('post_id', 0) if isinstance(result, dict) else 0
                add_log(f"[Слоты] Вставлен пост в {slot['display']} (id={post_id})", 'info')

                try:
                    from services.cleanup_storage import cleanup_post_artifacts
                    cleanup_post_artifacts(post_file, post_data)
                except Exception:
                    post_file.unlink(missing_ok=True)
                    photo_dir = posts_dir.parent / 'photos' / post_file.stem
                    if photo_dir.exists():
                        import shutil
                        shutil.rmtree(photo_dir, ignore_errors=True)

                filled += 1
                break

            except Exception as e:
                add_log(f"[Слоты] Ошибка публикации в {slot['display']}: {e}", 'error')
                move_failed_post(post_file)
                failed += 1
                continue

    return {'filled': filled, 'failed': failed}
