# -*- coding: utf-8 -*-
"""Единый антиплагиат-пайплайн для любого медиа.

Одна точка входа для фото (Pillow) и видео/клипов (ffmpeg):
кроп, цветовой сдвиг, зеркало, рамка, размытые плашки (blur-pad),
вотермарка, подмена метаданных. В hard-режиме (antiplagiaat.enabled)
рамка и blur-pad применяются случайно, чтобы каждый файл был уникален.
"""

import random
from pathlib import Path

from services.photo_transform import (
    apply_blur_pad,
    apply_color_shift,
    apply_fake_metadata,
    apply_frame,
    apply_mirror,
    apply_random_crop,
)
from services.watermark import apply_watermark_from_profile

# Вероятности случайных эффектов в hard-режиме
_FRAME_CHANCE = 0.25
_BLUR_PAD_CHANCE = 0.30


def _maybe(cfg_value, chance: float) -> bool:
    """true/false из конфига — как есть; отсутствие ('auto') — случайно."""
    if isinstance(cfg_value, bool):
        return cfg_value
    return random.random() < chance


def process_photos(local_photos: list, profile: dict) -> int:
    """Применить антиплагиат + вотермарку к списку фото. Возвращает кол-во обработанных.

    Зеркалится максимум одно случайное фото из списка (всё зеркалить — подозрительно).
    """
    photos = [str(p) for p in (local_photos or []) if p]
    if not photos:
        return 0

    ap_cfg = profile.get('antiplagiaat', {})
    ap_on = bool(ap_cfg.get('enabled'))
    tr = ap_cfg.get('transforms', {}) if ap_on else {}
    wm_on = bool(profile.get('watermark', {}).get('enabled'))
    if not ap_on and not wm_on:
        return 0

    do_crop = tr.get('crop', ap_on)
    do_color = tr.get('color_shift', ap_on)
    do_mirror = tr.get('mirror', False)
    do_meta = tr.get('strip_metadata', ap_on)
    mirror_idx = random.randrange(len(photos)) if do_mirror else -1

    count = 0
    for idx, photo in enumerate(photos):
        if not Path(photo).exists():
            continue
        ok = True
        if do_crop:
            ok = apply_random_crop(photo) and ok
        if do_color:
            ok = apply_color_shift(photo) and ok
        if do_mirror and idx == mirror_idx:
            ok = apply_mirror(photo) and ok
        if ap_on and _maybe(tr.get('blur_pad'), _BLUR_PAD_CHANCE):
            ok = apply_blur_pad(photo) and ok
        if ap_on and _maybe(tr.get('frame'), _FRAME_CHANCE):
            frame_color = random.choice([(255, 255, 255), (16, 16, 16)])
            ok = apply_frame(photo, color=frame_color) and ok
        if wm_on:
            apply_watermark_from_profile(photo, profile)
        if do_meta:
            ok = apply_fake_metadata(photo) and ok
        if ok:
            count += 1
    return count


def process_video(video_path: str | Path, profile: dict, *,
                  title: str = '', is_clip: bool = False) -> bool:
    """Антиплагиат видео/клипа: кроп, вырез, лого, скорость, фейды, blur-плашки."""
    from services.video_transform import transform_from_profile
    return transform_from_profile(video_path, profile, title=title, is_clip=is_clip)
