# -*- coding: utf-8 -*-

from workers.download import download_batch_size, download_scan_limit, select_photos_for_download


def test_download_batch_keeps_large_vk_scan_when_only_one_post_left():
    cfg = {"batch_size": 100}

    assert download_batch_size(remaining=1, dl_cfg=cfg) == 100


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
