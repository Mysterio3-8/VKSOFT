# -*- coding: utf-8 -*-
"""Token master routes: parse, mask and validate VK tokens."""

import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter

from config import app_state
from vk.api import validate_vk_tokens

router = APIRouter()


def _mask(token: str) -> str:
    token = (token or '').strip()
    if not token:
        return ''
    if len(token) <= 12:
        return token[:2] + '***'
    return token[:6] + '...' + token[-4:]


def _parse_token(value: str) -> dict:
    raw = (value or '').strip()
    if not raw:
        return {'token': '', 'expires_in': None}

    candidates = []
    parsed = urlparse(raw)
    for part in (parsed.query, parsed.fragment):
        if part:
            data = parse_qs(part)
            candidates.append(data)
    if '=' in raw and not candidates:
        candidates.append(parse_qs(raw.lstrip('#?')))

    for data in candidates:
        token = (data.get('access_token') or data.get('token') or [''])[0]
        if token:
            expires_raw = (data.get('expires_in') or [None])[0]
            try:
                expires_in = int(expires_raw) if expires_raw is not None else None
            except Exception:
                expires_in = None
            return {'token': token.strip(), 'expires_in': expires_in}

    return {'token': raw, 'expires_in': None}


def _token_info(kind: str, token: str, expires_at: int) -> dict:
    now = int(time.time())
    expires_label = 'неизвестно'
    status = 'unknown'
    if not token:
        status = 'missing'
        expires_label = 'токен не задан'
    elif expires_at == 0:
        status = 'ok'
        expires_label = 'без срока или неизвестно'
    elif expires_at > now:
        hours_left = round((expires_at - now) / 3600, 1)
        status = 'warning' if hours_left <= 24 else 'ok'
        expires_label = f'осталось {hours_left} ч'
    else:
        status = 'expired'
        expires_label = 'истек'
    return {
        'kind': kind,
        'present': bool(token),
        'masked': _mask(token),
        'status': status,
        'expires_at': expires_at,
        'expires_label': expires_label,
    }


@router.get('/tokens/status')
async def tokens_status():
    profile = app_state.profile
    vk = profile.get('vk', {})
    tm = profile.get('token_manager', {})
    return {
        'status': 'ok',
        'user': _token_info('user', vk.get('user_token', ''), int(tm.get('user_expires_at', 0) or 0)),
        'group': _token_info('group', vk.get('group_token', ''), int(tm.get('group_expires_at', 0) or 0)),
        'last_check': tm.get('last_check', ''),
        'last_error': tm.get('last_error', ''),
    }


@router.post('/tokens/parse')
async def parse_token(data: dict):
    kind = str(data.get('kind', 'user')).strip().lower()
    if kind not in ('user', 'group'):
        return {'status': 'error', 'message': 'kind должен быть user или group'}

    parsed = _parse_token(data.get('value', ''))
    token = parsed.get('token', '')
    if not token:
        return {'status': 'error', 'message': 'Токен не найден'}

    expires_in = parsed.get('expires_in')
    expires_at = 0
    if expires_in and expires_in > 0:
        expires_at = int(time.time()) + int(expires_in)

    saved = bool(data.get('save', False))
    if saved:
        profile = app_state.profile
        profile.setdefault('vk', {})[f'{kind}_token'] = token
        profile.setdefault('token_manager', {})[f'{kind}_expires_at'] = expires_at
        app_state.save_config()
        app_state.add_log(f'Токен {kind}: сохранен через мастер', 'info')

    return {
        'status': 'ok',
        'message': 'Токен распознан и сохранен' if saved else 'Токен распознан',
        'kind': kind,
        'masked': _mask(token),
        'expires_in': expires_in,
        'expires_at': expires_at,
        'saved': saved,
    }


@router.post('/tokens/validate')
async def tokens_validate():
    try:
        result = validate_vk_tokens()
        tm = app_state.profile.setdefault('token_manager', {})
        tm['last_check'] = datetime.now().strftime('%d.%m.%Y %H:%M')
        tm['last_error'] = '; '.join(result.get('errors', []))
        app_state.save_config()
        status_payload = await tokens_status()
        return {'status': 'ok', **status_payload, **result}
    except Exception as e:
        app_state.profile.setdefault('token_manager', {})['last_error'] = str(e)
        app_state.save_config()
        return {'status': 'error', 'message': str(e)}
