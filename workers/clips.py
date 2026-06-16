# -*- coding: utf-8 -*-
"""Клипы-воркер: делегирует в videos.py с is_clips_mode=True."""

from config import app_state
from workers.videos import (
    _download_videos_source,
    publish_videos_worker,
)


def download_clips_worker():
    profile = app_state.profile
    sources = profile.get('sources', [])
    cfg = profile.get('clips_settings', {})
    count        = int(cfg.get('clips_download_per_run', cfg.get('clips_per_run', 10)))
    max_duration = int(cfg.get('max_duration_sec', 180))
    quality      = cfg.get('quality', '720')

    enabled_count = sum(1 for s in sources if s.get('enabled'))
    if not enabled_count:
        app_state.add_log('Клипы: нет активных источников', 'warning')
        app_state.is_downloading_clips = False
        return
    try:
        from workers.download import eligible_sources_in_season, per_source_download_count
        eligible = eligible_sources_in_season(sources)
        if not eligible:
            app_state.add_log('Клипы: все источники в стоп-листе', 'warning')
            return
        blocked = enabled_count - len(eligible)
        if blocked:
            app_state.add_log(f'Клипы: пропущено стоп-источников {blocked}', 'info')
        total = len(eligible)
        remaining = count
        for i, src in enumerate(eligible, 1):
            if not app_state.is_downloading_clips or remaining <= 0:
                break
            cid = str(src.get('community_id', ''))
            name = src.get('name', cid)
            per = per_source_download_count(remaining, total - i + 1)
            app_state.add_log(f'Клипы: канал {i}/{total} «{name}» — беру до {per}', 'info')
            got = int(_download_videos_source(
                cid, per,
                max_duration=max_duration,
                quality=quality,
                is_clips_mode=True,
            ) or 0)
            remaining = max(0, remaining - got)
    except Exception as e:
        app_state.add_log(f'Клипы загрузка: {e}', 'error')
    finally:
        app_state.is_downloading_clips = False


def publish_clips_worker(count: int):
    publish_videos_worker(count, is_clips_mode=True)
