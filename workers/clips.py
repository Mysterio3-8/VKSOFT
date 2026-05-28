# -*- coding: utf-8 -*-
"""Клипы-воркер: делегирует в videos.py с is_clips_mode=True."""

from config import app_state
from workers.videos import (
    _download_videos_source,
    publish_videos_worker,
)


def download_clips_worker():
    profile = app_state.profile
    sources = [s for s in profile.get('sources', []) if s.get('enabled')]
    cfg = profile.get('clips_settings', {})
    count        = int(cfg.get('clips_per_run', 10))
    max_duration = int(cfg.get('max_duration_sec', 180))
    quality      = cfg.get('quality', '720')

    if not sources:
        app_state.add_log('Клипы: нет активных источников', 'warning')
        app_state.is_downloading_clips = False
        return
    try:
        for src in sources:
            if not app_state.is_downloading_clips:
                break
            cid = str(src.get('community_id', ''))
            app_state.add_log(f'Клипы: источник {src.get("name", cid)}', 'info')
            _download_videos_source(
                cid, count,
                max_duration=max_duration,
                quality=quality,
                is_clips_mode=True,
            )
    except Exception as e:
        app_state.add_log(f'Клипы загрузка: {e}', 'error')
    finally:
        app_state.is_downloading_clips = False


def publish_clips_worker(count: int):
    publish_videos_worker(count, is_clips_mode=True)
