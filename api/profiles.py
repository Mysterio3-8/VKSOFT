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
        vk = p.get('vk', {})
        result.append({
            **p,
            'group_id': vk.get('group_id', ''),
            'active': pid == active,
            'pending': pending,
        })
    return {'profiles': result, 'active': active}


@router.post('/profiles/create')
async def create_profile(data: dict):
    name = data.get('name', '').strip()
    group_id = str(data.get('group_id') or data.get('channel_id') or '').strip().lstrip('-')
    if not name:
        return {'status': 'error', 'message': 'Укажи название канала'}
    if not group_id:
        return {'status': 'error', 'message': 'Укажи ID канала'}
    import uuid
    pid = f'p{uuid.uuid4().hex[:6]}'
    from config import AppState
    prof = AppState.default_profile(pid, name)
    prof['vk']['group_id'] = group_id
    prof['vk']['api_version'] = '5.131'
    app_state.config.setdefault('profiles', {})[pid] = prof
    app_state.active_profile_id = pid
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
    updates = {}
    if 'name' in data:
        updates['name'] = str(data.get('name', '')).strip() or profiles[pid].get('name', pid)
    if 'group_id' in data or 'channel_id' in data:
        group_id = str(data.get('group_id') or data.get('channel_id') or '').strip().lstrip('-')
        if not group_id:
            return {'status': 'error', 'message': 'Укажи ID канала'}
        updates.setdefault('vk', {})['group_id'] = group_id
    if 'vk' in data:
        vk_updates = dict(data.get('vk') or {})
        vk_updates['api_version'] = '5.131'
        updates['vk'] = app_state._deep_merge(updates.get('vk', {}), vk_updates)
    profiles[pid] = app_state._deep_merge(profiles[pid], updates or data)
    profiles[pid].setdefault('vk', {})['api_version'] = '5.131'
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
