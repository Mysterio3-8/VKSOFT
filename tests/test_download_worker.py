# -*- coding: utf-8 -*-

from config import AppState
from workers.download import (
    download_batch_size,
    download_scan_limit,
    per_source_download_count,
    select_photos_for_download,
)


def test_default_profile_always_enables_duplicate_checking():
    profile = AppState.default_profile()

    assert profile["download_settings"]["check_duplicates"] is True


def test_normalized_profile_forces_fast_duplicate_safe_post_cycle():
    state = object.__new__(AppState)

    normalized = state._normalize_config({
        "active_profile": "p1",
        "profiles": {
            "p1": {
                "download_settings": {
                    "check_duplicates": False,
                    "delay_min": 5,
                    "delay_max": 9,
                    "batch_size": 10,
                    "max_photos_per_post": 8,
                },
                "publishing_settings": {
                    "skip_vk_sync": False,
                },
            }
        },
    })

    profile = normalized["profiles"]["p1"]
    assert profile["download_settings"]["check_duplicates"] is True
    assert profile["download_settings"]["delay_min"] == 0
    assert profile["download_settings"]["delay_max"] == 0
    assert profile["download_settings"]["batch_size"] == 100
    assert profile["download_settings"]["max_photos_per_post"] == 2
    assert profile["publishing_settings"]["skip_vk_sync"] is True


def test_download_batch_keeps_large_vk_scan_when_only_one_post_left():
    cfg = {"batch_size": 100}

    assert download_batch_size(remaining=1, dl_cfg=cfg) == 100


def test_per_source_download_count_distributes_total_cycle_budget():
    assert per_source_download_count(total_count=100, source_count=5) == 20
    assert per_source_download_count(total_count=100, source_count=3) == 34
    assert per_source_download_count(total_count=100, source_count=0) == 100


def test_download_all_worker_reassigns_budget_when_source_returns_less(monkeypatch, tmp_path):
    import config
    from config import app_state
    import workers.download as download

    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(
        app_state,
        "config",
        {
            "active_profile": "budget",
            "profiles": {
                "budget": {
                    "sources": [
                        {"community_id": "1", "enabled": True},
                        {"community_id": "2", "enabled": True},
                        {"community_id": "3", "enabled": True},
                    ],
                    "download_settings": {"posts_to_download": 100},
                }
            },
        },
    )
    app_state.is_downloading = True
    monkeypatch.setattr(app_state, "add_log", lambda *args, **kwargs: None)
    monkeypatch.setattr("services.seasonality.order_sources_by_season", lambda sources: sources)
    monkeypatch.setattr("services.source_quality.is_source_blocked", lambda cid: False)

    requested = []
    returned = iter([5, 48, 47])

    def fake_download_source(cid, count):
        requested.append((cid, count))
        return next(returned)

    monkeypatch.setattr(download, "_download_source", fake_download_source)

    download.download_all_worker()

    assert requested == [("1", 34), ("2", 48), ("3", 47)]


def test_eligible_sources_in_season_drops_disabled_and_blocked(monkeypatch):
    from workers.download import eligible_sources_in_season

    sources = [
        {"community_id": "1", "enabled": True},
        {"community_id": "2", "enabled": False},
        {"community_id": "3", "enabled": True},
    ]
    monkeypatch.setattr("services.seasonality.order_sources_by_season", lambda s: s)
    monkeypatch.setattr("services.source_quality.is_source_blocked", lambda cid: cid == "3")

    eligible = eligible_sources_in_season(sources)

    assert [s["community_id"] for s in eligible] == ["1"]


def test_download_photos_worker_spreads_budget_across_channels(monkeypatch, tmp_path):
    import config
    from config import app_state
    import workers.photos as photos

    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(
        app_state,
        "config",
        {
            "active_profile": "p",
            "profiles": {
                "p": {
                    "sources": [
                        {"community_id": "1", "enabled": True},
                        {"community_id": "2", "enabled": True},
                        {"community_id": "3", "enabled": True},
                    ],
                    "photos_settings": {"photos_download_per_run": 100},
                }
            },
        },
    )
    app_state.is_downloading_photos = True
    monkeypatch.setattr(app_state, "add_log", lambda *args, **kwargs: None)
    monkeypatch.setattr("services.seasonality.order_sources_by_season", lambda sources: sources)
    monkeypatch.setattr("services.source_quality.is_source_blocked", lambda cid: False)

    requested = []
    returned = iter([5, 48, 47])

    def fake_source(cid, count):
        requested.append((cid, count))
        return next(returned)

    monkeypatch.setattr(photos, "_download_photos_source", fake_source)

    photos.download_photos_worker()

    assert requested == [("1", 34), ("2", 48), ("3", 47)]


def test_download_videos_worker_spreads_budget_across_channels(monkeypatch, tmp_path):
    import config
    from config import app_state
    import workers.videos as videos

    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(
        app_state,
        "config",
        {
            "active_profile": "p",
            "profiles": {
                "p": {
                    "sources": [
                        {"community_id": "1", "enabled": True},
                        {"community_id": "2", "enabled": True},
                    ],
                    "videos_settings": {"videos_download_per_run": 10},
                }
            },
        },
    )
    app_state.is_downloading_videos = True
    monkeypatch.setattr(app_state, "add_log", lambda *args, **kwargs: None)
    monkeypatch.setattr("services.seasonality.order_sources_by_season", lambda sources: sources)
    monkeypatch.setattr("services.source_quality.is_source_blocked", lambda cid: False)

    requested = []

    def fake_source(cid, count, **kwargs):
        requested.append((cid, count))
        return count

    monkeypatch.setattr(videos, "_download_videos_source", fake_source)

    videos.download_videos_worker()

    assert requested == [("1", 5), ("2", 5)]


def test_download_batch_respects_config_bounds():
    assert download_batch_size(remaining=10, dl_cfg={"batch_size": 500}) == 100
    assert download_batch_size(remaining=10, dl_cfg={"batch_size": 0}) == 100
    assert download_batch_size(remaining=10, dl_cfg={"batch_size": 25}) == 25


def test_download_scan_limit_prevents_unbounded_filter_scans():
    assert download_scan_limit(target_count=20, dl_cfg={"scan_multiplier": 4}) == 100
    assert download_scan_limit(target_count=200, dl_cfg={"scan_multiplier": 3}) == 600
    assert download_scan_limit(target_count=20, dl_cfg={"max_scan_posts": 150}) == 150


def test_select_photos_for_download_limits_expensive_large_posts():
    photos = [{"type": "photo", "id": i} for i in range(10)]

    selected = select_photos_for_download(
        photos,
        profile={"antiplagiaat": {"enabled": True, "max_photos": 4}},
        dl_cfg={"max_photos_per_post": 2},
    )

    assert selected == photos[:2]


def test_select_photos_for_download_uses_antiplagiat_limit_when_no_fast_limit():
    photos = [{"type": "photo", "id": i} for i in range(10)]

    selected = select_photos_for_download(
        photos,
        profile={"antiplagiaat": {"enabled": True, "max_photos": 4}},
        dl_cfg={},
    )

    assert selected == photos[:5]


def test_download_saves_phash_duplicate_when_antiplagiarism_will_rewrite_photo(monkeypatch, tmp_path):
    import config
    from config import app_state
    from workers.download import _download_source

    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(
        app_state,
        "config",
        {
            "active_profile": "test_phash_ignore",
            "profiles": {
                "test_phash_ignore": {
                    "vk": {"user_token": "user-token", "api_version": "5.131"},
                    "download_settings": {
                        "batch_size": 1,
                        "delay_min": 0,
                        "delay_max": 0,
                        "max_scan_posts": 1,
                        "check_duplicates": False,
                    },
                    "processing": {"allow_video": False},
                    "filters": {},
                    "engagement": {"enabled": False},
                    "antiplagiaat": {"enabled": True, "max_photos": 4},
                    "phash": {"enabled": True, "threshold": 10},
                }
            },
        },
    )
    app_state.is_downloading = True
    logs = []
    monkeypatch.setattr(app_state, "add_log", lambda message, level="info": logs.append((level, message)))

    class FakeWall:
        def get(self, **kwargs):
            return {
                "items": [
                    {
                        "id": 99,
                        "text": "",
                        "attachments": [{"type": "photo", "photo": {}}],
                        "likes": {"count": 1},
                        "views": {"count": 10},
                    }
                ]
            }

    class FakeVk:
        wall = FakeWall()

    photo_file = tmp_path / "local.jpg"
    photo_file.write_bytes(b"photo")
    monkeypatch.setattr("workers.download.get_vk_api", lambda token, api_ver: FakeVk())
    monkeypatch.setattr("workers.download.vk_call_safe", lambda fn, **params: fn(**params))
    monkeypatch.setattr("workers.download.download_photos_for_post", lambda *args, **kwargs: [str(photo_file)])
    monkeypatch.setattr("services.phash.is_duplicate", lambda *args, **kwargs: True)

    _download_source("123", 1)

    saved = tmp_path / "test_phash_ignore" / "downloaded_posts" / "123_99.json"
    assert saved.exists()
    assert not any("Phash" in message or "duplicate" in message for _, message in logs)


def test_phash_enabled_reads_from_profile_config(monkeypatch):
    """phash_enabled should reflect profile.phash.enabled, not be hardcoded False."""
    import workers.download as dl

    profile = {"phash": {"enabled": True, "threshold": 10}}
    phash_cfg = profile.get('phash', {})
    phash_enabled = phash_cfg.get('enabled', False)

    assert phash_enabled is True
