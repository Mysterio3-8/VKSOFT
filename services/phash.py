# -*- coding: utf-8 -*-
"""Perceptual hash deduplication — пункт 6."""

import json
from pathlib import Path
from config import app_state, STORAGE_DIR, logger


def _cache_file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'phash_cache.json'


def _load() -> dict:
    f = _cache_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def _save(cache: dict):
    f = _cache_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        if len(cache) > 12000:
            keys = list(cache.keys())
            cache = {k: cache[k] for k in keys[-10000:]}
        f.write_text(json.dumps(cache), encoding='utf-8')
    except Exception as e:
        logger.warning(f'phash _save: {e}')


def is_duplicate(image_path: Path, threshold: int = 10) -> bool:
    """True если похожее фото уже есть в кэше."""
    try:
        import imagehash
        from PIL import Image
        new_h = imagehash.phash(Image.open(image_path))
        for h_str in _load().values():
            if abs(new_h - imagehash.hex_to_hash(h_str)) <= threshold:
                return True
        return False
    except Exception:
        return False


def add_to_cache(image_path: Path, key: str):
    """Добавить хэш изображения в кэш."""
    try:
        import imagehash
        from PIL import Image
        h = str(imagehash.phash(Image.open(image_path)))
        cache = _load()
        cache[key] = h
        _save(cache)
    except Exception:
        pass


def clear_cache():
    try:
        _cache_file().unlink(missing_ok=True)
    except Exception:
        pass


def cache_size() -> int:
    return len(_load())
