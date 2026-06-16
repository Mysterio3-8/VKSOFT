# -*- coding: utf-8 -*-
"""Единый планировщик слотов публикации.

Все циклы автопилота (posts/photos/videos/clips) резервируют время
публикации через reserve_slot(), чтобы не коллидировать друг с другом
и не превышать дневные лимиты по типам медиа.
"""

import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import app_state, logger

_DEFAULT_MIN_GAP_SECONDS = 1800  # 30 минут между любыми двумя постами


def _slots_file() -> Path:
    return app_state.scheduled_slots_file


def _lock_file() -> Path:
    return app_state.scheduled_slots_file.with_suffix('.lock')


def _acquire_lock(timeout: float = 10.0) -> Optional[object]:
    """Простой файловый лок через эксклюзивное создание файла."""
    lock_path = _lock_file()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            fd = open(lock_path, 'x')
            return fd
        except FileExistsError:
            # Если лок старше 30с — считаем его подвисшим и забираем
            try:
                if time.time() - lock_path.stat().st_mtime > 30:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            time.sleep(0.1)
    return None


def _release_lock(fd: Optional[object]) -> None:
    if fd is None:
        return
    try:
        fd.close()
    finally:
        _lock_file().unlink(missing_ok=True)


def _load_slots() -> dict:
    f = _slots_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            return {'slots': []}
    return {'slots': []}


def _save_slots(data: dict) -> None:
    import tempfile
    f = _slots_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        'w', dir=f.parent, delete=False, encoding='utf-8', suffix='.tmp'
    ) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp_path = tmp.name
    Path(tmp_path).replace(f)


def _prune_old_slots(data: dict) -> dict:
    """Убрать слоты в прошлом (старше 1 дня), чтобы файл не разрастался."""
    cutoff = int(time.time()) - 86400
    data['slots'] = [s for s in data['slots'] if s['ts'] >= cutoff]
    return data


def _min_gap_seconds(profile: dict) -> int:
    try:
        from services.smart_scheduler import _compute_min_gap
        from services.engagement import load_engagement_model
        model = load_engagement_model(app_state.active_profile_id)
        return max(_DEFAULT_MIN_GAP_SECONDS, _compute_min_gap(model))
    except Exception:
        return _DEFAULT_MIN_GAP_SECONDS


_DEFAULT_VIDEOS_DAILY_LIMIT = 1
_DEFAULT_CLIPS_DAILY_LIMIT = 2
_DEFAULT_PHOTOS_DAILY_LIMIT = 1


def _daily_limit(media_type: str, profile: dict) -> Optional[int]:
    """Дневной лимит для типа медиа. None = без лимита."""
    if media_type == 'videos':
        limit = profile.get('videos_settings', {}).get('daily_limit')
        return int(limit) if limit else _DEFAULT_VIDEOS_DAILY_LIMIT
    if media_type == 'clips':
        limit = profile.get('clips_settings', {}).get('daily_limit')
        return int(limit) if limit else _DEFAULT_CLIPS_DAILY_LIMIT
    if media_type == 'photos':
        # У фото свой дневной лимит, отдельно от постов (раньше делили
        # max_posts_per_day). Дефолт 1 — анти-спам «по чуть-чуть».
        limit = profile.get('photos_settings', {}).get('daily_limit')
        return int(limit) if limit else _DEFAULT_PHOTOS_DAILY_LIMIT
    if media_type == 'posts':
        limit = int(profile.get('publishing_settings', {}).get('max_posts_per_day', 0))
        return limit or None
    return None


def _count_for_day(slots: list, media_type: str, day_start: int, day_end: int) -> int:
    return sum(
        1 for s in slots
        if s['media_type'] == media_type and day_start <= s['ts'] < day_end
    )


def _count_all_for_day(slots: list, day_start: int, day_end: int) -> int:
    return sum(1 for s in slots if day_start <= s['ts'] < day_end)


def _global_daily_limit(profile: dict) -> Optional[int]:
    """Потолок публикаций в день по ВСЕМ типам сразу. 0/нет = без лимита."""
    limit = int(profile.get('publishing_settings', {}).get('max_total_per_day', 0) or 0)
    return limit or None


def _day_bounds(ts: int) -> tuple[int, int]:
    day_start = int(
        datetime.fromtimestamp(ts).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
    )
    return day_start, day_start + 86400


def _apply_publish_window(ts: int, profile: dict) -> int:
    """Сдвинуть слот в дневное окно публикации, чтобы не постить ночью.

    Опционально (publishing_settings.apply_window_to_media). Использует уже
    настроенное окно постов publish_hours_start/end — отдельной настройки не
    заводим. Выключено по умолчанию: поведение медиа-циклов не меняется,
    пока пользователь явно не включит.
    """
    ps = profile.get('publishing_settings', {}) or {}
    if not ps.get('apply_window_to_media'):
        return ts
    if not ps.get('publish_hours_enabled', True):
        return ts
    start = int(ps.get('publish_hours_start', 8))
    end = int(ps.get('publish_hours_end', 22))
    if not (0 <= start < end <= 24):
        return ts
    d = datetime.fromtimestamp(ts)
    if d.hour < start:
        d = d.replace(hour=start, minute=random.randint(0, 59), second=random.randint(0, 59))
    elif d.hour >= end:
        from datetime import timedelta
        d = (d + timedelta(days=1)).replace(
            hour=start, minute=random.randint(0, 59), second=random.randint(0, 59)
        )
    return int(d.timestamp())


def reserve_slot(
    media_type: str,
    delay_min: int,
    delay_max: int,
    profile: Optional[dict] = None,
) -> int:
    """Зарезервировать timestamp публикации для media_type.

    Гарантирует:
    - результат в будущем
    - зазор >= min_gap от ЛЮБОГО другого зарезервированного слота (любого типа)
    - не превышает дневной лимит media_type (если задан в конфиге);
      при превышении лимита на сегодня сдвигает на следующий день
    """
    from services.storage import read_last_scheduled, write_last_scheduled

    profile = profile if profile is not None else app_state.profile
    min_gap = _min_gap_seconds(profile)
    daily_limit = _daily_limit(media_type, profile)
    global_limit = _global_daily_limit(profile)

    lock = _acquire_lock()
    try:
        data = _prune_old_slots(_load_slots())
        slots = data['slots']
        occupied = sorted(s['ts'] for s in slots)

        base = max(
            int(time.time()),
            read_last_scheduled() or 0,
            occupied[-1] if occupied else 0,
        )
        candidate = base + random.randint(delay_min, delay_max)

        # Сдвигаем, пока не найдём слот без коллизий по зазору
        max_iterations = 200
        for _ in range(max_iterations):
            conflict = any(abs(candidate - occ) < min_gap for occ in occupied)
            if not conflict:
                break
            candidate += random.randint(delay_min, delay_max)

        # Проверка дневного лимита: если на день candidate уже набрано
        # daily_limit постов этого типа — переносим на следующий день
        if daily_limit is not None:
            for _ in range(14):  # не более 14 дней вперёд
                day_start, day_end = _day_bounds(candidate)
                if _count_for_day(slots, media_type, day_start, day_end) < daily_limit:
                    break
                candidate = day_end + random.randint(delay_min, delay_max)
                occupied = sorted(occupied + [candidate])

        # Глобальный потолок: суммарно по всем типам за день. Защита от спама,
        # когда включены все циклы сразу. Выключен по умолчанию (0 = без лимита).
        if global_limit is not None:
            for _ in range(14):
                day_start, day_end = _day_bounds(candidate)
                if _count_all_for_day(slots, day_start, day_end) < global_limit:
                    break
                candidate = day_end + random.randint(delay_min, delay_max)
                occupied = sorted(occupied + [candidate])

        # Дневное окно публикации (опционально) — не постить ночью.
        candidate = _apply_publish_window(candidate, profile)
        for _ in range(50):
            if not any(abs(candidate - occ) < min_gap for occ in occupied):
                break
            candidate = _apply_publish_window(candidate + min_gap, profile)

        slots.append({'media_type': media_type, 'ts': candidate})
        _save_slots(data)
        write_last_scheduled(candidate)
        return candidate
    finally:
        _release_lock(lock)


def record_slot(media_type: str, ts: int) -> None:
    """Зарегистрировать уже выбранный timestamp (posts со своим умным
    расписанием) в общем реестре, чтобы photos/videos/clips не коллидировали
    с ним через min_gap.
    """
    lock = _acquire_lock()
    try:
        data = _prune_old_slots(_load_slots())
        data['slots'].append({'media_type': media_type, 'ts': int(ts)})
        _save_slots(data)
    finally:
        _release_lock(lock)
