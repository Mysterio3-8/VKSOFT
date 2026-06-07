# -*- coding: utf-8 -*-
"""Cleanup routes."""

from fastapi import APIRouter

from config import app_state
from services.cleanup_storage import (
    cleanup_downloaded_posts,
    cleanup_junk,
    cleanup_media_queues,
    is_storage_busy,
    storage_status,
)

router = APIRouter()


def _busy():
    return is_storage_busy()


@router.get('/cleanup/status')
async def cleanup_status():
    return storage_status()


@router.post('/cleanup/posts')
async def cleanup_posts():
    if _busy():
        return {'status': 'error', 'message': 'Нельзя чистить во время работы'}
    try:
        result = cleanup_downloaded_posts(older_than_days=0)
        app_state.add_log(
            f'Очищено: {result["deleted_posts"]} постов, {result["deleted_photos"]} фото',
            'warning'
        )
        return {'status': 'ok', **result}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.post('/cleanup/junk')
async def cleanup_junk_route():
    if _busy():
        return {'status': 'error', 'message': 'Нельзя чистить во время работы'}
    try:
        result = cleanup_junk()
        app_state.add_log(
            'Мусор очищен: '
            f'{result["deleted_orphan_dirs"]} папок, '
            f'{result["deleted_orphan_files"]} файлов, '
            f'{result["deleted_temp_files"]} временных',
            'warning'
        )
        return {'status': 'ok', **result}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.post('/cleanup/media')
async def cleanup_media():
    if _busy():
        return {'status': 'error', 'message': 'Нельзя чистить во время работы'}
    try:
        result = cleanup_media_queues()
        app_state.add_log(f'Медиа-очереди очищены: {result["deleted_media_files"]} файлов', 'warning')
        return {'status': 'ok', **result}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.post('/cleanup/all')
async def cleanup_all():
    if _busy():
        return {'status': 'error', 'message': 'Нельзя чистить во время работы'}
    try:
        posts = cleanup_downloaded_posts(older_than_days=0)
        junk = cleanup_junk()
        media = cleanup_media_queues()
        app_state.save_stats({'published': 0, 'failed': 0})
        lsf = app_state.last_scheduled_file
        if lsf.exists():
            lsf.unlink()
        off = app_state.offsets_file
        if off.exists():
            off.unlink()
        app_state.logs = []
        app_state.download_progress = {'current': 0, 'total': 0, 'source': ''}
        return {'status': 'ok', **posts, **junk, **media}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
