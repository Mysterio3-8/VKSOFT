# -*- coding: utf-8 -*-
"""Качество источников: белые и стоп-листы по нормированному score.

Пороги из growth-отчёта: white — median score ≥ 1.2 при 10+ постах,
stop — median < 0.7 при 10+ постах (кулдаун 21 день, потом снова neutral).
Стоп-лист применяется в циклах скачивания: слабый источник не тратит квоту.
"""

import json
import os
import statistics
import time
from pathlib import Path

from config import STORAGE_DIR, app_state, logger

MIN_POSTS_FOR_DECISION = 10
WHITELIST_SCORE = 1.2
STOPLIST_SCORE = 0.7
STOPLIST_COOLDOWN_DAYS = 21


def _file(profile_id: str = None) -> Path:
    pid = profile_id or app_state.active_profile_id
    return STORAGE_DIR / pid / 'source_quality.json'


def load_states(profile_id: str = None) -> dict:
    f = _file(profile_id)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def _save_states(states: dict, profile_id: str = None) -> None:
    f = _file(profile_id)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.parent / f'.tmp_{f.name}'
        tmp.write_text(json.dumps(states, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, f)
    except Exception as exc:
        logger.warning(f'source_quality save: {exc}')


def build_source_stats(scored_posts: list) -> dict:
    """Median нормированного score по источникам (только посты с source_cid)."""
    by_source: dict[str, list] = {}
    for post in scored_posts:
        cid = str(post.get('source_cid', '') or '').strip()
        if not cid:
            continue
        by_source.setdefault(cid, []).append(float(post.get('norm_score', 0)))

    stats = {}
    for cid, scores in by_source.items():
        stats[cid] = {
            'posts': len(scores),
            'median_score': round(statistics.median(scores), 4),
        }
    return stats


def decide_state(stat: dict, now: int, previous: dict | None = None) -> dict:
    """Состояние источника по статистике: white / neutral / stop."""
    previous = previous or {}
    # Стоп-кулдаун ещё не истёк — состояние не пересматриваем
    if previous.get('state') == 'stop' and now < int(previous.get('cooldown_until', 0)):
        return {**previous, **stat}

    state = 'neutral'
    cooldown_until = 0
    if int(stat.get('posts', 0)) >= MIN_POSTS_FOR_DECISION:
        median = float(stat.get('median_score', 0))
        if median >= WHITELIST_SCORE:
            state = 'white'
        elif median < STOPLIST_SCORE:
            state = 'stop'
            cooldown_until = now + STOPLIST_COOLDOWN_DAYS * 86400
    return {**stat, 'state': state, 'cooldown_until': cooldown_until, 'updated_at': now}


def update_source_states() -> dict:
    """Пересчитать состояния всех источников из трекера. Вызывается learning-циклом."""
    from services.tracker import get_scored_posts

    now = int(time.time())
    stats = build_source_stats(get_scored_posts())
    previous = load_states()

    states = {}
    changes = []
    for cid, stat in stats.items():
        new_state = decide_state(stat, now, previous.get(cid))
        states[cid] = new_state
        old = (previous.get(cid) or {}).get('state', 'neutral')
        if new_state['state'] != old:
            changes.append(f'{cid}: {old} → {new_state["state"]}')

    # Источники без свежих данных сохраняем как есть (не теряем стоп-кулдауны)
    for cid, prev in previous.items():
        states.setdefault(cid, prev)

    _save_states(states)
    if changes:
        app_state.add_log(f'[Источники] Смена статусов: {"; ".join(changes)}', 'info')
    return states


def is_source_blocked(community_id: str) -> bool:
    """True — источник в стоп-листе, его не стоит качать."""
    cid = str(community_id or '').strip().lstrip('-')
    states = load_states()
    entry = states.get(cid) or states.get(f'-{cid}') or {}
    if entry.get('state') != 'stop':
        return False
    cooldown_until = int(entry.get('cooldown_until', 0))
    return cooldown_until == 0 or time.time() < cooldown_until
