# -*- coding: utf-8 -*-
from pathlib import Path

import pytest


def test_hash_video_frame_extracts_and_hashes(monkeypatch, tmp_path):
    from services import phash

    fake_frame = tmp_path / "frame.jpg"

    def fake_run(cmd, **kwargs):
        from PIL import Image
        Image.new("RGB", (64, 64), color=(120, 50, 200)).save(fake_frame)

        class Result:
            returncode = 0
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("services.phash._extract_frame_path", lambda video_path: fake_frame)

    h = phash.hash_video_frame(Path("dummy.mp4"))
    assert h is not None
    assert isinstance(h, str)
    assert len(h) > 0


def test_hash_video_frame_returns_none_on_ffmpeg_failure(monkeypatch, tmp_path):
    from services import phash

    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 1
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)

    h = phash.hash_video_frame(Path("dummy.mp4"))
    assert h is None


def test_is_duplicate_uses_precomputed_hash(monkeypatch, tmp_path):
    from services import phash

    monkeypatch.setattr("services.phash._cache_file", lambda: tmp_path / "phash_cache.json")
    phash.add_to_cache(Path("dummy.jpg"), "existing_key", precomputed_hash="0000000000000000")

    assert phash.is_duplicate(Path("dummy.mp4"), threshold=10, precomputed_hash="0000000000000000") is True
    assert phash.is_duplicate(Path("dummy.mp4"), threshold=0, precomputed_hash="ffffffffffffffff") is False


def test_add_to_cache_with_precomputed_hash_skips_image_open(monkeypatch, tmp_path):
    from services import phash

    monkeypatch.setattr("services.phash._cache_file", lambda: tmp_path / "phash_cache.json")
    phash.add_to_cache(Path("nonexistent.mp4"), "video_key", precomputed_hash="abc123")

    cache = phash._load()
    assert cache["video_key"] == "abc123"
