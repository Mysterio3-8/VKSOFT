# -*- coding: utf-8 -*-
"""Тренд охвата по типам медиа + рекомендация объёма публикаций."""

import time


def _post(views: int, age_days: float, media_type: str = 'photo') -> dict:
    return {
        'checked': True,
        'missing': False,
        'views': views,
        'published_at': int(time.time()) - int(age_days * 86400),
        'media_type': media_type,
    }


def test_reach_trend_filters_by_media_type(monkeypatch):
    from services import tracker

    data = [_post(50, 2, 'clip'), _post(999, 2, 'photo')]
    monkeypatch.setattr(tracker, '_load', lambda: data)

    clip = tracker.get_reach_trend(media_type='clip')
    assert clip['media_type'] == 'clip'
    assert clip['recent_avg_views'] == 50


def test_reach_trend_by_type_structure_and_reduce_signal(monkeypatch):
    from services import tracker

    # Свежее окно (2-4 дня) хуже предыдущего (9-11 дней) → охват падает.
    data = [
        _post(100, 2, 'clip'), _post(100, 3, 'photo'), _post(100, 4, 'video'),
        _post(200, 9, 'clip'), _post(200, 10, 'photo'), _post(200, 11, 'video'),
    ]
    monkeypatch.setattr(tracker, '_load', lambda: data)

    out = tracker.get_reach_trend_by_type()
    assert set(out['by_type']) == set(tracker.REACH_MEDIA_TYPES)
    assert out['overall']['signal'] == 'down'
    assert out['recommendation'] == 'reduce'
    assert out['recommendation_text']


def test_volume_recommendation_codes():
    from services.tracker import _volume_recommendation

    assert _volume_recommendation({'signal': 'down', 'delta_pct': -40.0})[0] == 'reduce'
    assert _volume_recommendation({'signal': 'ok', 'delta_pct': 20.0})[0] == 'increase'
    assert _volume_recommendation({'signal': 'ok', 'delta_pct': 2.0})[0] == 'hold'
    assert _volume_recommendation({'signal': 'insufficient'})[0] == 'insufficient'
