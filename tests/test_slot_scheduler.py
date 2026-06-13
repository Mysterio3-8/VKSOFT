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
