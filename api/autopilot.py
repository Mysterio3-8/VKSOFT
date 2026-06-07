# -*- coding: utf-8 -*-
"""Autopilot API. Safe by default: dry-run unless live is explicitly enabled."""

import threading

from fastapi import APIRouter

from config import app_state
from services.autopilot import (
    apply_growth_defaults,
    build_report,
    get_status,
    run_live_once,
)

router = APIRouter()


@router.get('/autopilot/status')
async def autopilot_status():
    return get_status()


@router.post('/autopilot/apply_defaults')
async def autopilot_apply_defaults():
    try:
        patch = apply_growth_defaults()
        return {
            'status': 'ok',
            'message': 'Безопасные дефолты применены. Live автопилота остался выключен.',
            'patch': patch,
        }
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.post('/autopilot/run_once')
async def autopilot_run_once(data: dict = {}):
    try:
        dry_run = bool(data.get('dry_run', True))
        if not dry_run and not app_state.profile.get('autopilot', {}).get('live_enabled', False):
            dry_run = True
        report = build_report(dry_run=dry_run)
        return {'status': 'ok', 'message': 'Dry-run отчет готов' if dry_run else 'Live отчет готов', 'report': report}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def _autopilot_thread(dry_run: bool):
    app_state.is_autopilot = True
    try:
        if dry_run:
            build_report(dry_run=True)
        else:
            run_live_once()
    finally:
        app_state.is_autopilot = False


@router.post('/autopilot/start')
async def autopilot_start(data: dict = {}):
    if app_state.is_autopilot:
        return {'status': 'error', 'message': 'Автопилот уже работает'}

    requested_live = not bool(data.get('dry_run', True))
    live_allowed = bool(app_state.profile.get('autopilot', {}).get('live_enabled', False))
    dry_run = True if not requested_live or not live_allowed else False

    t = threading.Thread(target=_autopilot_thread, args=(dry_run,), daemon=True, name='autopilot')
    app_state._autopilot_thread = t
    t.start()

    if dry_run:
        return {'status': 'ok', 'message': 'Автопилот запущен в dry-run: публикаций не будет'}
    return {'status': 'ok', 'message': 'Автопилот запущен в live-режиме'}


@router.post('/autopilot/stop')
async def autopilot_stop():
    app_state.is_autopilot = False
    app_state.add_log('Автопилот остановлен', 'warning')
    return {'status': 'ok', 'message': 'Автопилот остановлен'}
