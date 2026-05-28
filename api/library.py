# -*- coding: utf-8 -*-
"""API управления библиотекой текстов и опросов."""

from fastapi import APIRouter
from services.content_library import (
    load_library, save_library, DEFAULT_ENTRIES, DEFAULT_POLLS,
    NICHE_PRESETS, NICHE_LABELS, apply_niche_preset,
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
