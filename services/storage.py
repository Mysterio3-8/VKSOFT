# -*- coding: utf-8 -*-
"""Storage helpers: offsets, stats, daily_log, last_scheduled."""

import json
from pathlib import Path
from typing import Dict, Optional

from config import app_state, STORAGE_DIR, logger


def read_offsets() -> Dict:
    try:
        f = app_state.offsets_file
        if f.exists():
            return json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def save_offset(cid: str, offset: int):
    offs = read_offsets()
    offs[str(cid)] = offset
    try:
        app_state.offsets_file.write_text(json.dumps(offs), encoding='utf-8')
    except Exception as e:
        logger.warning(f'save_offset: {e}')


def clear_offset(cid: str):
    offs = read_offsets()
    offs.pop(str(cid), None)
    try:
        app_state.offsets_file.write_text(json.dumps(offs), encoding='utf-8')
    except Exception:
        pass


def read_last_scheduled() -> Optional[int]:
    try:
        f = app_state.last_scheduled_file
        if f.exists():
            first_line = f.read_text(encoding='utf-8').splitlines()[0].strip()
            return int(first_line) if first_line else None
    except Exception:
        pass
    return None


def write_last_scheduled(ts: int):
    try:
        from datetime import datetime as _dt
        human = _dt.fromtimestamp(int(ts)).strftime('%d.%m.%Y %H:%M')
        updated = _dt.now().strftime('%d.%m.%Y %H:%M')
        content = f'{int(ts)}\n# Дата публикации: {human}\n# Обновлено: {updated}\n'
        app_state.last_scheduled_file.write_text(content, encoding='utf-8')
    except Exception as e:
        logger.warning(f'write_last_scheduled: {e}')


def get_dir_size_mb(path: Path) -> float:
    try:
        total = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        return round(total / 1024 / 1024, 1)
    except Exception:
        return 0.0


def read_monitor_last_seen() -> Dict:
    try:
        f = app_state.monitor_last_seen_file
        if f.exists():
            return json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def save_monitor_last_seen(data: Dict):
    try:
        f = app_state.monitor_last_seen_file
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data), encoding='utf-8')
    except Exception as e:
        logger.warning(f'monitor_save_last_seen: {e}')


def read_monitor_published() -> set:
    try:
        f = app_state.monitor_published_file
        if f.exists():
            return set(json.loads(f.read_text(encoding='utf-8')))
    except Exception:
        pass
    return set()


def add_monitor_published(cid: str, post_id: int):
    ids = read_monitor_published()
    ids.add(f'{cid}_{post_id}')
    if len(ids) > 5000:
        ids = set(list(ids)[-4000:])
    try:
        f = app_state.monitor_published_file
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(list(ids)), encoding='utf-8')
    except Exception as e:
        logger.warning(f'monitor_add_published: {e}')
