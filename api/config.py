# -*- coding: utf-8 -*-
"""Config routes."""

from fastapi import APIRouter

from config import app_state

router = APIRouter()


@router.get('/config/get')
async def get_config():
    return app_state.profile


@router.post('/config/save')
async def save_config(config: dict):
    try:
        pid = app_state.active_profile_id
        app_state.config['profiles'][pid] = app_state._deep_merge(
            app_state.config['profiles'][pid], config
        )
        app_state.save_config()
        app_state.add_log('Настройки сохранены', 'info')
        return {'status': 'ok'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
