# -*- coding: utf-8 -*-
"""Media API — фото / видео / клипы."""

import threading
from fastapi import APIRouter
from config import app_state

router = APIRouter()


# ════════════════════════════════════════════════════════════════
# ФОТО
# ════════════════════════════════════════════════════════════════

@router.post('/media/photos/download/start')
async def photos_download_start():
    if app_state.is_downloading_photos:
        return {'status': 'error', 'message': 'Загрузка фото уже идёт'}
    profile = app_state.profile
    if not profile.get('photos_settings', {}).get('enabled', False):
        return {'status': 'error', 'message': 'Загрузка фото отключена в настройках'}
    sources = [s for s in profile.get('sources', []) if s.get('enabled')]
    if not sources:
        return {'status': 'error', 'message': 'Нет активных источников'}
    app_state.is_downloading_photos = True
    from workers.photos import download_photos_worker
    threading.Thread(target=download_photos_worker, daemon=True).start()
    return {'status': 'ok', 'message': f'Загрузка фото из {len(sources)} источников запущена'}


@router.post('/media/photos/download/stop')
async def photos_download_stop():
    app_state.is_downloading_photos = False
    app_state.add_log('Загрузка фото остановлена', 'warning')
    return {'status': 'ok'}


@router.post('/media/photos/publish/start')
async def photos_publish_start():
    if app_state.is_publishing_photos:
        return {'status': 'error', 'message': 'Публикация фото уже идёт'}
    from workers.photos import queue_count
    pending = queue_count()
    if pending == 0:
        return {'status': 'error', 'message': 'Нет фото в очереди. Сначала скачай.'}
    count = app_state.profile.get('photos_settings', {}).get('photos_per_run', 50)
    app_state.is_publishing_photos = True
    from workers.photos import publish_photos_worker
    threading.Thread(target=publish_photos_worker, args=(count,), daemon=True).start()
    return {'status': 'ok', 'message': f'Публикация {min(count, pending)} фото'}


@router.post('/media/photos/publish/stop')
async def photos_publish_stop():
    app_state.is_publishing_photos = False
    app_state.add_log('Публикация фото остановлена', 'warning')
    return {'status': 'ok'}


@router.get('/media/photos/status')
async def photos_status():
    from workers.photos import queue_count
    return {
        'is_downloading': app_state.is_downloading_photos,
        'is_publishing':  app_state.is_publishing_photos,
        'queue':          queue_count(),
    }


# ════════════════════════════════════════════════════════════════
# ВИДЕО
# ════════════════════════════════════════════════════════════════

@router.post('/media/videos/download/start')
async def videos_download_start():
    if app_state.is_downloading_videos:
        return {'status': 'error', 'message': 'Загрузка видео уже идёт'}
    sources = [s for s in app_state.profile.get('sources', []) if s.get('enabled')]
    if not sources:
        return {'status': 'error', 'message': 'Нет активных источников'}
    app_state.is_downloading_videos = True
    from workers.videos import download_videos_worker
    threading.Thread(target=download_videos_worker, daemon=True).start()
    return {'status': 'ok', 'message': f'Загрузка видео из {len(sources)} источников'}


@router.post('/media/videos/download/stop')
async def videos_download_stop():
    app_state.is_downloading_videos = False
    app_state.add_log('Загрузка видео остановлена', 'warning')
    return {'status': 'ok'}


@router.post('/media/videos/publish/start')
async def videos_publish_start():
    if app_state.is_publishing_videos:
        return {'status': 'error', 'message': 'Публикация видео уже идёт'}
    pending = len(list(app_state.videos_queue_dir.glob('*.json')))
    if pending == 0:
        return {'status': 'error', 'message': 'Нет видео в очереди. Сначала скачай.'}
    count = app_state.profile.get('videos_settings', {}).get('videos_per_run', 10)
    app_state.is_publishing_videos = True
    from workers.videos import publish_videos_worker
    threading.Thread(target=publish_videos_worker, args=(count, False), daemon=True).start()
    return {'status': 'ok', 'message': f'Публикация {min(count, pending)} видео'}


@router.post('/media/videos/publish/stop')
async def videos_publish_stop():
    app_state.is_publishing_videos = False
    app_state.add_log('Публикация видео остановлена', 'warning')
    return {'status': 'ok'}


@router.get('/media/videos/status')
async def videos_status():
    pending = len(list(app_state.videos_queue_dir.glob('*.json')))
    return {
        'is_downloading': app_state.is_downloading_videos,
        'is_publishing':  app_state.is_publishing_videos,
        'queue':          pending,
    }


# ════════════════════════════════════════════════════════════════
# КЛИПЫ
# ════════════════════════════════════════════════════════════════

@router.post('/media/clips/download/start')
async def clips_download_start():
    if app_state.is_downloading_clips:
        return {'status': 'error', 'message': 'Загрузка клипов уже идёт'}
    sources = [s for s in app_state.profile.get('sources', []) if s.get('enabled')]
    if not sources:
        return {'status': 'error', 'message': 'Нет активных источников'}
    app_state.is_downloading_clips = True
    from workers.clips import download_clips_worker
    threading.Thread(target=download_clips_worker, daemon=True).start()
    return {'status': 'ok', 'message': f'Загрузка клипов из {len(sources)} источников'}


@router.post('/media/clips/download/stop')
async def clips_download_stop():
    app_state.is_downloading_clips = False
    app_state.add_log('Загрузка клипов остановлена', 'warning')
    return {'status': 'ok'}


@router.post('/media/clips/publish/start')
async def clips_publish_start():
    if app_state.is_publishing_clips:
        return {'status': 'error', 'message': 'Публикация клипов уже идёт'}
    pending = len(list(app_state.clips_queue_dir.glob('*.json')))
    if pending == 0:
        return {'status': 'error', 'message': 'Нет клипов в очереди. Сначала скачай.'}
    count = app_state.profile.get('clips_settings', {}).get('clips_per_run', 10)
    app_state.is_publishing_clips = True
    from workers.clips import publish_clips_worker
    threading.Thread(target=publish_clips_worker, args=(count,), daemon=True).start()
    return {'status': 'ok', 'message': f'Публикация {min(count, pending)} клипов'}


@router.post('/media/clips/publish/stop')
async def clips_publish_stop():
    app_state.is_publishing_clips = False
    app_state.add_log('Публикация клипов остановлена', 'warning')
    return {'status': 'ok'}


@router.get('/media/clips/status')
async def clips_status():
    pending = len(list(app_state.clips_queue_dir.glob('*.json')))
    return {
        'is_downloading': app_state.is_downloading_clips,
        'is_publishing':  app_state.is_publishing_clips,
        'queue':          pending,
    }


# ════════════════════════════════════════════════════════════════
# Общий статус всех типов
# ════════════════════════════════════════════════════════════════

@router.get('/media/status')
async def all_media_status():
    from workers.photos import queue_count as ph_q
    return {
        'photos': {
            'is_downloading': app_state.is_downloading_photos,
            'is_publishing':  app_state.is_publishing_photos,
            'queue':          ph_q(),
        },
        'videos': {
            'is_downloading': app_state.is_downloading_videos,
            'is_publishing':  app_state.is_publishing_videos,
            'queue':          len(list(app_state.videos_queue_dir.glob('*.json'))),
        },
        'clips': {
            'is_downloading': app_state.is_downloading_clips,
            'is_publishing':  app_state.is_publishing_clips,
            'queue':          len(list(app_state.clips_queue_dir.glob('*.json'))),
        },
    }
