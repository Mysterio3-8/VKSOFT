# -*- coding: utf-8 -*-
"""Анализатор ниш VK — поиск и ранжирование сообществ."""

import time
from datetime import datetime, timezone
from typing import List, Dict, Optional

import vk_api

from config import app_state, logger
from vk.api import get_vk_api, vk_call_safe

AUTO_KEYWORDS = [
    'юмор', 'фитнес', 'авто', 'кулинария', 'путешествия',
    'мотивация', 'технологии', 'животные', 'красота', 'спорт',
    'музыка', 'кино', 'игры', 'бизнес', 'психология',
    'дети', 'мода', 'здоровье', 'новости', 'природа',
]


def _score_community(members: int, avg_likes: float, posts_per_week: float, activity: float) -> float:
    if members <= 0:
        return 0.0
    engagement = avg_likes / max(posts_per_week, 1)
    return members * engagement * max(activity, 0.01)


def _normalize_scores(communities: List[Dict]) -> List[Dict]:
    if not communities:
        return communities
    max_score = max(c['raw_score'] for c in communities)
    if max_score == 0:
        for c in communities:
            c['score'] = 0.0
        return communities
    for c in communities:
        c['score'] = round(c['raw_score'] / max_score * 100, 1)
    return communities


def _analyze_community(vk, group: Dict) -> Optional[Dict]:
    gid = group.get('id')
    members = group.get('members_count', 0)
    if not gid or members < 1000:
        return None

    owner_id = f'-{gid}'
    try:
        wall = vk_call_safe(vk.wall.get, owner_id=owner_id, count=20, filter='owner')
    except vk_api.exceptions.ApiError as e:
        if getattr(e, 'code', 0) in (15, 19, 7):
            return None
        return None
    except Exception:
        return None

    items = wall.get('items', [])
    if not items:
        return None

    now_ts = int(datetime.now(timezone.utc).timestamp())
    week_ago = now_ts - 7 * 86400

    total_likes = sum(p.get('likes', {}).get('count', 0) for p in items)
    avg_likes = total_likes / len(items)

    recent = [p for p in items if p.get('date', 0) >= week_ago]
    activity_factor = len(recent) / len(items)

    if items:
        oldest_ts = min(p.get('date', now_ts) for p in items)
        span_weeks = max((now_ts - oldest_ts) / (7 * 86400), 0.01)
        posts_per_week = len(items) / span_weeks
    else:
        posts_per_week = 0.0

    raw_score = _score_community(members, avg_likes, posts_per_week, activity_factor)

    return {
        'id': gid,
        'name': group.get('name', ''),
        'screen_name': group.get('screen_name', ''),
        'members': members,
        'avg_likes': round(avg_likes, 1),
        'posts_per_week': round(posts_per_week, 1),
        'activity_factor': round(activity_factor, 2),
        'raw_score': raw_score,
        'score': 0.0,
    }


def _scan_keyword(vk, keyword: str) -> List[Dict]:
    try:
        resp = vk_call_safe(
            vk.groups.search,
            q=keyword,
            type='page',
            count=20,
            sort=0,
        )
    except Exception as e:
        logger.warning(f'groups.search "{keyword}": {e}')
        return []

    groups = resp.get('items', [])
    results = []
    for group in groups:
        time.sleep(0.35)
        community = _analyze_community(vk, group)
        if community:
            results.append(community)

    return _normalize_scores(results)


def run_niche_scan(keywords: List[str]) -> None:
    app_state.is_niche_scanning = True
    app_state.niche_results = []
    app_state.niche_progress = {'current': 0, 'total': len(keywords), 'keyword': ''}

    vk_cfg = app_state.profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    api_ver = vk_cfg.get('api_version', '5.131')

    if not user_token:
        app_state.add_log('Нишевый анализ: user_token не задан', 'error')
        app_state.is_niche_scanning = False
        return

    try:
        vk = get_vk_api(user_token, api_ver)
    except Exception as e:
        app_state.add_log(f'Нишевый анализ: ошибка VK API: {e}', 'error')
        app_state.is_niche_scanning = False
        return

    results = []
    for idx, keyword in enumerate(keywords):
        app_state.niche_progress = {'current': idx + 1, 'total': len(keywords), 'keyword': keyword}
        app_state.add_log(f'Анализ ниши: {keyword} ({idx + 1}/{len(keywords)})', 'info')

        communities = _scan_keyword(vk, keyword)
        top = max(communities, key=lambda c: c['score'], default=None) if communities else None

        results.append({
            'keyword': keyword,
            'communities': communities,
            'top_community': top,
            'avg_score': round(sum(c['score'] for c in communities) / len(communities), 1) if communities else 0.0,
            'count': len(communities),
        })

    results.sort(key=lambda r: r['avg_score'], reverse=True)
    app_state.niche_results = results
    app_state.niche_progress = {'current': len(keywords), 'total': len(keywords), 'keyword': ''}
    app_state.add_log(f'Анализ ниш завершён: {len(results)} ниш', 'info')
    app_state.is_niche_scanning = False
