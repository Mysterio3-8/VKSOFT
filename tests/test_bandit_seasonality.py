# -*- coding: utf-8 -*-
"""UCB-бандит и сезонные веса источников."""

from services.bandit import stats_to_arms, ucb_choose
from services.seasonality import detect_season, order_sources_by_season, source_season_weight
from services.tracker import build_overlay_stats


# ── bandit ────────────────────────────────────────────────────────

def test_ucb_explores_untried_arm_first():
    arms = [
        {'name': 'question', 'mean': 0.5, 'trials': 50},
        {'name': 'rating', 'mean': 0.0, 'trials': 0},
    ]
    assert ucb_choose(arms) == 'rating'


def test_ucb_exploits_best_mean_with_equal_trials():
    arms = [
        {'name': 'question', 'mean': 0.10, 'trials': 100},
        {'name': 'cta', 'mean': 0.30, 'trials': 100},
        {'name': 'mission', 'mean': 0.05, 'trials': 100},
    ]
    assert ucb_choose(arms) == 'cta'


def test_ucb_exploration_bonus_lifts_undersampled_arm():
    # Почти равный mean, но у одной руки в 100 раз меньше попыток —
    # бонус исследования должен её поднять.
    arms = [
        {'name': 'leader', 'mean': 0.30, 'trials': 1000},
        {'name': 'undersampled', 'mean': 0.29, 'trials': 10},
    ]
    assert ucb_choose(arms) == 'undersampled'


def test_stats_to_arms_includes_untried_names():
    stats = {'question': {'posts': 5, 'avg_er': 0.1}}
    arms = stats_to_arms(stats, names=['question', 'rating'])

    assert arms == [
        {'name': 'question', 'mean': 0.1, 'trials': 5},
        {'name': 'rating', 'mean': 0.0, 'trials': 0},
    ]


def test_ucb_empty_arms_returns_none():
    assert ucb_choose([]) is None


# ── seasonality ───────────────────────────────────────────────────

def test_detect_season_maps_months():
    assert detect_season(7) == 'summer'
    assert detect_season(1) == 'winter'
    assert detect_season(10) == 'autumn'
    assert detect_season(4) == 'spring'


def test_source_season_weight_uses_report_table():
    sea = {'bucket': 'sea'}
    snow = {'bucket': 'snow'}
    unmarked = {'name': 'без метки'}

    assert source_season_weight(sea, 'summer') == 1.30
    assert source_season_weight(snow, 'summer') == 0.70
    assert source_season_weight(snow, 'winter') == 1.35
    assert source_season_weight(unmarked, 'summer') == 1.0
    # Синонимы бакетов
    assert source_season_weight({'bucket': 'ocean'}, 'summer') == 1.30


def test_order_sources_by_season_prioritizes_seasonal():
    sources = [
        {'name': 'снег', 'bucket': 'snow'},
        {'name': 'море', 'bucket': 'sea'},
        {'name': 'обычный'},
    ]
    ordered = order_sources_by_season(sources, season='summer')
    assert [s['name'] for s in ordered] == ['море', 'обычный', 'снег']

    ordered_winter = order_sources_by_season(sources, season='winter')
    assert ordered_winter[0]['name'] == 'снег'


# ── overlay stats ─────────────────────────────────────────────────

def test_build_overlay_stats_aggregates_by_family():
    data = [
        {'overlay_family': 'rating', 'checked': True, 'views': 100, 'likes': 10,
         'comments': 0, 'reposts': 0},
        {'overlay_family': 'rating', 'checked': True, 'views': 100, 'likes': 30,
         'comments': 0, 'reposts': 0},
        {'overlay_family': 'escape', 'checked': True, 'views': 100, 'likes': 5,
         'comments': 0, 'reposts': 0},
        {'overlay_family': 'escape', 'checked': False, 'views': 100, 'likes': 99},  # не проверен
        {'checked': True, 'views': 100, 'likes': 50},                               # без оверлея
    ]

    stats = build_overlay_stats(data)

    assert stats['rating']['posts'] == 2
    assert stats['rating']['avg_er'] == 0.2
    assert stats['escape']['posts'] == 1
