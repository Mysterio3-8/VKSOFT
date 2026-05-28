# -*- coding: utf-8 -*-
"""Трекинг опубликованных постов + алерты — пункты 7, 10."""

import json
import time
import threading
from pathlib import Path
from config import app_state, STORAGE_DIR, logger


def _file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'post_tracker.json'


def _load() -> list:
    f = _file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            pass
    return []


def _save(data: list):
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        if len(data) > 600:
            data = data[-500:]
        f.write_text(json.dumps(data), encoding='utf-8')
    except Exception as e:
        logger.warning(f'tracker _save: {e}')


def track(vk_post_id: int, owner_id: str, source_cid: str = ''):
    """Зарегистрировать пост сразу после публикации."""
    data = _load()
    data.append({
        'post_id': vk_post_id,
        'owner_id': owner_id,
        'source_cid': source_cid,
        'published_at': int(time.time()),
        'checked': False,
        'likes': 0,
        'views': 0,
        'reposts': 0,
    })
    _save(data)


def get_all() -> list:
    return _load()


def get_summary() -> dict:
    data = _load()
    checked = [p for p in data if p.get('checked')]
    if not checked:
        return {'total': len(data), 'checked': 0, 'avg_views': 0, 'avg_likes': 0, 'top': []}
    avg_views = round(sum(p['views'] for p in checked) / len(checked))
    avg_likes = round(sum(p['likes'] for p in checked) / len(checked))
    top = sorted(checked, key=lambda p: p.get('likes', 0), reverse=True)[:5]
    return {
        'total': len(data),
        'checked': len(checked),
        'avg_views': avg_views,
        'avg_likes': avg_likes,
        'top': top,
    }


def run_check():
    """Проверить статистику постов опубликованных 24ч назад."""
    from vk.api import get_vk_api, vk_call_safe

    profile = app_state.profile
    tracking_cfg = profile.get('tracking', {})
    if not tracking_cfg.get('enabled', True):
        return

    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    if not user_token:
        return

    check_after = 86400  # 24 часа
    now = int(time.time())

    try:
        data = _load()
        vk = get_vk_api(user_token, vk_cfg.get('api_version', '5.131'))
        updated = False

        unchecked = [
            p for p in data
            if not p.get('checked') and now - p.get('published_at', now) >= check_after
        ]
        if not unchecked:
            return

        for i in range(0, len(unchecked), 25):
            batch = unchecked[i:i + 25]
            try:
                ids = ','.join(f'{p["owner_id"]}_{p["post_id"]}' for p in batch)
                resp = vk_call_safe(vk.wall.getById, posts=ids, extended=1)
                items = (resp.get('items', []) if isinstance(resp, dict) else resp) or []
                stats_map = {item['id']: item for item in items}
                for p in batch:
                    item = stats_map.get(p['post_id'], {})
                    if item:
                        p['likes']   = item.get('likes',   {}).get('count', 0)
                        p['views']   = item.get('views',   {}).get('count', 0)
                        p['reposts'] = item.get('reposts', {}).get('count', 0)
                    p['checked'] = True
                    updated = True
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f'tracker batch: {e}')

        if updated:
            _save(data)

        # Алерт: подозрительно низкий охват
        if tracking_cfg.get('alert_low_views', False):
            checked = [p for p in data if p.get('checked') and p.get('views', 0) > 0]
            if len(checked) >= 10:
                avg = sum(p['views'] for p in checked) / len(checked)
                very_low = [p for p in checked[-20:] if p['views'] < avg * 0.3]
                if len(very_low) >= 3:
                    logger.warning(
                        f'Низкий охват: {len(very_low)} постов получили меньше 30% от среднего ({int(avg)} просм.)'
                    )

    except Exception as e:
        logger.warning(f'tracker run_check: {e}')


def tracker_loop():
    """Фоновый поток — проверяет посты каждый час."""
    while True:
        time.sleep(3600)
        try:
            run_check()
        except Exception as e:
            logger.warning(f'tracker_loop: {e}')
