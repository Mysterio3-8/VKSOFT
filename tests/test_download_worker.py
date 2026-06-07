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
