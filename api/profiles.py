# -*- coding: utf-8 -*-
"""Profile routes."""

from fastapi import APIRouter

from config import app_state, STORAGE_DIR

router = APIRouter()


@router.get('/profiles')
async def list_profiles():
    profiles = app_state.config.get('profiles', {})
    active = app_state.active_profile_id
    result = []
    for pid, p in profiles.items():
        pending = len(list((STORAGE_DIR / pid / 'downloaded_posts').glob('*.json'))) \
                  if (STORAGE_DIR / pid / 'downloaded_posts').exists() else 0
        result.append({**p, 'active': pid == active, 'pending': pending})
    return {'profiles': result, 'active': active}


@router.post('/profiles/create')
async def create_profile(data: dict):
    name = data.get('name', '').strip()
    color = data.get('color', '#7c3aed')
    if not name:
        return {'status': 'error', 'message': 'Укажи название канала'}
    import uuid
    pid = f'p{uuid.uuid4().hex[:6]}'
    from config import AppState
    prof = AppState.default_profile(pid, name)
    prof['color'] = color
    app_state.config.setdefault('profiles', {})[pid] = prof
    app_state.save_config()
    app_state.add_log(f'Канал создан: {name}', 'info')
    return {'status': 'ok', 'profile': prof}


@router.post('/profiles/switch')
async def switch_profile(data: dict):
    pid = data.get('id', '')
    if pid not in app_state.config.get('profiles', {}):
        return {'status': 'error', 'message': 'Профиль не найден'}
    if app_state.is_downloading or app_state.is_publishing:
        return {'status': 'error', 'message': 'Нельзя переключить во время работы бота'}
    app_state.active_profile_id = pid
    app_state.save_config()
    app_state.add_log(f'Переключён на канал: {app_state.profile.get("name")}', 'info')
    return {'status': 'ok', 'active': pid}


@router.post('/profiles/update')
async def update_profile(data: dict):
    pid = data.get('id', app_state.active_profile_id)
    profiles = app_state.config.get('profiles', {})
    if pid not in profiles:
        return {'status': 'error', 'message': 'Профиль не найден'}
    profiles[pid] = app_state._deep_merge(profiles[pid], data)
    app_state.save_config()
    app_state.add_log('Настройки канала сохранены', 'info')
    return {'status': 'ok'}


@router.delete('/profiles/{pid}')
async def delete_profile(pid: str):
    profiles = app_state.config.get('profiles', {})
    if len(profiles) <= 1:
        return {'status': 'error', 'message': 'Нельзя удалить последний канал'}
    if pid not in profiles:
        return {'status': 'error', 'message': 'Канал не найден'}
    del profiles[pid]
    if app_state.active_profile_id == pid:
        app_state.active_profile_id = next(iter(profiles))
    app_state.save_config()
    return {'status': 'ok'}
