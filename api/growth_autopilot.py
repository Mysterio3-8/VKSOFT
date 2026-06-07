# -*- coding: utf-8 -*-
"""Growth Autopilot API."""

from fastapi import APIRouter

from config import app_state
from services.growth_autopilot import (
    apply_profile_patch,
    build_algorithmic_recommendations,
    build_cycle_dry_run,
    build_readonly_report,
    load_cycle_status,
    load_growth_settings,
    load_report,
    save_report,
    start_cycle,
)

router = APIRouter()


@router.get('/growth-autopilot/status')
async def growth_autopilot_status():
    return {
        'status': 'ok',
        'profile_id': app_state.active_profile_id,
        'settings': load_growth_settings(),
        'report': load_report(),
        'cycle': load_cycle_status(),
    }


@router.post('/growth-autopilot/run')
async def growth_autopilot_run(data: dict = {}):
    settings = load_growth_settings()
    settings.update(data.get('settings') or {})

    run_mode = data.get('run_mode') or settings.get('run_mode', 'dry_run')
    if run_mode not in ('read_only', 'dry_run'):
        run_mode = 'dry_run'

    report = build_readonly_report(settings=settings, save=False)
    report['mode'] = run_mode
    save_report(report)
    return {'status': 'ok', 'report': report}


@router.post('/growth-autopilot/cycle/dry-run')
async def growth_autopilot_cycle_dry_run(data: dict = {}):
    settings = load_growth_settings()
    settings.update(data.get('settings') or {})
    report = build_cycle_dry_run(settings=settings)
    return {'status': 'ok', 'report': report}


@router.post('/growth-autopilot/cycle/start')
async def growth_autopilot_cycle_start(data: dict = {}):
    settings = load_growth_settings()
    settings.update(data.get('settings') or {})
    return start_cycle(settings=settings)


@router.get('/growth-autopilot/cycle/status')
async def growth_autopilot_cycle_status():
    return {'status': 'ok', 'cycle': load_cycle_status()}


@router.post('/growth-autopilot/analyze')
async def growth_autopilot_analyze():
    return build_algorithmic_recommendations()


@router.post('/growth-autopilot/apply-recommendation')
async def growth_autopilot_apply_recommendation(data: dict = {}):
    patch = data.get('patch') or {}
    if not patch:
        return {'status': 'error', 'message': 'Patch is empty'}
    apply_profile_patch(patch)
    return {'status': 'ok', 'message': 'Recommendation applied', 'patch': patch}
