# -*- coding: utf-8 -*-
"""Трекинг опубликованных постов + алерты — пункты 7, 10."""

import json
import time
import threading
from datetime import datetime
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


def track(vk_post_id: int, owner_id: str, source_cid: str = '', published_at: int | None = None):
    """Зарегистрировать пост сразу после публикации."""
    data = _load()
    data.append({
        'post_id': vk_post_id,
        'owner_id': owner_id,
        'source_cid': source_cid,
        'published_at': int(published_at or time.time()),
        'checked': False,
        'likes': 0,
        'views': 0,
        'reposts': 0,
    })
    _save(data)


def get_all() -> list:
    return _load()


def build_hour_heatmap(data: list) -> list:
    buckets = {
        hour: {'hour': hour, 'posts': 0, 'views': 0, 'likes': 0, 'reposts': 0, 'score': 0}
        for hour in range(24)
    }
    for post in data:
        if not post.get('checked'):
            continue
        if post.get('missing'):
            continue
        # Нулевые просмотры = пост не вышел или не отследился. Такие данные не
        # несут сигнала о лучшем времени — исключаем из обучения.
        if int(post.get('views', 0) or 0) <= 0:
            continue
        published_at = post.get('published_at')
        if not published_at:
            continue
        hour = datetime.fromtimestamp(int(published_at)).hour
        views = int(post.get('views', 0) or 0)
        likes = int(post.get('likes', 0) or 0)
        reposts = int(post.get('reposts', 0) or 0)
        score = views + likes * 10 + reposts * 25
        bucket = buckets[hour]
        bucket['posts'] += 1
        bucket['views'] += views
        bucket['likes'] += likes
        bucket['reposts'] += reposts
        bucket['score'] += score

    result = []
    for hour in range(24):
        bucket = buckets[hour]
        posts = max(bucket['posts'], 1)
        result.append({
            **bucket,
            'avg_views': round(bucket['views'] / posts),
            'avg_likes': round(bucket['likes'] / posts, 2),
            'avg_reposts': round(bucket['reposts'] / posts, 2),
            'avg_score': round(bucket['score'] / posts, 2),
        })
    return result


def get_summary() -> dict:
    data = _load()
    # Для обучения значимы только посты с реальными данными (views>0).
    checked = [p for p in data if p.get('checked') and not p.get('missing') and int(p.get('views', 0) or 0) > 0]
    heatmap = build_hour_heatmap(data)
    if not checked:
        return {
            'total': len(data),
            'checked': 0,
            'avg_views': 0,
            'avg_likes': 0,
            'top': [],
            'hour_heatmap': heatmap,
            # Нет данных → не подставляем peak_hours из профиля (они устаревшие).
            # Алгоритм сам выберет равномерный fallback.
            'recommended_hours': [],
        }
    avg_views = round(sum(p['views'] for p in checked) / len(checked))
    avg_likes = round(sum(p['likes'] for p in checked) / len(checked))
    top = sorted(checked, key=lambda p: p.get('likes', 0), reverse=True)[:5]
    recommended_hours = [
        item['hour']
        for item in sorted(
            [item for item in heatmap if item['posts'] > 0],
            key=lambda x: (x['avg_score'], x['posts']),
            reverse=True
        )[:6]
    ] or app_state.profile.get('peak_hours', {}).get('hours', [])
    return {
        'total': len(data),
        'checked': len(checked),
        'avg_views': avg_views,
        'avg_likes': avg_likes,
        'top': top,
        'hour_heatmap': heatmap,
        'recommended_hours': recommended_hours,
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
                    item = stats_map.get(p['post_id'])
                    if item:
                        p['likes']   = item.get('likes',   {}).get('count', 0)
                        p['views']   = item.get('views',   {}).get('count', 0)
                        p['reposts'] = item.get('reposts', {}).get('count', 0)
                        p['checked'] = True
                        updated = True
                    else:
                        # Пост не найден (удалён/не вышел). Не помечаем checked —
                        # иначе нулевые views навсегда отравят обучение. Считаем
                        # попытки и сдаёмся после нескольких.
                        p['check_attempts'] = int(p.get('check_attempts', 0)) + 1
                        if p['check_attempts'] >= 3:
                            p['checked'] = True
                            p['missing'] = True
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
                    msg = f'Низкий охват: {len(very_low)} постов < 30% от среднего ({int(avg)} просм.)'
                    logger.warning(msg)
                    app_state.add_log(f'[Трекер] ⚠️ {msg}', 'warning')

    except Exception as e:
        logger.warning(f'tracker run_check: {e}')
        app_state.add_log(f'[Трекер] Ошибка проверки: {e}', 'error')


def bootstrap_from_wall():
    """Подтянуть всю историю постов со стены своей группы в трекер.

    Вызывается при старте. Постранично читает wall.get до тех пор пока
    не встретит только уже известные посты (значит дальше всё старое).
    Сразу проставляет views/likes — посты уже вышли, ждать 24ч не нужно.
    """
    from vk.api import get_vk_api, vk_call_safe

    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    group_id = str(vk_cfg.get('group_id', '')).strip().lstrip('-')
    if not user_token or not group_id:
        return

    try:
        vk = get_vk_api(user_token, vk_cfg.get('api_version', '5.131'))
        owner_id = f'-{group_id}'

        data = _load()
        known_ids = {p['post_id'] for p in data}

        all_new: list = []
        offset = 0
        batch_size = 100

        while True:
            resp = vk_call_safe(vk.wall.get, owner_id=owner_id, count=batch_size, offset=offset, filter='owner')
            items = (resp.get('items', []) if isinstance(resp, dict) else []) or []
            if not items:
                break

            new_in_batch = 0
            for item in items:
                pid = item.get('id')
                if not pid or pid in known_ids:
                    continue
                known_ids.add(pid)
                all_new.append({
                    'post_id': pid,
                    'owner_id': owner_id,
                    'source_cid': '',
                    'published_at': int(item.get('date', time.time())),
                    'checked': False,
                    'likes': 0,
                    'views': 0,
                    'reposts': 0,
                    '_bootstrapped': True,
                })
                new_in_batch += 1

            # Страница полностью из известных — дальше только старьё
            if new_in_batch == 0:
                break

            offset += batch_size
            time.sleep(0.4)

        if not all_new:
            logger.info('tracker bootstrap: нет новых постов для добавления')
            return

        # Сразу проставляем stats — посты уже вышли
        for i in range(0, len(all_new), 25):
            batch = all_new[i:i + 25]
            try:
                ids = ','.join(f'{p["owner_id"]}_{p["post_id"]}' for p in batch)
                stat_resp = vk_call_safe(vk.wall.getById, posts=ids, extended=1)
                stat_items = (stat_resp.get('items', []) if isinstance(stat_resp, dict) else stat_resp) or []
                stats_map = {s['id']: s for s in stat_items}
                for p in batch:
                    s = stats_map.get(p['post_id'])
                    if s:
                        p['likes'] = s.get('likes', {}).get('count', 0)
                        p['views'] = s.get('views', {}).get('count', 0)
                        p['reposts'] = s.get('reposts', {}).get('count', 0)
                        p['checked'] = True
                    else:
                        p['checked'] = True
                        p['missing'] = True
                time.sleep(0.3)
            except Exception as e:
                logger.warning(f'tracker bootstrap batch: {e}')

        data.extend(all_new)
        _save(data)
        with_views = sum(1 for p in all_new if p.get('views', 0) > 0)
        logger.info(f'tracker bootstrap: добавлено {len(all_new)} постов, {with_views} с views>0')
        app_state.add_log(f'[Трекер] Загружено {len(all_new)} постов, {with_views} с просмотрами', 'info')

    except Exception as e:
        logger.warning(f'tracker bootstrap_from_wall: {e}')
        app_state.add_log(f'[Трекер] Ошибка загрузки: {e}', 'error')


def tracker_loop():
    """Фоновый поток — проверяет посты каждый час."""
    while True:
        time.sleep(3600)
        try:
            run_check()
        except Exception as e:
            logger.warning(f'tracker_loop: {e}')
