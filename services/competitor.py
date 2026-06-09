# -*- coding: utf-8 -*-
"""Анализ конкурентов: топ посты по ER, паттерны времени, тренды.

Данные пишутся в storage/{profile_id}/competitor_data.json.
Никакого UI — только накопление сигнала для services/learning.py.
"""

import json
import os
import time
import threading
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from config import app_state, STORAGE_DIR, logger


_LOCK = threading.Lock()
MAX_POSTS_PER_SOURCE = 200   # сколько последних постов анализируем у конкурента
SCAN_INTERVAL_SEC = 21600    # раз в 6 часов


def _data_file(profile_id: str) -> Path:
    return STORAGE_DIR / profile_id / 'competitor_data.json'


def _load_data(profile_id: str) -> dict:
    f = _data_file(profile_id)
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_data(profile_id: str, data: dict) -> None:
    f = _data_file(profile_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.parent / f'.tmp_{f.name}'
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, f)


def _calc_er(post: dict) -> float:
    """ER = (likes + reposts*2 + comments) / max(views, 1) * 100."""
    likes = post.get('likes', {}).get('count', 0)
    reposts = post.get('reposts', {}).get('count', 0)
    comments = post.get('comments', {}).get('count', 0)
    views = post.get('views', {}).get('count', 1) or 1
    return round((likes + reposts * 2 + comments) / views * 100, 4)


def _content_type(post: dict) -> str:
    atts = post.get('attachments', [])
    types = {a.get('type') for a in atts}
    if 'video' in types:
        return 'video'
    if 'photo' in types:
        photos = [a for a in atts if a.get('type') == 'photo']
        return 'multi_photo' if len(photos) > 1 else 'photo'
    if post.get('text'):
        return 'text'
    return 'other'


def scan_competitor(community_id: str) -> dict | None:
    """Просканировать одного конкурента, вернуть агрегированные данные."""
    from vk.api import get_vk_api, vk_call_safe, normalize_owner_id

    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    if not user_token:
        logger.warning('competitor: user_token не задан')
        return None

    try:
        vk = get_vk_api(user_token, vk_cfg.get('api_version', '5.131'))
        owner_id = normalize_owner_id(community_id)
    except Exception as e:
        logger.warning(f'competitor: не удалось инициализировать VK API: {e}')
        return None

    posts: list[dict] = []
    offset = 0
    batch = 100

    while len(posts) < MAX_POSTS_PER_SOURCE:
        try:
            resp = vk_call_safe(
                vk.wall.get,
                owner_id=owner_id,
                count=batch,
                offset=offset,
                filter='owner',
            )
        except Exception as e:
            logger.warning(f'competitor {community_id}: {e}')
            break

        items = resp.get('items', []) if isinstance(resp, dict) else []
        if not items:
            break
        posts.extend(items)
        offset += len(items)
        if len(items) < batch:
            break
        time.sleep(0.5)

    if not posts:
        return None

    # Считаем ER для каждого поста
    scored = []
    for p in posts:
        er = _calc_er(p)
        ctype = _content_type(p)
        hour = datetime.fromtimestamp(p.get('date', 0)).hour if p.get('date') else -1
        scored.append({
            'post_id': p.get('id'),
            'date': p.get('date'),
            'hour': hour,
            'er': er,
            'views': p.get('views', {}).get('count', 0),
            'likes': p.get('likes', {}).get('count', 0),
            'reposts': p.get('reposts', {}).get('count', 0),
            'comments': p.get('comments', {}).get('count', 0),
            'type': ctype,
            'text_len': len(p.get('text', '')),
            'has_hashtags': '#' in p.get('text', ''),
        })

    # Топ 20 постов по ER
    top20 = sorted(scored, key=lambda x: x['er'], reverse=True)[:20]

    # Heatmap по часам: средний ER
    hour_er: dict[int, list[float]] = defaultdict(list)
    hour_views: dict[int, list[int]] = defaultdict(list)
    for s in scored:
        if s['hour'] >= 0:
            hour_er[s['hour']].append(s['er'])
            hour_views[s['hour']].append(s['views'])

    hour_heatmap = {}
    for h in range(24):
        ers = hour_er.get(h, [])
        vs = hour_views.get(h, [])
        hour_heatmap[str(h)] = {
            'avg_er': round(sum(ers) / len(ers), 4) if ers else 0.0,
            'avg_views': round(sum(vs) / len(vs)) if vs else 0,
            'posts': len(ers),
        }

    # Топ типы контента
    type_counts = Counter(s['type'] for s in scored)
    type_er: dict[str, list[float]] = defaultdict(list)
    for s in scored:
        type_er[s['type']].append(s['er'])
    content_stats = {
        ctype: {
            'count': cnt,
            'avg_er': round(sum(type_er[ctype]) / cnt, 4),
        }
        for ctype, cnt in type_counts.items()
    }

    # Средний интервал между постами (в часах)
    dates = sorted([s['date'] for s in scored if s.get('date')], reverse=True)
    avg_interval_h = 0.0
    if len(dates) >= 2:
        gaps = [(dates[i] - dates[i + 1]) / 3600 for i in range(len(dates) - 1)]
        avg_interval_h = round(sum(gaps) / len(gaps), 2)

    # Лучшие часы (топ-6 по avg_er с минимум 2 постами)
    best_hours = sorted(
        [h for h in range(24) if hour_heatmap[str(h)]['posts'] >= 2],
        key=lambda h: hour_heatmap[str(h)]['avg_er'],
        reverse=True,
    )[:6]

    # Частые хештеги
    hashtag_counter: Counter = Counter()
    for p in posts:
        text = p.get('text', '')
        tags = [w for w in text.split() if w.startswith('#') and len(w) > 2]
        hashtag_counter.update(tags)
    top_hashtags = [tag for tag, _ in hashtag_counter.most_common(20)]

    return {
        'community_id': community_id,
        'scanned_at': int(time.time()),
        'total_posts': len(scored),
        'avg_er': round(sum(s['er'] for s in scored) / len(scored), 4),
        'avg_views': round(sum(s['views'] for s in scored) / len(scored)),
        'top20': top20,
        'hour_heatmap': hour_heatmap,
        'best_hours': best_hours,
        'content_stats': content_stats,
        'avg_post_interval_hours': avg_interval_h,
        'top_hashtags': top_hashtags,
    }


def scan_all_competitors() -> dict[str, Any]:
    """Просканировать всех конкурентов из профиля. Возвращает агрегат."""
    profile = app_state.profile
    profile_id = app_state.active_profile_id

    sources = [s for s in profile.get('sources', []) if s.get('enabled')]
    if not sources:
        logger.info('competitor: нет активных источников')
        return {}

    data = _load_data(profile_id)
    results: dict[str, dict] = {}

    for src in sources:
        cid = str(src.get('community_id', ''))
        if not cid:
            continue

        # Пропускаем если скан был менее 6ч назад
        existing = data.get(cid, {})
        if existing.get('scanned_at', 0) > int(time.time()) - SCAN_INTERVAL_SEC:
            logger.info(f'competitor {cid}: скан свежий, пропускаю')
            results[cid] = existing
            continue

        logger.info(f'competitor: сканирую {cid}')
        app_state.add_log(f'[Конкуренты] Сканирую {cid}', 'info')
        result = scan_competitor(cid)
        if result:
            data[cid] = result
            results[cid] = result
            logger.info(
                f'competitor {cid}: {result["total_posts"]} постов, '
                f'avg_er={result["avg_er"]}, best_hours={result["best_hours"]}'
            )
            app_state.add_log(
                f'[Конкуренты] {cid}: {result["total_posts"]} постов, '
                f'avg_er={result["avg_er"]:.2f}, часы={result["best_hours"][:3]}',
                'info'
            )
        time.sleep(1.0)

    if results:
        with _LOCK:
            _save_data(profile_id, data)

    return aggregate_competitors(data)


def aggregate_competitors(data: dict) -> dict:
    """Свести данные всех конкурентов в единый сигнал для обучения."""
    if not data:
        return {}

    # Взвешенный heatmap по часам (вес = количество постов у источника)
    agg_hour: dict[int, list[tuple[float, int]]] = defaultdict(list)  # (avg_er, posts)
    all_hashtags: Counter = Counter()
    all_content_stats: dict[str, list[float]] = defaultdict(list)
    best_hours_votes: Counter = Counter()

    for cid, source in data.items():
        hm = source.get('hour_heatmap', {})
        for h_str, hdata in hm.items():
            h = int(h_str)
            if hdata['posts'] > 0:
                agg_hour[h].append((hdata['avg_er'], hdata['posts']))

        for tag in source.get('top_hashtags', []):
            all_hashtags[tag] += 1

        for ctype, cdata in source.get('content_stats', {}).items():
            all_content_stats[ctype].append(cdata['avg_er'])

        for h in source.get('best_hours', []):
            best_hours_votes[h] += 1

    # Финальный heatmap: взвешенное среднее
    agg_heatmap = {}
    for h in range(24):
        pairs = agg_hour.get(h, [])
        if not pairs:
            agg_heatmap[h] = 0.0
        else:
            total_posts = sum(p for _, p in pairs)
            weighted_er = sum(er * p for er, p in pairs) / total_posts
            agg_heatmap[h] = round(weighted_er, 4)

    # Топ часы (голосование + ER)
    top_hours = sorted(
        range(24),
        key=lambda h: (best_hours_votes.get(h, 0), agg_heatmap.get(h, 0)),
        reverse=True,
    )[:6]

    # Лучший тип контента по ER
    best_content_type = max(
        all_content_stats,
        key=lambda t: sum(all_content_stats[t]) / max(len(all_content_stats[t]), 1),
        default='photo',
    )

    # ER каждого источника — для ранжирования при скачивании
    source_er = {
        cid: round(float(source.get('avg_er', 0.0)), 4)
        for cid, source in data.items()
    }

    return {
        'updated_at': int(time.time()),
        'sources_count': len(data),
        'agg_hour_heatmap': agg_heatmap,
        'recommended_hours': top_hours,
        'top_hashtags': [tag for tag, _ in all_hashtags.most_common(30)],
        'best_content_type': best_content_type,
        'content_er': {
            t: round(sum(ers) / len(ers), 4)
            for t, ers in all_content_stats.items()
        },
        'source_er': source_er,
    }


def get_competitor_insights(profile_id: str) -> dict:
    """Получить агрегированные инсайты конкурентов (без нового скана)."""
    data = _load_data(profile_id)
    return aggregate_competitors(data)


def competitor_scan_loop():
    """Фоновый поток: сканирует конкурентов каждые 6 часов."""
    # Первый запуск через 5 минут после старта (не перегружать старт)
    time.sleep(300)
    while True:
        try:
            result = scan_all_competitors()
            if result:
                hours = result.get('recommended_hours', [])
                logger.info(f'competitor scan: done, recommended_hours={hours}')
                app_state.add_log(f'[Конкуренты] Скан завершён, рекомендуемые часы: {hours}', 'info')
        except Exception as e:
            logger.warning(f'competitor_scan_loop: {e}')
            app_state.add_log(f'[Конкуренты] Ошибка скана: {e}', 'error')
        time.sleep(SCAN_INTERVAL_SEC)
