# -*- coding: utf-8 -*-
"""Антиплагиат-трансформации фото через Pillow.

Три независимых уровня защиты от поиска по картинке:
  - случайный кроп краёв (2–5%) — меняет хэш
  - лёгкий цветовой сдвиг (яркость + контраст ±5%) — меняет палитру
  - зеркальное отражение одного случайного фото из поста
"""

import random
from pathlib import Path
from config import logger

try:
    from PIL import Image, ImageEnhance
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


def apply_random_crop(image_path: str | Path, min_pct: float = 0.02, max_pct: float = 0.05) -> bool:
    """Обрезать случайный процент с каждого края (асимметрично)."""
    if not _PIL_OK:
        return False
    path = Path(image_path)
    if not path.exists():
        return False
    try:
        img = Image.open(path)
        w, h = img.size
        left   = int(w * random.uniform(min_pct, max_pct))
        right  = int(w * random.uniform(min_pct, max_pct))
        top    = int(h * random.uniform(min_pct, max_pct))
        bottom = int(h * random.uniform(min_pct, max_pct))
        cropped = img.crop((left, top, w - right, h - bottom))
        cropped.save(path, quality=95)
        return True
    except Exception as e:
        logger.warning(f"photo_transform crop: {e}")
        return False


def apply_color_shift(image_path: str | Path, delta: float = 0.05) -> bool:
    """Случайный сдвиг яркости и контраста в диапазоне [1-delta, 1+delta]."""
    if not _PIL_OK:
        return False
    path = Path(image_path)
    if not path.exists():
        return False
    try:
        img = Image.open(path).convert("RGB")
        brightness_factor = random.uniform(1.0 - delta, 1.0 + delta)
        contrast_factor   = random.uniform(1.0 - delta, 1.0 + delta)
        img = ImageEnhance.Brightness(img).enhance(brightness_factor)
        img = ImageEnhance.Contrast(img).enhance(contrast_factor)
        img.save(path, quality=95)
        return True
    except Exception as e:
        logger.warning(f"photo_transform color_shift: {e}")
        return False


def apply_mirror(image_path: str | Path) -> bool:
    """Горизонтальное зеркальное отражение."""
    if not _PIL_OK:
        return False
    path = Path(image_path)
    if not path.exists():
        return False
    try:
        img = Image.open(path)
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
        img.save(path, quality=95)
        return True
    except Exception as e:
        logger.warning(f"photo_transform mirror: {e}")
        return False


def strip_metadata(image_path: str | Path) -> bool:
    """Remove EXIF/metadata by re-saving the image as plain RGB JPEG."""
    if not _PIL_OK:
        return False
    path = Path(image_path)
    if not path.exists():
        return False
    try:
        img = Image.open(path).convert("RGB")
        img.save(path, "JPEG", quality=95, optimize=True)
        return True
    except Exception as e:
        logger.warning(f"photo_transform strip_metadata: {e}")
        return False


def apply_transforms_from_profile(local_photos: list[str], profile: dict) -> int:
    """
    Применить все включённые трансформации к списку фото согласно профилю.
    Возвращает количество успешно обработанных фото.

    profile['antiplagiaat']['transforms'] = {
        'crop': true,
        'color_shift': true,
        'mirror': true   # зеркалится только одно случайное фото
    }
    """
    if not local_photos:
        return 0

    ap_cfg = profile.get('antiplagiaat', {})
    if not ap_cfg.get('enabled'):
        return 0

    transforms = ap_cfg.get('transforms', {})
    do_crop    = transforms.get('crop', False)
    do_color   = transforms.get('color_shift', False)
    do_mirror  = transforms.get('mirror', False)
    do_strip   = transforms.get('strip_metadata', True)

    if not (do_crop or do_color or do_mirror or do_strip):
        return 0

    # Выбрать одно случайное фото для зеркала (не всё зеркалить — подозрительно)
    mirror_idx = random.randrange(len(local_photos)) if do_mirror else -1

    count = 0
    for idx, photo_path in enumerate(local_photos):
        ok = True
        if do_crop:
            ok = apply_random_crop(photo_path) and ok
        if do_color:
            ok = apply_color_shift(photo_path) and ok
        if do_mirror and idx == mirror_idx:
            ok = apply_mirror(photo_path) and ok
        if do_strip:
            ok = strip_metadata(photo_path) and ok
        if ok:
            count += 1

    return count
