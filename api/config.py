# -*- coding: utf-8 -*-
"""Config routes."""

from fastapi import APIRouter, UploadFile, File
from pathlib import Path

from config import app_state, BASE_DIR

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


@router.post('/config/upload_logo')
async def upload_logo(file: UploadFile = File(...)):
    """Загрузить PNG-логотип для водяного знака. Возвращает путь к файлу."""
    if not file.filename.lower().endswith('.png'):
        return {'status': 'error', 'message': 'Только PNG файлы'}
    logos_dir = BASE_DIR / 'logos'
    logos_dir.mkdir(exist_ok=True)
    dest = logos_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)
    return {'status': 'ok', 'path': str(dest)}
