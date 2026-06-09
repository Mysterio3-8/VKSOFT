# -*- coding: utf-8 -*-
"""API управления библиотекой текстов и опросов."""

import uuid

from fastapi import APIRouter
from services.content_library import (
    load_library, save_library, DEFAULT_ENTRIES, DEFAULT_POLLS,
    NICHE_PRESETS, NICHE_LABELS, apply_niche_preset, DEFAULT_PROMO_MESSAGES,
)

router = APIRouter()


@router.get('/library')
async def get_library():
    lib = load_library()
    niche = lib.get('niche', 'nature')
    lib['niche_label'] = NICHE_LABELS.get(niche, niche)
    return {'status': 'ok', **lib}


@router.post('/library/save')
async def save_lib(data: dict):
    lib = load_library()
    if 'enabled' in data:
        lib['enabled'] = bool(data['enabled'])
    if 'cta_enabled' in data:
        lib['cta_enabled'] = bool(data['cta_enabled'])
    if 'entries' in data:
        lib['entries'] = data['entries']
    if 'polls' in data:
        lib['polls'] = data['polls']
    if 'ctas' in data:
        lib['ctas'] = data['ctas']
    save_library(lib)
    return {'status': 'ok'}


@router.get('/library/niches')
async def get_niches():
    return {
        'status': 'ok',
        'niches': [
            {'id': k, 'label': v['label'],
             'entries_count': len(v['entries']),
             'polls_count': len(v['polls'])}
            for k, v in NICHE_PRESETS.items()
        ],
    }


@router.post('/library/apply_niche')
async def apply_niche(data: dict):
    niche = data.get('niche', '')
    if niche not in NICHE_PRESETS:
        return {'status': 'error', 'message': f'Неизвестная ниша: {niche}'}
    ok = apply_niche_preset(niche)
    if ok:
        lib = load_library()
        return {
            'status': 'ok',
            'message': f'Пресет «{NICHE_LABELS[niche]}» применён',
            'entries_count': len(lib['entries']),
            'polls_count': len(lib['polls']),
        }
    return {'status': 'error', 'message': 'Ошибка применения пресета'}


@router.post('/library/reset')
async def reset_library():
    """Сбросить до 100 дефолтных вариантов."""
    lib = load_library()
    lib['entries'] = DEFAULT_ENTRIES
    lib['polls'] = DEFAULT_POLLS
    save_library(lib)
    return {'status': 'ok', 'count': len(DEFAULT_ENTRIES), 'polls': len(DEFAULT_POLLS)}


@router.post('/library/entry/add')
async def add_entry(data: dict):
    lib = load_library()
    entries = lib.get('entries', [])
    entries.append({'text': data.get('text', ''), 'tags': data.get('tags', '')})
    lib['entries'] = entries
    save_library(lib)
    return {'status': 'ok', 'count': len(entries)}


@router.delete('/library/entry/{idx}')
async def delete_entry(idx: int):
    lib = load_library()
    entries = lib.get('entries', [])
    if 0 <= idx < len(entries):
        entries.pop(idx)
        lib['entries'] = entries
        save_library(lib)
        return {'status': 'ok'}
    return {'status': 'error', 'message': 'Index out of range'}


@router.post('/library/poll/add')
async def add_poll(data: dict):
    lib = load_library()
    polls = lib.get('polls', [])
    polls.append({'question': data.get('question', ''), 'answers': data.get('answers', [])})
    lib['polls'] = polls
    save_library(lib)
    return {'status': 'ok', 'count': len(polls)}


@router.delete('/library/poll/{idx}')
async def delete_poll(idx: int):
    lib = load_library()
    polls = lib.get('polls', [])
    if 0 <= idx < len(polls):
        polls.pop(idx)
        lib['polls'] = polls
        save_library(lib)
        return {'status': 'ok'}
    return {'status': 'error', 'message': 'Index out of range'}


# ── Promo messages ────────────────────────────────────────────────────────

@router.get('/library/promo')
async def get_promo():
    lib = load_library()
    return {
        'status': 'ok',
        'promo_enabled': lib.get('promo_enabled', False),
        'promo_messages': lib.get('promo_messages', []),
    }


@router.post('/library/promo/toggle')
async def toggle_promo(data: dict):
    lib = load_library()
    lib['promo_enabled'] = bool(data.get('enabled', False))
    save_library(lib)
    return {'status': 'ok', 'promo_enabled': lib['promo_enabled']}


@router.post('/library/promo/add')
async def add_promo(data: dict):
    lib = load_library()
    messages = lib.get('promo_messages', [])
    new_msg = {
        'id': str(uuid.uuid4())[:8],
        'name': data.get('name', 'Новое сообщение'),
        'text': data.get('text', ''),
        'hashtags': data.get('hashtags', ''),
        'active': len(messages) == 0,
    }
    messages.append(new_msg)
    lib['promo_messages'] = messages
    save_library(lib)
    return {'status': 'ok', 'count': len(messages)}


@router.post('/library/promo/activate/{msg_id}')
async def activate_promo(msg_id: str):
    lib = load_library()
    messages = lib.get('promo_messages', [])
    found = False
    for m in messages:
        m['active'] = m.get('id') == msg_id
        if m['active']:
            found = True
    if not found:
        return {'status': 'error', 'message': 'Сообщение не найдено'}
    lib['promo_messages'] = messages
    save_library(lib)
    return {'status': 'ok'}


@router.post('/library/promo/update/{msg_id}')
async def update_promo(msg_id: str, data: dict):
    lib = load_library()
    messages = lib.get('promo_messages', [])
    for m in messages:
        if m.get('id') == msg_id:
            if 'name' in data:
                m['name'] = data['name']
            if 'text' in data:
                m['text'] = data['text']
            if 'hashtags' in data:
                m['hashtags'] = data['hashtags']
            lib['promo_messages'] = messages
            save_library(lib)
            return {'status': 'ok'}
    return {'status': 'error', 'message': 'Сообщение не найдено'}


@router.delete('/library/promo/{msg_id}')
async def delete_promo(msg_id: str):
    lib = load_library()
    messages = lib.get('promo_messages', [])
    messages = [m for m in messages if m.get('id') != msg_id]
    # Если удалили активное — активируем первое
    if messages and not any(m.get('active') for m in messages):
        messages[0]['active'] = True
    lib['promo_messages'] = messages
    save_library(lib)
    return {'status': 'ok', 'count': len(messages)}
