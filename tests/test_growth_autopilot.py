# -*- coding: utf-8 -*-

from datetime import datetime

from services.growth_autopilot import (
    DEFAULT_GROWTH_SETTINGS,
    build_readonly_report,
    build_algorithmic_recommendations,
    build_cycle_patch,
    build_learned_24h_schedule,
    build_schedule_preview,
    distribute_download_count,
    filter_global_duplicates,
    load_used_posts,
    mark_used_post,
    score_candidate,
)
from services.tracker import build_hour_heatmap


def test_default_growth_settings_keep_24_as_preset_not_constant():
    assert DEFAULT_GROWTH_SETTINGS["preset"] == "custom"
    assert DEFAULT_GROWTH_SETTINGS["posts_per_day_min"] == 12
    assert DEFAULT_GROWTH_SETTINGS["posts_per_day_max"] == 24
    assert 24 in DEFAULT_GROWTH_SETTINGS["preset_values"].values()


def test_score_candidate_rewards_viral_signals_and_explains_reasons():
    strong = {
        "id": 10,
        "owner_id": -123,
        "date": 1893456000,
        "text": "Useful viral text",
        "likes": {"count": 200},
        "reposts": {"count": 30},
        "comments": {"count": 15},
        "views": {"count": 5000},
        "attachments": [{"type": "photo"}],
    }
    weak = {
        "id": 11,
        "owner_id": -123,
        "date": 1893456000,
        "text": "x",
        "likes": {"count": 1},
        "reposts": {"count": 0},
        "comments": {"count": 0},
        "views": {"count": 100},
        "attachments": [],
    }

    strong_score = score_candidate(strong, source_id="123")
    weak_score = score_candidate(weak, source_id="123")

    assert strong_score["viral_score"] > weak_score["viral_score"]
    assert strong_score["source_id"] == "123"
    assert strong_score["post_id"] == 10
    assert strong_score["reasons"]


def test_build_schedule_preview_uses_bounds_and_randomized_intervals():
    candidates = [
        {"file": f"post_{i}.json", "viral_score": 80 - i, "post_id": i}
        for i in range(10)
    ]
    settings = {
        "posts_per_day_min": 3,
        "posts_per_day_max": 5,
        "allowed_hours_start": 8,
        "allowed_hours_end": 22,
        "interval_jitter_min": 15,
        "queue_days": 1,
    }

    schedule = build_schedule_preview(candidates, settings, start_ts=1893456000)

    assert 3 <= len(schedule) <= 5
    assert all(item["file"].endswith(".json") for item in schedule)
    assert all("publish_at" in item for item in schedule)


def test_global_dedup_filters_used_post(tmp_path):
    used_file = tmp_path / "used.json"
    mark_used_post({"dedup_key": "1_10", "source_id": "1", "post_id": 10}, used_file=used_file, profile_id="p1")
    candidates = [
        {"dedup_key": "1_10", "viral_score": 90},
        {"dedup_key": "1_11", "viral_score": 80},
    ]

    filtered = filter_global_duplicates(candidates, used_file=used_file)

    assert [item["dedup_key"] for item in filtered] == ["1_11"]
    assert "1_10" in load_used_posts(used_file)


def test_build_readonly_report_scores_local_queue(tmp_path):
    posts_dir = tmp_path / "posts"
    posts_dir.mkdir()
    (posts_dir / "123_10.json").write_text(
        '{"id": 10, "owner_id": -123, "text": "Nice post", "likes": {"count": 20}, "views": {"count": 500}, "attachments": [{"type": "photo"}]}',
        encoding="utf-8",
    )

    report = build_readonly_report(
        posts_dir=posts_dir,
        settings={"posts_per_day_min": 1, "posts_per_day_max": 1, "min_viral_score": 0},
        save=False,
    )

    assert report["status"] == "ok"
    assert report["summary"]["candidate_count"] == 1
    assert report["top_candidates"][0]["post_id"] == 10
    assert len(report["schedule_preview"]) == 1


def test_growth_cycle_patch_uses_fast_download_and_publish_defaults():
    patch = build_cycle_patch({
        "horizon_days": 1,
        "posts_per_day": 10,
        "allowed_hours_start": 8,
        "allowed_hours_end": 22,
        "download_multiplier": 2,
    })

    assert patch["download_settings"]["posts_to_download"] == 20
    assert patch["download_settings"]["batch_size"] == 100
    assert patch["download_settings"]["delay_min"] == 0
    assert patch["download_settings"]["delay_max"] == 0
    assert patch["download_settings"]["max_scan_posts"] >= 100
    assert patch["download_settings"]["max_photos_per_post"] == 2
    assert patch["antiplagiaat"]["max_photos"] == 2
    assert patch["polls"]["enabled"] is False
    assert patch["publishing_settings"]["skip_vk_sync"] is True
    assert patch["peak_hours"]["enabled"] is False
    assert patch["publishing_settings"]["publish_delay_max"] <= 2 * 60 * 60


def test_distribute_download_count_keeps_cycle_budget_across_sources():
    assert distribute_download_count(168, 2) == 84
    assert distribute_download_count(10, 3) == 4
    assert distribute_download_count(10, 0) == 10


def test_algorithmic_recommendations_do_not_reenable_peak_hour_limiter(monkeypatch):
    monkeypatch.setattr(
        "services.tracker.get_summary",
        lambda: {
            "checked": 10,
            "avg_views": 100,
            "avg_likes": 20,
            "recommended_hours": [8, 10, 13, 17],
        },
    )

    result = build_algorithmic_recommendations()

    assert result["recommendation"]["patch"]["peak_hours"]["enabled"] is False
    assert result["recommendation"]["patch"]["peak_hours"]["hours"] == [8, 10, 13, 17]


def test_hour_heatmap_can_learn_night_and_far_timezone_slots():
    base = int(datetime(2030, 1, 1, 0, 0, 0).timestamp())
    data = [
        {"checked": True, "published_at": base + 2 * 3600, "views": 5000, "likes": 90, "reposts": 12},
        {"checked": True, "published_at": base + 2 * 3600 + 600, "views": 4200, "likes": 70, "reposts": 8},
        {"checked": True, "published_at": base + 15 * 3600, "views": 300, "likes": 4, "reposts": 0},
        {"checked": True, "published_at": base + 20 * 3600, "views": 2500, "likes": 30, "reposts": 5},
    ]

    heatmap = build_hour_heatmap(data)

    assert heatmap[2]["posts"] == 2
    assert heatmap[2]["avg_score"] > heatmap[15]["avg_score"]
    assert [item["hour"] for item in sorted(heatmap, key=lambda x: x["avg_score"], reverse=True)[:2]] == [2, 20]


def test_learned_24h_schedule_uses_best_hours_and_keeps_exploration():
    heatmap = [
        {"hour": hour, "posts": 5, "avg_score": 10}
        for hour in range(24)
    ]
    heatmap[2]["avg_score"] = 1000
    heatmap[20]["avg_score"] = 700

    schedule = build_learned_24h_schedule(
        count=12,
        start_ts=1893456000,
        heatmap=heatmap,
        horizon_days=1,
        exploitation_percent=75,
    )
    hours = [item.hour for item in schedule]

    assert 2 in hours
    assert 20 in hours
    assert len(set(hours)) > 2
    assert len(schedule) == 12
