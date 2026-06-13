# -*- coding: utf-8 -*-
"""Трекинг опубликованных постов: снимки метрик, нормированный score, алерты."""

import json
import statistics
import time
import threading
from datetime import datetime
from pathlib import Path
from config import app_state, STORAGE_DIR, logger

# Снимки метрик по возрасту поста — velocity и ранние сигналы (P0 из отчёта)
SNAPSHOT_HOURS = [1, 6, 24, 72]

NORM_CAP = 3.0  # норма к медиане формата обрезается сверху — один выброс не ломает шкалу


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


def track(
    vk_post_id: int,
    owner_id: str,
    source_cid: str = '',
    published_at: int | None = None,
    caption_category: str = '',
    caption_text: str = '',
    caption_id: str = '',
    media_type: str = 'photo',
    overlay_family: str = '',
):
    """Зарегистрировать пост сразу после публикации."""
    data = _load()
    entry = {
        'post_id': vk_post_id,
        'owner_id': owner_id,
        'source_cid': source_cid,
        'published_at': int(published_at or time.time()),
        'media_type': media_type or 'photo',
        'checked': False,
        'likes': 0,
        'views': 0,
        'reposts': 0,
        'comments': 0,
        'snapshots': {},
    }
    if caption_category:
        entry['caption_category'] = caption_category
        entry['caption_text'] = caption_text
        if caption_id:
            entry['caption_id'] = caption_id
    if overlay_family:
        entry['overlay_family'] = overlay_family
    data.append(entry)
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
        comments = int(post.get('comments', 0) or 0)
        score = views + likes * 10 + comments * 50 + reposts * 25
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


def caption_engagement_score(post: dict) -> float:
    """Вовлечённость поста: лайки×1, комменты×4, репосты×8 (формула из отчёта)."""
    likes = int(post.get('likes', 0) or 0)
    comments = int(post.get('comments', 0) or 0)
    reposts = int(post.get('reposts', 0) or 0)
    return likes + comments * 4 + reposts * 8


def post_velocity(post: dict) -> float | None:
    """views_1h / views_24h по снимкам — скорость раннего разгона."""
    snaps = post.get('snapshots') or {}
    h1 = snaps.get('1')
    h24 = snaps.get('24')
    if not h1 or not h24:
        return None
    return int(h1.get('views', 0) or 0) / max(int(h24.get('views', 0) or 0), 1)


def _eligible(post: dict) -> bool:
    return bool(
        post.get('checked') and not post.get('missing')
        and int(post.get('views', 0) or 0) > 0
    )


def build_format_baselines(data: list) -> dict:
    """Медианы ER/views/velocity по формату — база для нормировки score.

    Без нормировки внутри формата клипы всегда съедают фото за счёт
    большего числа просмотров.
    """
    grouped: dict[str, dict[str, list]] = {}
    for post in data:
        if not _eligible(post):
            continue
        fmt = post.get('media_type', 'photo')
        bucket = grouped.setdefault(fmt, {'er': [], 'views': [], 'velocity': []})
        views = int(post.get('views', 0) or 0)
        bucket['er'].append(caption_engagement_score(post) / views)
        bucket['views'].append(views)
        velocity = post_velocity(post)
        if velocity is not None:
            bucket['velocity'].append(velocity)

    baselines = {}
    for fmt, values in grouped.items():
        baselines[fmt] = {
            'er': statistics.median(values['er']) if values['er'] else 0.0,
            'views': statistics.median(values['views']) if values['views'] else 0.0,
            'velocity': statistics.median(values['velocity']) if values['velocity'] else 0.0,
            'posts': len(values['views']),
        }
    return baselines


def _norm(value: float, baseline: float) -> float:
    if not baseline or baseline <= 0:
        return 1.0  # нет базы — нейтрально, не наказываем и не награждаем
    return min(value / baseline, NORM_CAP)


def compute_post_score(post: dict, baselines: dict) -> float:
    """Нормированный score поста относительно медианы его формата.

    1.0 = типичный пост формата; ≥1.5 — promote; <0.8 — kill (пороги отчёта).
    """
    views = int(post.get('views', 0) or 0)
    if views <= 0:
        return 0.0
    fmt = post.get('media_type', 'photo')
    base = baselines.get(fmt, {})
    er_norm = _norm(caption_engagement_score(post) / views, base.get('er', 0))
    views_norm = _norm(views, base.get('views', 0))
    velocity = post_velocity(post)
    if velocity is not None and base.get('velocity'):
        score = 0.5 * er_norm + 0.3 * views_norm + 0.2 * _norm(velocity, base['velocity'])
    else:
        score = 0.6 * er_norm + 0.4 * views_norm
    return round(score, 4)


def get_scored_posts() -> list:
    """Все проверенные посты с нормированным score (для источников/победителей)."""
    data = _load()
    baselines = build_format_baselines(data)
    return [
        {**post, 'norm_score': compute_post_score(post, baselines)}
        for post in data if _eligible(post)
    ]


def build_caption_stats(data: list, media_type: str = '') -> dict:
    """Агрегировать engagement по категориям подписей (опционально по формату).

    ER = score/views, чтобы убрать зависимость от времени публикации
    (часы уже оптимизирует learning через heatmap).
    """
    stats: dict[str, dict] = {}
    for post in data:
        category = post.get('caption_category', '')
        if not category:
            continue
        if media_type and post.get('media_type', 'photo') != media_type:
            continue
        if not _eligible(post):
            continue
        views = int(post.get('views', 0) or 0)
        bucket = stats.setdefault(category, {
            'posts': 0, 'views': 0, 'likes': 0, 'comments': 0, 'reposts': 0, 'er_sum': 0.0,
        })
        bucket['posts'] += 1
        bucket['views'] += views
        bucket['likes'] += int(post.get('likes', 0) or 0)
        bucket['comments'] += int(post.get('comments', 0) or 0)
        bucket['reposts'] += int(post.get('reposts', 0) or 0)
        bucket['er_sum'] += caption_engagement_score(post) / views

    for bucket in stats.values():
        bucket['avg_er'] = round(bucket['er_sum'] / bucket['posts'], 5)
        del bucket['er_sum']
    return stats


def get_caption_stats(media_type: str = '') -> dict:
    return build_caption_stats(_load(), media_type)


def build_overlay_stats(data: list) -> dict:
    """Агрегаты по семействам hook-оверлеев (только клипы)."""
    stats: dict[str, dict] = {}
    for post in data:
        family = post.get('overlay_family', '')
        if not family or not _eligible(post):
            continue
        views = int(post.get('views', 0) or 0)
        bucket = stats.setdefault(family, {'posts': 0, 'er_sum': 0.0})
        bucket['posts'] += 1
        bucket['er_sum'] += caption_engagement_score(post) / views

    for bucket in stats.values():
        bucket['avg_er'] = round(bucket['er_sum'] / bucket['posts'], 5)
        del bucket['er_sum']
    return stats


def get_overlay_stats() -> dict:
    return build_overlay_stats(_load())


def mark_republished(post_id: int, republished_at: int | None = None) -> None:
    """Пометить пост-победитель как переизданный (для cooldown повторов)."""
    data = _load()
    for post in data:
        if post.get('post_id') == post_id:
            post['republished_at'] = int(republished_at or time.time())
            _save(data)
            return


def _due_snapshot_hour(post: dict, now: int) -> int | None:
    """Самый поздний снимок, который пора снять. None — снимать нечего."""
    if post.get('missing'):
        return None
    published_at = int(post.get('published_at', 0) or 0)
    if published_at <= 0 or published_at > now:
        return None  # отложенный пост ещё не вышел
    age_hours = (now - published_at) / 3600
    snaps = post.get('snapshots') or {}
    due = None
    for h in SNAPSHOT_HOURS:
        if age_hours >= h and str(h) not in snaps:
            due = h
    return due


def run_check():
    """Снять очередные снимки метрик (1ч/6ч/24ч/72ч) для постов, где пора."""
    from vk.api import get_vk_api, vk_call_safe

    profile = app_state.profile
    tracking_cfg = profile.get('tracking', {})
    if not tracking_cfg.get('enabled', True):
        return

    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    if not user_token:
        return

    now = int(time.time())

    try:
        data = _load()
        vk = get_vk_api(user_token, vk_cfg.get('api_version', '5.131'))
        updated = False

        pending = [(p, _due_snapshot_hour(p, now)) for p in data]
        pending = [(p, due) for p, due in pending if due is not None]
        if not pending:
            return

        for i in range(0, len(pending), 25):
            batch = pending[i:i + 25]
            try:
                ids = ','.join(f'{p["owner_id"]}_{p["post_id"]}' for p, _ in batch)
                resp = vk_call_safe(vk.wall.getById, posts=ids, extended=1)
                items = (resp.get('items', []) if isinstance(resp, dict) else resp) or []
                stats_map = {item['id']: item for item in items}
                for p, due in batch:
                    item = stats_map.get(p['post_id'])
                    if item:
                        metrics = {
                            'views':    item.get('views',    {}).get('count', 0),
                            'likes':    item.get('likes',    {}).get('count', 0),
                            'reposts':  item.get('reposts',  {}).get('count', 0),
                            'comments': item.get('comments', {}).get('count', 0),
                        }
                        snaps = p.setdefault('snapshots', {})
                        snaps[str(due)] = {**metrics, 'captured_at': now}
                        # Верхний уровень — всегда самые свежие метрики
                        p.update(metrics)
                        if due >= 24:
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
                        p['comments'] = s.get('comments', {}).get('count', 0)
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
    """Фоновый поток — снимает метрики каждые 15 минут (нужен точный снимок 1ч)."""
    while True:
        time.sleep(900)
        try:
            run_check()
        except Exception as e:
            logger.warning(f'tracker_loop: {e}')
