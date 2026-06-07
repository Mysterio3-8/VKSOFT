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
    from vk.api import vk_call_safe
    timestamps = []
    offset = 0
    gid = abs(int(group_id))

    while True:
        try:
            result = vk_call_safe('wall.get', {
                'owner_id': f'-{gid}',
                'filter': 'postponed',
                'count': 100,
                'offset': offset,
            }, vk_instance=vk_group)
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


def find_empty_slots(
    postponed_timestamps: list[int],
    profile: dict,
    model: dict,
    max_slots: int = 20,
) -> list[dict]:
    """
    Найти пустые слоты в очереди постов.

    Возвращает список слотов:
    [{'date': '2026-06-07', 'hour': 14, 'ts': 1234567890}, ...]
    """
    from services.smart_scheduler import _peaks_for_timezone, _compute_min_gap

    pub = profile.get('publishing_settings', {})
    timezone = pub.get('timezone', 'Europe/Moscow')
    window_start = pub.get('publish_hours_start', 8)
    window_end = pub.get('publish_hours_end', 22)
    max_per_day = pub.get('max_posts_per_day', 4)
    offset_hours = _get_tz_offset(timezone)
    min_gap = _compute_min_gap(model)
    now_ts = int(time.time())

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

    peaks = _peaks_for_timezone(timezone)
    slots = []
    scan_day = today

    while scan_day <= end_date and len(slots) < max_slots:
        day_occupied = occupied_by_day.get(scan_day, [])

        if len(day_occupied) < max_per_day:
            occupied_hours = set()
            for ts in day_occupied:
                local_dt = datetime.utcfromtimestamp(ts) + timedelta(hours=offset_hours)
                occupied_hours.add(local_dt.hour)

            # Кандидаты: сначала пики, потом остальные часы в окне
            candidate_hours = []
            for h in peaks:
                if window_start <= h < window_end and h not in occupied_hours:
                    candidate_hours.append(h)
            for h in range(window_start, window_end):
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
    from vk.upload import upload_photo_from_file

    posts_dir = Path(posts_dir)
    post_files = sorted(posts_dir.glob('*.json'))

    if not post_files:
        add_log('Слоты: нет постов в очереди для заполнения', 'warning')
        return {'filled': 0, 'failed': 0}

    filled = 0
    failed = 0
    gid = abs(int(group_id))
    pub = profile.get('publishing_settings', {})

    for slot, post_file in zip(slots, post_files):
        try:
            post_data = json.loads(post_file.read_text(encoding='utf-8'))
            local_photos = post_data.get('_local_photos', [])

            attachments = []
            for photo_path in local_photos:
                try:
                    attach = upload_photo_from_file(vk_user, gid, photo_path)
                    if attach:
                        attachments.append(attach)
                except Exception as e:
                    add_log(f'Слоты: ошибка загрузки фото {photo_path}: {e}', 'warning')

            text = post_data.get('text', '')
            if pub.get('add_hashtags') and pub.get('hashtags'):
                hashtags = ' '.join(pub['hashtags'])
                text = f"{text}\n{hashtags}".strip() if text else hashtags

            params: dict = {
                'owner_id': f'-{gid}',
                'from_group': 1,
                'message': text,
                'publish_date': slot['ts'],
            }
            if attachments:
                params['attachments'] = ','.join(attachments)

            result = vk_call_safe('wall.post', params, vk_instance=vk_group)
            post_id = result.get('post_id', 0) if isinstance(result, dict) else 0

            add_log(f"[Слоты] Вставлен пост в {slot['display']} (id={post_id})", 'info')

            # Удалить файл поста после публикации
            post_file.unlink(missing_ok=True)
            photo_dir = posts_dir.parent / 'photos' / post_file.stem
            if photo_dir.exists():
                import shutil
                shutil.rmtree(photo_dir, ignore_errors=True)

            filled += 1

        except Exception as e:
            add_log(f"[Слоты] Ошибка публикации в {slot['display']}: {e}", 'error')
            failed += 1

    return {'filled': filled, 'failed': failed}
