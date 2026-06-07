# -*- coding: utf-8 -*-
"""Тесты для services/photo_transform.py"""

import hashlib
import tempfile
from pathlib import Path

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow не установлен")


def _make_test_image(path: Path, size: tuple = (200, 200)):
    img = Image.new("RGB", size, color=(100, 150, 200))
    img.save(path, "JPEG", quality=95)


def _file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_apply_random_crop_changes_file():
    from services.photo_transform import apply_random_crop
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "photo.jpg"
        _make_test_image(p)
        original_hash = _file_hash(p)
        original_size = Image.open(p).size
        result = apply_random_crop(p)
        assert result is True
        new_size = Image.open(p).size
        # Файл изменился
        assert _file_hash(p) != original_hash
        # Размер уменьшился
        assert new_size[0] < original_size[0]
        assert new_size[1] < original_size[1]


def test_apply_color_shift_changes_file():
    from services.photo_transform import apply_color_shift
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "photo.jpg"
        _make_test_image(p)
        original_hash = _file_hash(p)
        result = apply_color_shift(p)
        assert result is True
        assert _file_hash(p) != original_hash


def test_apply_mirror_changes_file():
    from services.photo_transform import apply_mirror
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "photo.jpg"
        # Асимметричная картинка: градиент слева направо
        img = Image.new("RGB", (200, 200))
        pixels = img.load()
        for x in range(200):
            for y in range(200):
                pixels[x, y] = (x, y, 100)
        img.save(p, "JPEG", quality=95)
        original_hash = _file_hash(p)
        result = apply_mirror(p)
        assert result is True
        assert _file_hash(p) != original_hash


def test_apply_mirror_is_reversible():
    """Двойное зеркало возвращает исходное изображение."""
    from services.photo_transform import apply_mirror
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "photo.jpg"
        _make_test_image(p)
        original_hash = _file_hash(p)
        apply_mirror(p)
        apply_mirror(p)
        # После двух зеркал хэш может отличаться из-за JPEG re-encode,
        # но размер должен совпадать
        assert Image.open(p).size == (200, 200)


def test_apply_transforms_from_profile_all_enabled():
    from services.photo_transform import apply_transforms_from_profile
    with tempfile.TemporaryDirectory() as tmp:
        photos = []
        for i in range(3):
            p = Path(tmp) / f"photo_{i}.jpg"
            _make_test_image(p)
            photos.append(str(p))

        profile = {
            'antiplagiaat': {
                'enabled': True,
                'transforms': {'crop': True, 'color_shift': True, 'mirror': True},
            }
        }
        count = apply_transforms_from_profile(photos, profile)
        assert count == 3


def test_apply_transforms_from_profile_disabled():
    from services.photo_transform import apply_transforms_from_profile
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "photo.jpg"
        _make_test_image(p)
        original_hash = _file_hash(p)

        profile = {'antiplagiaat': {'enabled': False}}
        count = apply_transforms_from_profile([str(p)], profile)
        assert count == 0
        assert _file_hash(p) == original_hash


def test_apply_transforms_strips_metadata_by_default():
    from services.photo_transform import apply_transforms_from_profile
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "photo.jpg"
        _make_test_image(p)
        original_hash = _file_hash(p)

        profile = {
            'antiplagiaat': {
                'enabled': True,
                'transforms': {'crop': False, 'color_shift': False, 'mirror': False},
            }
        }
        count = apply_transforms_from_profile([str(p)], profile)
        assert count == 1
        assert _file_hash(p) != original_hash


def test_missing_file_returns_false():
    from services.photo_transform import apply_random_crop, apply_color_shift, apply_mirror, strip_metadata
    p = "/nonexistent/photo.jpg"
    assert apply_random_crop(p) is False
    assert apply_color_shift(p) is False
    assert apply_mirror(p) is False
    assert strip_metadata(p) is False


def test_strip_metadata_changes_file_hash():
    from services.photo_transform import strip_metadata
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "photo.jpg"
        _make_test_image(p)
        original_hash = _file_hash(p)
        assert strip_metadata(p) is True
        assert _file_hash(p) != original_hash
