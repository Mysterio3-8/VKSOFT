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
