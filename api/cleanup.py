# -*- coding: utf-8 -*-
"""Cleanup routes."""

from fastapi import APIRouter
import shutil

from config import app_state

router = APIRouter()


@router.post('/cleanup/posts')
async def cleanup_posts():
    if app_state.is_downloading or app_state.is_publishing:
        return {'status': 'error', 'message': 'Нельзя чистить во время работы'}
    try:
        jsons = list(app_state.posts_dir.glob('*.json'))
        for f in jsons:
            f.unlink()
        photos = 0
        for d in app_state.photos_dir.iterdir():
            if d.is_dir():
                photos += len(list(d.glob('*.jpg')))
                shutil.rmtree(d)
        app_state.add_log(f'Очищено: {len(jsons)} постов, {photos} фото', 'warning')
        return {'status': 'ok', 'deleted_posts': len(jsons), 'deleted_photos': photos}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.post('/cleanup/all')
async def cleanup_all():
    if app_state.is_downloading or app_state.is_publishing:
        return {'status': 'error', 'message': 'Нельзя чистить во время работы'}
    try:
        jsons = list(app_state.posts_dir.glob('*.json'))
        for f in jsons:
            f.unlink()
        photos = 0
        for d in app_state.photos_dir.iterdir():
            if d.is_dir():
                photos += len(list(d.glob('*.jpg')))
                shutil.rmtree(d)
        app_state.save_stats({'published': 0, 'failed': 0})
        lsf = app_state.last_scheduled_file
        if lsf.exists():
            lsf.unlink()
        off = app_state.offsets_file
        if off.exists():
            off.unlink()
        app_state.logs = []
        app_state.download_progress = {'current': 0, 'total': 0, 'source': ''}
        return {'status': 'ok', 'deleted_posts': len(jsons), 'deleted_photos': photos}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
