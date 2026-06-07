"""
Умный планировщик времени публикаций.

Логика:
- Стартовые веса: статистические пики по России (9, 12, 15, 18, 21 MSK) конвертируются в timezone профиля
- Обучение: engagement_model.json обновляется после сбора статистики (см. engagement.py)
- 75% exploitation (лучшие часы) + 25% exploration (редко используемые)
- Поиск свободного окна: минимальный зазор между постами определяется моделью
"""
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Статистические пики для России (MSK UTC+3), используются до накопления реальных данных
_RUSSIA_PEAKS_MSK = [9, 12, 15, 18, 21]

# Минимальный зазор между постами в один день (секунды) — стартовое значение
_MIN_GAP_SECONDS_DEFAULT = 3 * 3600


def _get_tz_offset(timezone: str) -> int:
    """Возвращает UTC-смещение в часах для российских зон."""
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


def _peaks_for_timezone(timezone: str) -> list[int]:
    """Конвертировать MSK-пики в часы целевой зоны."""
    offset = _get_tz_offset(timezone)
    msk_offset = 3
    delta = offset - msk_offset
    return sorted(set(((h + delta) % 24) for h in _RUSSIA_PEAKS_MSK))


def _pick_hour(model: dict, timezone: str, used_hours: set[int], window_start: int, window_end: int) -> int:
    """
    Выбрать час для публикации на основе модели.
    75% — лучший час из окна, 25% — случайный из редко используемых.
    """
    heatmap: dict[str, float] = model.get('hour_heatmap', {})
    sample_count: dict[str, int] = model.get('sample_count', {})

    # Допустимые часы в рабочем окне, не занятые в этот день
    candidates = [h for h in range(window_start, window_end) if h not in used_hours]
    if not candidates:
        # Расширяем до всего дня
        candidates = [h for h in range(24) if h not in used_hours]
    if not candidates:
        candidates = list(range(window_start, window_end)) or list(range(24))

    total_samples = sum(sample_count.get(str(h), 0) for h in candidates)

    if total_samples < 10 or random.random() < 0.25:
        # Exploration: выбрать пики по зоне или редко проверенный час
        peaks = _peaks_for_timezone(timezone)
        peak_candidates = [h for h in peaks if h in candidates]
        if not peak_candidates:
            peak_candidates = candidates
        # Из пиков выбрать наименее изученный
        chosen = min(peak_candidates, key=lambda h: sample_count.get(str(h), 0))
    else:
        # Exploitation: лучший час по heatmap
        chosen = max(candidates, key=lambda h: heatmap.get(str(h), 0.0))

    return chosen


def _local_hour_to_utc_ts(date: datetime, hour: int, timezone: str) -> int:
    """Собрать Unix timestamp для даты+часа в заданной зоне."""
    offset_hours = _get_tz_offset(timezone)
    # date должна быть naive UTC-midnight или local-midnight — используем naive
    local_dt = date.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))
    utc_dt = local_dt - timedelta(hours=offset_hours)
    return int(utc_dt.timestamp())


def next_publish_timestamp(
    last_ts: int,
    profile: dict,
    model: dict,
    occupied_timestamps: list[int],
) -> tuple[int, int]:
    """
    Вычислить следующий timestamp для публикации.

    Возвращает (unix_ts, hour_local) — timestamp и час в зоне профиля.

    Алгоритм:
    1. Взять день после last_ts (в локальной зоне)
    2. Собрать занятые часы в этот день
    3. Выбрать час через _pick_hour()
    4. Если в этот день уже max_posts_per_day — перейти на следующий
    5. Проверить минимальный зазор с соседними постами
    """
    pub = profile.get('publishing_settings', {})
    timezone = pub.get('timezone', 'Europe/Moscow')
    window_start = pub.get('publish_hours_start', 8)
    window_end = pub.get('publish_hours_end', 22)
    max_per_day = pub.get('max_posts_per_day', 4)

    offset_hours = _get_tz_offset(timezone)
    now_ts = int(time.time())
    base_ts = max(last_ts, now_ts)

    # Конвертировать occupied_timestamps в (date_local, hour_local)
    def ts_to_local(ts: int) -> tuple[datetime, int]:
        dt = datetime.utcfromtimestamp(ts) + timedelta(hours=offset_hours)
        return dt.date(), dt.hour

    occupied_by_day: dict[Any, list[int]] = {}
    for ts in occupied_timestamps:
        d, h = ts_to_local(ts)
        occupied_by_day.setdefault(d, []).append(h)

    # Стартовый день
    base_local = datetime.utcfromtimestamp(base_ts) + timedelta(hours=offset_hours)
    search_day = base_local.date()

    for _ in range(30):  # не больше 30 дней вперёд
        day_posts = occupied_by_day.get(search_day, [])

        if len(day_posts) < max_per_day:
            used_hours = set(day_posts)
            chosen_hour = _pick_hour(model, timezone, used_hours, window_start, window_end)

            # Проверяем минимальный зазор
            candidate_ts = _local_hour_to_utc_ts(
                datetime.combine(search_day, datetime.min.time()),
                chosen_hour,
                timezone,
            )

            min_gap = _compute_min_gap(model)
            conflict = any(abs(candidate_ts - occ) < min_gap for occ in occupied_timestamps)

            if not conflict and candidate_ts > base_ts:
                app_log = f"[Расписание] {search_day} {chosen_hour:02d}:xx {timezone} (модель: {'обучена' if model.get('hour_heatmap') else 'стартовая'})"
                logger.info(app_log)
                return candidate_ts, chosen_hour

        search_day += timedelta(days=1)

    # Fallback: просто добавить delay к last_ts
    delay = random.randint(
        pub.get('publish_delay_min', 7200),
        pub.get('publish_delay_max', 10800),
    )
    fallback_ts = base_ts + delay
    local_dt = datetime.utcfromtimestamp(fallback_ts) + timedelta(hours=offset_hours)
    return fallback_ts, local_dt.hour


def _compute_min_gap(model: dict) -> int:
    """
    Вычислить минимальный зазор между постами.
    Чем больше данных — тем точнее. Стартово — 3 часа.
    """
    heatmap = model.get('hour_heatmap', {})
    if not heatmap:
        return _MIN_GAP_SECONDS_DEFAULT

    # Найти минимальный интервал между топ-5 часами
    sorted_hours = sorted(heatmap.keys(), key=lambda h: heatmap[h], reverse=True)
    top = sorted(int(h) for h in sorted_hours[:5])
    if len(top) < 2:
        return _MIN_GAP_SECONDS_DEFAULT

    gaps = [(top[i+1] - top[i]) * 3600 for i in range(len(top)-1)]
    min_gap = min(gaps)
    # Минимум 1 час, максимум 6 часов
    return max(3600, min(min_gap, 6 * 3600))
