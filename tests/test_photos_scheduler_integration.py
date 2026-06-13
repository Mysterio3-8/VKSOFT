# -*- coding: utf-8 -*-
import json
import time

import pytest


def test_get_next_ts_uses_slot_scheduler(monkeypatch, tmp_path):
    from config import app_state
    from workers.photos import _get_next_ts

    slots_file = tmp_path / "scheduled_slots.json"
    lock_file = tmp_path / "scheduled_slots.lock"
    monkeypatch.setattr(type(app_state), "scheduled_slots_file", property(lambda self: slots_file))
    monkeypatch.setattr("services.slot_scheduler._lock_file", lambda: lock_file)
    monkeypatch.setattr("services.storage.read_last_scheduled", lambda: None)
    monkeypatch.setattr("services.storage.write_last_scheduled", lambda ts: None)
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 60)

    now = int(time.time())
    ts = _get_next_ts(60, 120)

    assert ts > now
    data = json.loads(slots_file.read_text(encoding="utf-8"))
    assert data["slots"][0]["media_type"] == "photos"
