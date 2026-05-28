# -*- coding: utf-8 -*-
"""Publish routes."""

from fastapi import APIRouter
from datetime import datetime

from config import app_state
from services.storage import read_last_scheduled, write_last_scheduled
from workers.publish import publish_worker

router = APIRouter()


@router.post('/publish/start')
async def start_publish(data: dict):
    if app_state.is_publishing:
        return {'status': 'error', 'message': 'Публикация уже идёт'}
    pending = len(list(app_state.posts_dir.glob('*.json')))
    if pending == 0:
        return {'status': 'error', 'message': 'Нет постов. Сначала загрузи.'}
    count = int(data.get('count', app_state.profile.get('publishing_settings', {}).get('posts_to_publish', 50)))
    app_state.is_publishing = True
    import threading
    threading.Thread(target=publish_worker, args=(count,), daemon=True).start()
    return {'status': 'ok', 'message': f'Публикация {min(count, pending)} постов'}


@router.post('/publish/pause')
async def pause_publish():
    app_state.is_publishing = False
    app_state.add_log('Публикация остановлена', 'warning')
    return {'status': 'ok'}


@router.get('/posts/pending')
async def get_pending():
    try:
        from vk.api import get_best_photo_url
        files = sorted(app_state.posts_dir.glob('*.json'),
                       key=lambda f: f.stat().st_mtime, reverse=True)[:50]
        posts = []
        for fp in files:
            try:
                import json
                from pathlib import Path
                p = json.loads(fp.read_text(encoding='utf-8'))
                text = p.get('text', '')
                photos = [a for a in p.get('attachments', []) if a.get('type') == 'photo']
                thumb_url = None
                if photos:
                    thumb_url = get_best_photo_url(photos[0].get('photo', {}))
                local_photos = p.get('_local_photos', [])
                has_local_photo = bool(local_photos and Path(local_photos[0]).exists())
                posts.append({
                    'id': p.get('id'),
                    'text': text[:200],
                    'has_more_text': len(text) > 200,
                    'date': datetime.fromtimestamp(p.get('date', 0)).strftime('%Y-%m-%d %H:%M'),
                    'photo_count': len(photos),
                    'has_photo': has_local_photo,
                    'thumb_url': thumb_url,
                    'filename': fp.name,
                })
            except Exception:
                pass
        return {'status': 'ok', 'count': len(list(app_state.posts_dir.glob('*.json'))), 'posts': posts}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.get('/publish/last_scheduled')
async def get_last_scheduled():
    ts = read_last_scheduled()
    if ts:
        return {
            'status': 'ok',
            'timestamp': ts,
            'datetime': datetime.fromtimestamp(ts).strftime('%Y-%m-%dT%H:%M'),
            'human': datetime.fromtimestamp(ts).strftime('%d.%m.%Y %H:%M'),
        }
    return {'status': 'empty', 'timestamp': None, 'datetime': None, 'human': 'Не задано'}


@router.post('/publish/last_scheduled')
async def set_last_scheduled(data: dict):
    try:
        ts = data.get('timestamp') or int(
            datetime.fromisoformat(data.get('datetime', '')).timestamp()
        )
        write_last_scheduled(int(ts))
        human = datetime.fromtimestamp(int(ts)).strftime('%d.%m.%Y %H:%M')
        return {'status': 'ok', 'human': human, 'timestamp': int(ts)}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.post('/publish/last_scheduled_from_vk')
async def fetch_scheduled_vk():
    try:
        from vk.api import get_vk_api, fetch_last_postponed_from_vk
        vk_cfg = app_state.profile.get('vk', {})
        gt = vk_cfg.get('group_token', '').strip()
        gid = vk_cfg.get('group_id', '').strip()
        if not gt or not gid:
            return {'status': 'error', 'message': 'Group Token и Group ID не заданы'}
        vk = get_vk_api(gt, vk_cfg.get('api_version', '5.131'))
        oid = f'-{gid.lstrip("-")}'
        ts = fetch_last_postponed_from_vk(vk, oid)
        if ts:
            write_last_scheduled(ts)
            return {
                'status': 'ok',
                'timestamp': ts,
                'datetime': datetime.fromtimestamp(ts).strftime('%Y-%m-%dT%H:%M'),
                'human': datetime.fromtimestamp(ts).strftime('%d.%m.%Y %H:%M'),
            }
        return {'status': 'warning', 'message': 'Отложенных постов не найдено'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
