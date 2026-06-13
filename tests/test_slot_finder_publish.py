# -*- coding: utf-8 -*-

import json


class FakeWall:
    def __init__(self):
        self.posts = []

    def post(self, **params):
        self.posts.append(params)
        return {"post_id": 777}


class FakeVkGroup:
    def __init__(self):
        self.wall = FakeWall()


def test_fill_slots_applies_antiplagiarism_before_posting(monkeypatch, tmp_path):
    from services.slot_finder import fill_slots_with_queue

    photos_dir = tmp_path / "photos" / "source_1"
    posts_dir = tmp_path / "downloaded_posts"
    posts_dir.mkdir()
    photos_dir.mkdir(parents=True)
    first = photos_dir / "photo_0.jpg"
    second = photos_dir / "photo_1.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    (posts_dir / "source_1.json").write_text(
        json.dumps(
            {
                "id": 1,
                "owner_id": -123,
                "text": "ORIGINAL SOURCE TEXT",
                "_local_photos": [str(first), str(second)],
            }
        ),
        encoding="utf-8",
    )

    transformed = []
    uploaded = []

    def fake_transform(paths, profile):
        transformed.extend(paths)
        return len(paths)

    def fake_upload(vk_user, group_id_num, path):
        uploaded.append(path.name)
        return f"photo-{group_id_num}_{path.stem}"

    monkeypatch.setattr("services.media_pipeline.process_photos", fake_transform)
    monkeypatch.setattr("vk.upload.upload_photo_from_file", fake_upload)
    monkeypatch.setattr("workers.publish.upload_photo_from_file", fake_upload)
    monkeypatch.setattr("vk.api.vk_call_safe", lambda fn, **params: fn(**params))

    vk_group = FakeVkGroup()
    result = fill_slots_with_queue(
        slots=[{"ts": 1893456000, "display": "01.01 10:00"}],
        posts_dir=posts_dir,
        vk_user=object(),
        vk_group=vk_group,
        group_id="42",
        profile={
            "processing": {"add_hashtags": False, "hashtags": []},
            "publishing_settings": {"add_hashtags": False, "hashtags": []},
            "antiplagiaat": {
                "enabled": True,
                "clear_text": True,
                "max_photos": 1,
                "remove_photo": "first",
                "transforms": {"crop": True, "color_shift": True, "mirror": False, "strip_metadata": True},
            },
            "watermark": {"enabled": False},
        },
        add_log=lambda message, level="info": None,
    )

    assert result == {"filled": 1, "failed": 0}
    assert "ORIGINAL SOURCE TEXT" not in vk_group.wall.posts[0]["message"]
    assert transformed == [str(second)]
    assert uploaded == ["photo_1.jpg"]
    assert vk_group.wall.posts[0]["attachments"] == "photo-42_photo_1"
