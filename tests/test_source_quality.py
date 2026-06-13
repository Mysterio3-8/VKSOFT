# -*- coding: utf-8 -*-
"""Снимки метрик и белые/стоп-листы источников."""

from services.source_quality import (
    MIN_POSTS_FOR_DECISION,
    STOPLIST_COOLDOWN_DAYS,
    build_source_stats,
    decide_state,
)
from services.tracker import SNAPSHOT_HOURS, _due_snapshot_hour

DAY = 86400


# ── tracker: расписание снимков ───────────────────────────────────

def test_due_snapshot_picks_latest_missing_hour():
    now = 100 * DAY
    post = {'published_at': now - 7 * 3600, 'snapshots': {'1': {}}}
    # Возраст 7ч: снимок 1ч уже есть, пора снять 6ч
    assert _due_snapshot_hour(post, now) == 6

    post['snapshots']['6'] = {}
    assert _due_snapshot_hour(post, now) is None  # 24ч ещё не наступило


def test_due_snapshot_skips_future_and_missing_posts():
    now = 100 * DAY
    assert _due_snapshot_hour({'published_at': now + 3600}, now) is None  # отложен
    assert _due_snapshot_hour({'published_at': now - DAY, 'missing': True}, now) is None


def test_due_snapshot_catches_up_after_downtime():
    # Бот лежал 4 дня: снимаем сразу самый поздний снимок (72ч), не фальсифицируя ранние
    now = 100 * DAY
    post = {'published_at': now - 4 * DAY, 'snapshots': {}}
    assert _due_snapshot_hour(post, now) == max(SNAPSHOT_HOURS)


# ── source quality ────────────────────────────────────────────────

def _scored(cid: str, score: float, n: int) -> list:
    return [{'source_cid': cid, 'norm_score': score} for _ in range(n)]


def test_build_source_stats_median_per_source():
    posts = _scored('111', 1.5, 3) + _scored('222', 0.5, 2)
    posts.append({'source_cid': '', 'norm_score': 9.9})  # без источника — мимо

    stats = build_source_stats(posts)

    assert stats['111'] == {'posts': 3, 'median_score': 1.5}
    assert stats['222'] == {'posts': 2, 'median_score': 0.5}
    assert len(stats) == 2


def test_decide_state_whitelists_and_stops():
    now = 1000

    white = decide_state({'posts': MIN_POSTS_FOR_DECISION, 'median_score': 1.3}, now)
    stop = decide_state({'posts': MIN_POSTS_FOR_DECISION, 'median_score': 0.5}, now)
    neutral = decide_state({'posts': MIN_POSTS_FOR_DECISION, 'median_score': 1.0}, now)
    too_few = decide_state({'posts': MIN_POSTS_FOR_DECISION - 1, 'median_score': 0.1}, now)

    assert white['state'] == 'white'
    assert stop['state'] == 'stop'
    assert stop['cooldown_until'] == now + STOPLIST_COOLDOWN_DAYS * DAY
    assert neutral['state'] == 'neutral'
    assert too_few['state'] == 'neutral'  # мало данных — не судим


def test_decide_state_keeps_stop_until_cooldown_expires():
    now = 1000
    previous = {'state': 'stop', 'cooldown_until': now + DAY}

    # Даже если статистика выправилась, до конца кулдауна источник остаётся в стопе
    decided = decide_state({'posts': 20, 'median_score': 2.0}, now, previous)

    assert decided['state'] == 'stop'

    # После кулдауна — пересматриваем по фактическим числам
    later = now + 2 * DAY
    decided = decide_state({'posts': 20, 'median_score': 2.0}, later, previous)
    assert decided['state'] == 'white'
