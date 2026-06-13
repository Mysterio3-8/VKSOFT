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
    from config import STORAGE_DIR
    return STORAGE_DIR / app_state.active_profile_id / 'scheduled_slots.json'


def _lock_file() -> Path:
    from config import STORAGE_DIR
    return STORAGE_DIR / app_state.active_profile_id / 'scheduled_slots.lock'


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


def _daily_limit(media_type: str, profile: dict) -> Optional[int]:
    """Дневной лимит для типа медиа. None = без лимита."""
    if media_type == 'videos':
        return int(profile.get('videos_settings', {}).get('daily_limit', 0)) or None
    if media_type == 'clips':
        return int(profile.get('clips_settings', {}).get('daily_limit', 0)) or None
    if media_type in ('posts', 'photos'):
        limit = int(profile.get('publishing_settings', {}).get('max_posts_per_day', 0))
        return limit or None
    return None


def _count_for_day(slots: list, media_type: str, day_start: int, day_end: int) -> int:
    return sum(
        1 for s in slots
        if s['media_type'] == media_type and day_start <= s['ts'] < day_end
    )


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
                day_start = int(
                    datetime.fromtimestamp(candidate).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ).timestamp()
                )
                day_end = day_start + 86400
                if _count_for_day(slots, media_type, day_start, day_end) < daily_limit:
                    break
                candidate = day_end + random.randint(delay_min, delay_max)
                occupied = sorted(occupied + [candidate])

        slots.append({'media_type': media_type, 'ts': candidate})
        _save_slots(data)
        write_last_scheduled(candidate)
        return candidate
    finally:
        _release_lock(lock)
