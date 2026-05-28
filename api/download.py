# -*- coding: utf-8 -*-
"""Download routes."""

from fastapi import APIRouter

from config import app_state
from workers.download import download_worker, download_all_worker

router = APIRouter()


@router.post('/download/start')
async def start_download(data: dict):
    if app_state.is_downloading:
        return {'status': 'error', 'message': 'Загрузка уже идёт'}
    cid = str(data.get('community_id', '')).strip()
    count = int(data.get('count', app_state.profile.get('download_settings', {}).get('posts_to_download', 100)))
    if not cid:
        return {'status': 'error', 'message': 'community_id не указан'}
    app_state.is_downloading = True
    import threading
    threading.Thread(target=download_worker, args=(cid, count), daemon=True).start()
    return {'status': 'ok', 'message': f'Загрузка {count} постов запущена'}


@router.post('/download/start_all')
async def start_download_all():
    if app_state.is_downloading:
        return {'status': 'error', 'message': 'Загрузка уже идёт'}
    from config import app_state
    sources = [s for s in app_state.profile.get('sources', []) if s.get('enabled')]
    if not sources:
        return {'status': 'error', 'message': 'Нет активных источников'}
    app_state.is_downloading = True
    import threading
    threading.Thread(target=download_all_worker, daemon=True).start()
    return {'status': 'ok', 'message': f'Загрузка из {len(sources)} источников'}


@router.post('/download/pause')
async def pause_download():
    app_state.is_downloading = False
    app_state.add_log('Загрузка остановлена', 'warning')
    return {'status': 'ok'}


@router.get('/download/progress')
async def download_progress():
    p = app_state.download_progress
    t = p.get('total', 0)
    c = p.get('current', 0)
    return {
        'is_downloading': app_state.is_downloading,
        'current': c, 'total': t,
        'percent': round(c / t * 100) if t else 0,
        'source': p.get('source', ''),
    }


@router.get('/posts/downloaded')
async def get_downloaded():
    try:
        files = sorted(app_state.posts_dir.glob('*.json'),
                       key=lambda f: f.stat().st_mtime, reverse=True)
        posts = []
        for fp in files[:50]:
            try:
                import json
                from datetime import datetime
                p = json.loads(fp.read_text(encoding='utf-8'))
                posts.append({
                    'id': p.get('id'),
                    'text': p.get('text', '')[:200],
                    'date': datetime.fromtimestamp(p.get('date', 0)).strftime('%Y-%m-%d %H:%M'),
                    'attachments_count': len(p.get('attachments', [])),
                })
            except Exception:
                pass
        return {'status': 'ok', 'posts': posts, 'total': len(list(app_state.posts_dir.glob('*.json')))}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
