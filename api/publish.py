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


@router.post('/publish/fill_slots')
async def find_fill_slots():
    """Найти пустые слоты в очереди VK и вернуть их список для подтверждения."""
    try:
        from vk.api import get_vk_api
        from services.engagement import load_engagement_model
        from services.slot_finder import fetch_postponed_timestamps, find_empty_slots

        profile = app_state.profile
        vk_cfg = profile.get('vk', {})
        gt = vk_cfg.get('group_token', '').strip()
        gid = vk_cfg.get('group_id', '').strip()
        if not gt or not gid:
            return {'status': 'error', 'message': 'Group Token и Group ID не заданы'}

        pending = len(list(app_state.posts_dir.glob('*.json')))
        if pending == 0:
            return {'status': 'error', 'message': 'Нет постов в очереди для заполнения слотов'}

        vk = get_vk_api(gt, vk_cfg.get('api_version', '5.131'))
        model = load_engagement_model(app_state.active_profile_id)
        occupied = fetch_postponed_timestamps(vk, gid)
        slots = find_empty_slots(occupied, profile, model, max_slots=min(pending, 30), profile_id=app_state.active_profile_id)

        if not slots:
            return {'status': 'ok', 'slots': [], 'message': 'Свободных слотов не найдено — очередь заполнена'}

        app_state.add_log(f'[Слоты] Найдено {len(slots)} пустых слотов', 'info')
        return {'status': 'ok', 'slots': slots, 'message': f'Найдено {len(slots)} слотов'}
    except Exception as e:
        app_state.add_log(f'[Слоты] Ошибка поиска: {e}', 'error')
        return {'status': 'error', 'message': str(e)}


@router.post('/publish/fill_slots_apply')
async def apply_fill_slots(data: dict):
    """Опубликовать посты из очереди в переданные слоты."""
    try:
        import threading
        from vk.api import get_vk_api
        from services.slot_finder import fill_slots_with_queue

        slots = data.get('slots', [])
        if not slots:
            return {'status': 'error', 'message': 'Нет слотов'}

        profile = app_state.profile
        vk_cfg = profile.get('vk', {})
        gt = vk_cfg.get('group_token', '').strip()
        ut = vk_cfg.get('user_token', '').strip()
        gid = vk_cfg.get('group_id', '').strip()
        api_ver = vk_cfg.get('api_version', '5.131')

        vk_group = get_vk_api(gt, api_ver)
        vk_user = get_vk_api(ut, api_ver)

        def _run():
            result = fill_slots_with_queue(
                slots, app_state.posts_dir, vk_user, vk_group,
                gid, profile, app_state.add_log
            )
            app_state.add_log(f'[Слоты] Заполнено: {result["filled"]}, ошибок: {result["failed"]}', 'info')

        threading.Thread(target=_run, daemon=True).start()
        return {'status': 'ok', 'message': f'Запущено заполнение {len(slots)} слотов', 'filled': len(slots), 'failed': 0}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.post('/publish/check_engagement')
async def check_engagement_endpoint():
    """Проверить статистику опубликованных постов и обновить модель обучения."""
    try:
        from vk.api import get_vk_api
        from services.engagement import collect_engagement

        profile = app_state.profile
        vk_cfg = profile.get('vk', {})
        ut = vk_cfg.get('user_token', '').strip()
        gid = vk_cfg.get('group_id', '').strip()
        if not ut:
            return {'status': 'error', 'message': 'User Token не задан'}

        vk_user = get_vk_api(ut, vk_cfg.get('api_version', '5.131'))
        new_data = collect_engagement(app_state.active_profile_id, gid, vk_user)
        checked = len(new_data)
        if checked:
            app_state.add_log(f'[Обучение] Обновлены данные для {checked} постов', 'info')
        else:
            app_state.add_log('[Обучение] Новых данных нет (посты проверены или слишком свежие)', 'info')

        return {'status': 'ok', 'checked': checked, 'message': f'Проверено постов: {checked}'}
    except Exception as e:
        app_state.add_log(f'[Обучение] Ошибка: {e}', 'error')
        return {'status': 'error', 'message': str(e)}
