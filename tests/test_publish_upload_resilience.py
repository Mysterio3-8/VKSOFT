# -*- coding: utf-8 -*-

from pathlib import Path

from vk.upload import upload_photo_from_file


class FakeUploadResponse:
    def __init__(self, payload=None, exc=None):
        self.payload = payload
        self.exc = exc
        self.status_code = 200
        self.text = "" if exc else "{}"

    def json(self):
        if self.exc:
            raise self.exc
        return self.payload


class FakePhotosApi:
    def getWallUploadServer(self, group_id):
        return {"upload_url": "https://upload.example.test"}

    def saveWallPhoto(self, group_id, photo, server, hash):
        return [{"owner_id": -group_id, "id": 123}]


class FakeVkUser:
    photos = FakePhotosApi()


def test_upload_photo_retries_empty_non_json_upload_response(monkeypatch, tmp_path):
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"fake-jpeg")
    calls = []
    responses = [
        FakeUploadResponse(exc=ValueError("empty response")),
        FakeUploadResponse({"photo": "[]", "server": 1, "hash": "abc"}),
    ]

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return responses.pop(0)

    monkeypatch.setattr("vk.upload.req_lib.post", fake_post)

    assert upload_photo_from_file(FakeVkUser(), 42, photo) == "photo-42_123"
    assert len(calls) == 2


def test_upload_local_photos_tries_fallback_when_selected_photo_fails(monkeypatch, tmp_path):
    from workers.publish import _upload_local_photos_with_fallback

    selected = tmp_path / "selected.jpg"
    fallback = tmp_path / "fallback.jpg"
    selected.write_bytes(b"bad")
    fallback.write_bytes(b"good")
    attempted = []

    def fake_upload(vk_user, group_id_num, path):
        attempted.append(Path(path).name)
        if Path(path).name == "fallback.jpg":
            return "photo-42_456"
        return None

    monkeypatch.setattr("workers.publish.upload_photo_from_file", fake_upload)

    attachments = _upload_local_photos_with_fallback(
        vk_user=object(),
        gid_num=42,
        selected_photos=[str(selected)],
        all_local_photos=[str(selected), str(fallback)],
        log=lambda message, level="info": None,
    )

    assert attachments == ["photo-42_456"]
    assert attempted == ["selected.jpg", "fallback.jpg"]

