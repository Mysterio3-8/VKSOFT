# -*- coding: utf-8 -*-
"""Test routes."""

from fastapi import APIRouter

from config import app_state
from vk.api import validate_vk_tokens

router = APIRouter()


@router.post('/vk/validate')
async def vk_validate():
    try:
        result = validate_vk_tokens()
        if result['errors']:
            for err in result['errors']:
                app_state.add_log(f'Токен: {err}', 'warning')
        return {'status': 'ok', **result}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


