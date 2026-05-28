# -*- coding: utf-8 -*-
"""Statistics routes."""

from fastapi import APIRouter
from datetime import datetime
import shutil

from config import app_state, STORAGE_DIR
from services.storage import read_last_scheduled

router = APIRouter()


@router.get('/statistics')
async def get_statistics():
    pending = len(list(app_state.posts_dir.glob('*.json')))
    stats = app_state.load_stats()
    published = stats.get('published', 0)
    failed = stats.get('failed', 0)
    pub_cfg = app_state.profile.get('publishing_settings', {})
    delay_min = int(pub_cfg.get('publish_delay_min', 3600))
    delay_max = int(pub_cfg.get('publish_delay_max', delay_min))
    avg_delay = (delay_min + delay_max) // 2
    last_ts = read_last_scheduled()

    estimated_end = None
    if last_ts and pending > 0 and avg_delay > 0:
        end_ts = last_ts + pending * avg_delay
        estimated_end = datetime.fromtimestamp(end_ts).strftime('%d.%m.%Y %H:%M')

    profile_dir = STORAGE_DIR / app_state.active_profile_id
    storage_mb = 0.0
    try:
        if profile_dir.exists():
            total = sum(f.stat().st_size for f in profile_dir.rglob('*') if f.is_file())
            storage_mb = round(total / 1024 / 1024, 1)
    except Exception:
        pass

    try:
        disk_free_gb = round(shutil.disk_usage(str(STORAGE_DIR)).free / 1024 ** 3, 1)
    except Exception:
        disk_free_gb = None

    return {
        'downloaded': pending + published,
        'published': published,
        'pending': pending,
        'failed': failed,
        'estimated_end': estimated_end,
        'storage_mb': storage_mb,
        'disk_free_gb': disk_free_gb,
        'is_downloading': app_state.is_downloading,
        'is_publishing': app_state.is_publishing,
        'is_monitoring': app_state.is_monitoring,
        'download_source': app_state.download_progress.get('source', ''),
    }
