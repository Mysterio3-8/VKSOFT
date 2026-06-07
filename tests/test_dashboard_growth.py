# -*- coding: utf-8 -*-

from api.dashboard import build_growth_dashboard_payload


def test_growth_dashboard_payload_combines_channel_stats_and_autopilot():
    payload = build_growth_dashboard_payload(
        base={"pending": 3, "published_today": 4, "errors_today": 0},
        tracker={
            "checked": 5,
            "avg_views": 1200,
            "avg_likes": 20,
            "hour_heatmap": [
                {"hour": 2, "posts": 2, "avg_score": 900},
                {"hour": 18, "posts": 3, "avg_score": 700},
                {"hour": 9, "posts": 0, "avg_score": 0},
            ],
        },
        subscribers={"members": 300, "diff_today": 7},
        settings={"posts_per_day": 12},
        report={"summary": {"candidate_count": 10}},
        cycle={"running": False, "phase": "done"},
    )

    assert payload["status"] == "ok"
    assert payload["dashboard"]["pending"] == 3
    assert payload["subscribers"]["diff_today"] == 7
    assert payload["growth_autopilot"]["settings"]["posts_per_day"] == 12
    assert payload["growth_autopilot"]["hot_hours"] == [2, 18]
