# -*- coding: utf-8 -*-
import json
import time

import pytest


@pytest.fixture
def scheduler_paths(tmp_path, monkeypatch):
    slots_file = tmp_path / "scheduled_slots.json"
    lock_file = tmp_path / "scheduled_slots.lock"
    monkeypatch.setattr("services.slot_scheduler._slots_file", lambda: slots_file)
    monkeypatch.setattr("services.slot_scheduler._lock_file", lambda: lock_file)
    # Изолируем от реального storage/{profile_id}/last_scheduled.txt активного
    # профиля — иначе base для candidate берёт продовый timestamp из будущего.
    monkeypatch.setattr("services.storage.read_last_scheduled", lambda: None)
    monkeypatch.setattr("services.storage.write_last_scheduled", lambda ts: None)
    return slots_file, lock_file


def test_reserve_slot_returns_future_timestamp(scheduler_paths):
    from services.slot_scheduler import reserve_slot

    now = int(time.time())
    ts = reserve_slot(media_type="photos", delay_min=60, delay_max=120)

    assert ts > now
    assert ts <= now + 120 + 5  # small buffer for test runtime


def test_reserve_slot_persists_to_file(scheduler_paths):
    from services.slot_scheduler import reserve_slot

    slots_file, _ = scheduler_paths
    reserve_slot(media_type="photos", delay_min=60, delay_max=60)

    data = json.loads(slots_file.read_text(encoding="utf-8"))
    assert len(data["slots"]) == 1
    assert data["slots"][0]["media_type"] == "photos"


def test_reserve_slot_avoids_collision_with_other_media_type(scheduler_paths, monkeypatch):
    from services.slot_scheduler import reserve_slot
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 1800)

    ts1 = reserve_slot(media_type="videos", delay_min=10, delay_max=10, profile={})
    ts2 = reserve_slot(media_type="clips", delay_min=10, delay_max=10, profile={})

    assert abs(ts2 - ts1) >= 1800


def test_reserve_slot_respects_daily_limit(scheduler_paths, monkeypatch):
    from services.slot_scheduler import reserve_slot
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 60)

    profile = {"videos_settings": {"daily_limit": 1}}

    ts1 = reserve_slot(media_type="videos", delay_min=10, delay_max=10, profile=profile)
    ts2 = reserve_slot(media_type="videos", delay_min=10, delay_max=10, profile=profile)

    from datetime import datetime
    day1 = datetime.fromtimestamp(ts1).date()
    day2 = datetime.fromtimestamp(ts2).date()
    assert day2 > day1


def test_reserve_slot_does_not_limit_other_media_types(scheduler_paths, monkeypatch):
    from services.slot_scheduler import reserve_slot
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 60)

    profile = {"videos_settings": {"daily_limit": 1}}

    ts_video = reserve_slot(media_type="videos", delay_min=10, delay_max=10, profile=profile)
    ts_clip = reserve_slot(media_type="clips", delay_min=10, delay_max=10, profile=profile)

    from datetime import datetime
    assert datetime.fromtimestamp(ts_clip).date() == datetime.fromtimestamp(ts_video).date()


def test_app_state_has_scheduled_slots_file(monkeypatch, tmp_path):
    from config import app_state, STORAGE_DIR

    expected = STORAGE_DIR / app_state.active_profile_id / 'scheduled_slots.json'
    assert app_state.scheduled_slots_file == expected


def test_app_state_has_publish_log_file():
    from config import app_state, STORAGE_DIR

    expected = STORAGE_DIR / app_state.active_profile_id / 'publish_log.jsonl'
    assert app_state.publish_log_file == expected


def test_record_slot_appears_in_future_reservations(scheduler_paths, monkeypatch):
    from services.slot_scheduler import record_slot, reserve_slot
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 1800)

    fixed_ts = int(time.time()) + 100
    record_slot("posts", fixed_ts)

    ts2 = reserve_slot(media_type="videos", delay_min=10, delay_max=10, profile={})
    assert abs(ts2 - fixed_ts) >= 1800


def test_daily_limits_are_configurable_per_profile():
    """videos_settings.daily_limit / clips_settings.daily_limit задают лимит,
    с дефолтами 1 и 2, если в профиле не указано."""
    from services.slot_scheduler import _daily_limit

    profile_with_custom_limits = {
        "videos_settings": {"daily_limit": 5},
        "clips_settings": {"daily_limit": 10},
    }

    assert _daily_limit("videos", profile_with_custom_limits) == 5
    assert _daily_limit("clips", profile_with_custom_limits) == 10
    assert _daily_limit("videos", {}) == 1
    assert _daily_limit("clips", {}) == 2


def test_reserve_slot_caps_videos_to_one_per_day(scheduler_paths, monkeypatch):
    from services.slot_scheduler import reserve_slot
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 60)

    ts1 = reserve_slot(media_type="videos", delay_min=10, delay_max=10, profile={})
    ts2 = reserve_slot(media_type="videos", delay_min=10, delay_max=10, profile={})

    from datetime import datetime
    assert datetime.fromtimestamp(ts1).date() != datetime.fromtimestamp(ts2).date()


def test_apply_publish_window_disabled_by_default():
    from datetime import datetime

    from services.slot_scheduler import _apply_publish_window

    night = int(datetime.now().replace(hour=3, minute=0, second=0, microsecond=0).timestamp())
    assert _apply_publish_window(night, {}) == night


def test_apply_publish_window_pushes_night_into_daytime():
    from datetime import datetime

    from services.slot_scheduler import _apply_publish_window

    profile = {'publishing_settings': {
        'apply_window_to_media': True,
        'publish_hours_enabled': True,
        'publish_hours_start': 8,
        'publish_hours_end': 22,
    }}
    night = int(datetime.now().replace(hour=3, minute=0, second=0, microsecond=0).timestamp())

    out = _apply_publish_window(night, profile)

    assert 8 <= datetime.fromtimestamp(out).hour < 22


def test_reserve_slot_global_cap_across_all_types(scheduler_paths, monkeypatch):
    from datetime import datetime

    from services.slot_scheduler import reserve_slot
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 60)

    profile = {"publishing_settings": {"max_total_per_day": 2}}

    ts1 = reserve_slot(media_type="photos", delay_min=10, delay_max=10, profile=profile)
    ts2 = reserve_slot(media_type="clips", delay_min=10, delay_max=10, profile=profile)
    ts3 = reserve_slot(media_type="photos", delay_min=10, delay_max=10, profile=profile)

    d1 = datetime.fromtimestamp(ts1).date()
    d2 = datetime.fromtimestamp(ts2).date()
    d3 = datetime.fromtimestamp(ts3).date()
    assert d1 == d2
    assert d3 != d1


def test_daily_limit_photos_default_and_custom():
    """У фото свой дневной лимит (дефолт 1), отдельный от постов."""
    from services.slot_scheduler import _daily_limit

    assert _daily_limit("photos", {}) == 1
    assert _daily_limit("photos", {"photos_settings": {"daily_limit": 3}}) == 3


def test_daily_limit_posts_independent_of_photos():
    from services.slot_scheduler import _daily_limit

    assert _daily_limit("posts", {}) is None
    assert _daily_limit("posts", {"publishing_settings": {"max_posts_per_day": 3}}) == 3


def test_reserve_slot_caps_photos_to_one_per_day(scheduler_paths, monkeypatch):
    from services.slot_scheduler import reserve_slot
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 60)

    ts1 = reserve_slot(media_type="photos", delay_min=10, delay_max=10, profile={})
    ts2 = reserve_slot(media_type="photos", delay_min=10, delay_max=10, profile={})

    from datetime import datetime
    assert datetime.fromtimestamp(ts1).date() != datetime.fromtimestamp(ts2).date()


def test_reserve_slot_caps_clips_to_two_per_day(scheduler_paths, monkeypatch):
    from services.slot_scheduler import reserve_slot
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 60)

    ts1 = reserve_slot(media_type="clips", delay_min=10, delay_max=10, profile={})
    ts2 = reserve_slot(media_type="clips", delay_min=10, delay_max=10, profile={})
    ts3 = reserve_slot(media_type="clips", delay_min=10, delay_max=10, profile={})

    from datetime import datetime
    day1 = datetime.fromtimestamp(ts1).date()
    day2 = datetime.fromtimestamp(ts2).date()
    day3 = datetime.fromtimestamp(ts3).date()
    assert day1 == day2
    assert day3 != day1
