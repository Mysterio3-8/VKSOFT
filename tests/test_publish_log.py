# -*- coding: utf-8 -*-
import gzip
import json
import time


def test_log_publish_event_appends_jsonl(monkeypatch, tmp_path):
    from config import app_state
    from services import publish_log

    log_file = tmp_path / "publish_log.jsonl"
    monkeypatch.setattr(type(app_state), "publish_log_file", property(lambda self: log_file))

    publish_log.log_publish_event(
        media_type="photos",
        status="success",
        post_id=12345,
        publish_date=int(time.time()) + 60,
        source_id="999",
        extra={"duplicate": False},
    )

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["media_type"] == "photos"
    assert entry["status"] == "success"
    assert entry["post_id"] == 12345
    assert entry["extra"]["duplicate"] is False


def test_read_recent_events_returns_latest_first(monkeypatch, tmp_path):
    from config import app_state
    from services import publish_log

    log_file = tmp_path / "publish_log.jsonl"
    monkeypatch.setattr(type(app_state), "publish_log_file", property(lambda self: log_file))

    for i in range(3):
        publish_log.log_publish_event(media_type="posts", status="success", post_id=i, publish_date=0)

    events = publish_log.read_recent_events(limit=2)
    assert len(events) == 2
    assert events[0]["post_id"] == 2
    assert events[1]["post_id"] == 1


def test_rotate_old_logs_compresses_yesterdays_file(monkeypatch, tmp_path):
    from config import app_state
    from services import publish_log

    log_dir = tmp_path
    log_file = log_dir / "publish_log.jsonl"
    monkeypatch.setattr(type(app_state), "publish_log_file", property(lambda self: log_file))

    # Simulate an old log file with yesterday's mtime
    log_file.write_text('{"post_id": 1}\n', encoding="utf-8")
    yesterday = time.time() - 90000
    import os
    os.utime(log_file, (yesterday, yesterday))

    publish_log.rotate_old_logs()

    gz_files = list(log_dir.glob("publish_log-*.jsonl.gz"))
    assert len(gz_files) == 1
    with gzip.open(gz_files[0], "rt", encoding="utf-8") as f:
        assert '"post_id": 1' in f.read()
    assert not log_file.exists()
