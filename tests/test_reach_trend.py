# -*- coding: utf-8 -*-
"""Тренд охвата (ранний сигнал теневого бана) в services.tracker."""

import time


def test_get_reach_trend_flags_drop(monkeypatch):
    import services.tracker as tr

    now = int(time.time())
    posts = (
        [{'published_at': now - 86400, 'views': 100} for _ in range(4)]
        + [{'published_at': now - 10 * 86400, 'views': 400} for _ in range(4)]
    )
    monkeypatch.setattr(tr, '_load', lambda: posts)
    monkeypatch.setattr(tr, '_eligible', lambda p: True)

    out = tr.get_reach_trend(days=7)

    assert out['signal'] == 'down'
    assert out['recent_avg_views'] == 100
    assert out['prev_avg_views'] == 400
    assert out['delta_pct'] == -75.0


def test_get_reach_trend_ok_when_stable(monkeypatch):
    import services.tracker as tr

    now = int(time.time())
    posts = (
        [{'published_at': now - 86400, 'views': 410} for _ in range(4)]
        + [{'published_at': now - 10 * 86400, 'views': 400} for _ in range(4)]
    )
    monkeypatch.setattr(tr, '_load', lambda: posts)
    monkeypatch.setattr(tr, '_eligible', lambda p: True)

    assert tr.get_reach_trend(days=7)['signal'] == 'ok'


def test_get_reach_trend_insufficient_data(monkeypatch):
    import services.tracker as tr

    now = int(time.time())
    monkeypatch.setattr(tr, '_load', lambda: [{'published_at': now - 86400, 'views': 100}])
    monkeypatch.setattr(tr, '_eligible', lambda p: True)

    assert tr.get_reach_trend()['signal'] == 'insufficient'
