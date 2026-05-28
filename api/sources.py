# -*- coding: utf-8 -*-
"""Sources routes."""

from fastapi import APIRouter

from config import app_state

router = APIRouter()


@router.post('/sources/add')
async def add_source(data: dict):
    name = data.get('name', '').strip()
    cid = str(data.get('community_id', '')).strip()
    if not name or not cid:
        return {'status': 'error', 'message': 'Укажи название и ID'}
    sources = app_state.config['profiles'][app_state.active_profile_id].setdefault('sources', [])
    src = {'id': len(sources) + 1, 'name': name, 'community_id': cid, 'enabled': True}
    sources.append(src)
    app_state.save_config()
    return {'status': 'ok', 'source': src}


@router.post('/sources/remove')
async def remove_source(data: dict):
    sid = data.get('id')
    profile = app_state.config['profiles'][app_state.active_profile_id]
    profile['sources'] = [s for s in profile.get('sources', []) if s['id'] != sid]
    app_state.save_config()
    return {'status': 'ok'}
