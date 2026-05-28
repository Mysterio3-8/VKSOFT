# -*- coding: utf-8 -*-
"""Monitor routes."""

from fastapi import APIRouter

from config import app_state
from workers.monitor import monitor_worker, _watchdog_loop
import threading

router = APIRouter()


@router.get('/monitor/status')
async def monitor_status():
    mon_cfg = app_state.profile.get('monitoring', {})
    return {
        'is_monitoring': app_state.is_monitoring,
        'last_check': app_state.monitor_last_check,
        'next_check': app_state.monitor_next_check,
        'sources': mon_cfg.get('sources', []),
        'check_interval': mon_cfg.get('check_interval_min', 120),
        'catch_up_days': mon_cfg.get('catch_up_days', 3),
        'max_per_cycle': mon_cfg.get('max_per_cycle', 3),
        'min_views': mon_cfg.get('min_views', 0),
        'ocr_filter': mon_cfg.get('ocr_filter', False),
        'google_image': mon_cfg.get('google_image', False),
        'google_api_key': mon_cfg.get('google_api_key', ''),
        'google_cx': mon_cfg.get('google_cx', ''),
    }


@router.post('/monitor/start')
async def monitor_start():
    if app_state.is_monitoring:
        return {'status': 'error', 'message': 'Мониторинг уже запущен'}
    mon_sources = app_state.profile.get('monitoring', {}).get('sources', [])
    if not [s for s in mon_sources if s.get('enabled', True)]:
        return {'status': 'error', 'message': 'Нет активных источников в мониторинге'}
    t = threading.Thread(target=monitor_worker, daemon=True)
    app_state._monitor_thread = t
    t.start()
    return {'status': 'ok', 'message': 'Мониторинг запущен'}


@router.post('/monitor/stop')
async def monitor_stop():
    app_state.is_monitoring = False
    return {'status': 'ok', 'message': 'Мониторинг остановлен'}


@router.get('/monitor/log')
async def monitor_log(lines: int = 100):
    with app_state._lock:
        return {'logs': app_state.monitor_log[:lines]}


@router.post('/monitor/sources/add')
async def monitor_source_add(data: dict):
    name = data.get('name', '').strip()
    cid = str(data.get('community_id', '')).strip()
    if not name or not cid:
        return {'status': 'error', 'message': 'Укажи название и ID'}
    pid = app_state.active_profile_id
    profile = app_state.config['profiles'][pid]
    sources = profile.setdefault('monitoring', {}).setdefault('sources', [])
    src = {'id': len(sources) + 1, 'name': name, 'community_id': cid, 'enabled': True}
    sources.append(src)
    app_state.save_config()
    return {'status': 'ok', 'source': src}


@router.post('/monitor/sources/remove')
async def monitor_source_remove(data: dict):
    sid = data.get('id')
    pid = app_state.active_profile_id
    sources = app_state.config['profiles'][pid].get('monitoring', {}).get('sources', [])
    before = len(sources)
    sources[:] = [s for s in sources if s.get('id') != sid]
    app_state.save_config()
    return {'status': 'ok', 'removed': before - len(sources)}


@router.post('/monitor/sources/toggle')
async def monitor_source_toggle(data: dict):
    sid = data.get('id')
    pid = app_state.active_profile_id
    sources = app_state.config['profiles'][pid].get('monitoring', {}).get('sources', [])
    for s in sources:
        if s.get('id') == sid:
            s['enabled'] = not s.get('enabled', True)
    app_state.save_config()
    return {'status': 'ok'}


@router.post('/monitor/settings')
async def monitor_settings_save(data: dict):
    """Сохранить настройки новостного мониторинга."""
    pid = app_state.active_profile_id
    mon = app_state.config['profiles'][pid].setdefault('monitoring', {})
    for key in ('check_interval_min', 'catch_up_days', 'max_per_cycle', 'min_views'):
        if key in data:
            mon[key] = int(data[key])
    for key in ('ocr_filter', 'google_image'):
        if key in data:
            mon[key] = bool(data[key])
    for key in ('google_api_key', 'google_cx'):
        if key in data:
            mon[key] = str(data[key]).strip()
    app_state.save_config()
    return {'status': 'ok'}
