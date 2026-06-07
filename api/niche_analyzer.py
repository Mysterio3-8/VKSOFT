# -*- coding: utf-8 -*-
"""Niche analyzer routes."""

import threading
from fastapi import APIRouter

from config import app_state
from services.niche_analyzer import run_niche_scan, AUTO_KEYWORDS

router = APIRouter()


@router.post('/niche/scan')
async def niche_scan(data: dict):
    if app_state.is_niche_scanning:
        return {'status': 'error', 'message': 'Анализ уже запущен'}

    vk_cfg = app_state.profile.get('vk', {})
    if not vk_cfg.get('user_token', '').strip():
        return {'status': 'error', 'message': 'user_token не задан в настройках'}

    auto = data.get('auto', False)
    if auto:
        keywords = AUTO_KEYWORDS
    else:
        raw = data.get('keywords', [])
        keywords = [k.strip() for k in raw if isinstance(k, str) and k.strip()]

    if not keywords:
        return {'status': 'error', 'message': 'Укажите ключевые слова'}

    t = threading.Thread(target=run_niche_scan, args=(keywords,), daemon=True)
    t.start()
    return {'status': 'started', 'keywords_count': len(keywords)}


@router.get('/niche/results')
async def niche_results():
    prog = app_state.niche_progress
    total = prog.get('total', 0)
    current = prog.get('current', 0)
    progress_pct = int(current / total * 100) if total > 0 else 0

    if app_state.is_niche_scanning:
        status = 'running'
    elif app_state.niche_results:
        status = 'done'
    else:
        status = 'idle'

    return {
        'status': status,
        'progress': progress_pct,
        'current_keyword': prog.get('keyword', ''),
        'results': app_state.niche_results,
    }


@router.post('/niche/add-source')
async def niche_add_source(data: dict):
    community_id = str(data.get('community_id', '')).strip()
    name = str(data.get('name', '')).strip() or f'community_{community_id}'

    if not community_id:
        return {'status': 'error', 'message': 'community_id не указан'}

    profile = app_state.config['profiles'][app_state.active_profile_id]
    sources = profile.setdefault('sources', [])

    if any(str(s.get('community_id', '')) == community_id for s in sources):
        return {'status': 'error', 'message': 'Источник уже добавлен'}

    src = {
        'id': max((s.get('id', 0) for s in sources), default=0) + 1,
        'name': name,
        'community_id': community_id,
        'enabled': True,
    }
    sources.append(src)
    app_state.save_config()
    app_state.add_log(f'Добавлен источник из анализа ниш: {name} ({community_id})', 'info')
    return {'status': 'ok', 'source': src}
