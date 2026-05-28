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


@router.post('/ollama/test')
async def test_ollama(data: dict):
    url = data.get('url', 'http://localhost:11434').rstrip('/')
    model = data.get('model', 'llama3.2:3b')
    try:
        import requests as req_lib
        ping = req_lib.get(f'{url}/api/tags', timeout=8)
        ping.raise_for_status()
        available = [m.get('name', '') for m in ping.json().get('models', [])]
        found = any(model.split(':')[0] in m for m in available)
        if not found:
            return {'status': 'warning',
                    'message': f'Ollama работает, модель "{model}" не найдена. Доступные: {", ".join(available) or "нет"}'}
        return {'status': 'ok', 'message': f'Ollama OK, модель "{model}" найдена ✓'}
    except req_lib.exceptions.ConnectionError:
        return {'status': 'error', 'message': f'Не удалось подключиться к {url}'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
