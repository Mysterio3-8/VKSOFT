# -*- coding: utf-8 -*-
"""Dashboard routes."""

from fastapi import APIRouter
from datetime import datetime, timedelta

from config import app_state
from services.storage import read_last_scheduled

router = APIRouter()


def build_dashboard_payload():
    pending = len(list(app_state.posts_dir.glob('*.json')))
    stats = app_state.load_stats()
    daily_log = app_state.load_daily_log()
    today = datetime.now().strftime('%Y-%m-%d')
    today_s = daily_log.get(today, {'published': 0, 'errors': 0})

    chart_data = []
    for i in range(29, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        label = (datetime.now() - timedelta(days=i)).strftime('%d.%m')
        entry = daily_log.get(d, {})
        chart_data.append({
            'date': d,
            'label': label,
            'published': entry.get('published', 0),
            'errors': entry.get('errors', 0),
        })

    last_ts = read_last_scheduled()
    return {
        'pending': pending,
        'published_total': stats.get('published', 0),
        'published_today': today_s.get('published', 0),
        'errors_today': today_s.get('errors', 0),
        'errors_total': stats.get('failed', 0),
        'is_downloading': app_state.is_downloading,
        'is_publishing': app_state.is_publishing,
        'is_monitoring': app_state.is_monitoring,
        'last_scheduled': datetime.fromtimestamp(last_ts).strftime('%d.%m.%Y %H:%M') if last_ts else None,
        'monitor_next_check': app_state.monitor_next_check,
        'chart_data': chart_data,
    }


def build_growth_dashboard_payload(base, tracker, subscribers, settings, report, cycle):
    profile = app_state.profile
    vk = profile.get('vk', {})
    heatmap = tracker.get('hour_heatmap', []) or []
    hot_hours = [
        item['hour']
        for item in sorted(
            [item for item in heatmap if item.get('posts', 0) > 0],
            key=lambda item: item.get('avg_score', 0),
            reverse=True,
        )[:8]
    ]
    return {
        'status': 'ok',
        'profile': {
            'id': app_state.active_profile_id,
            'name': profile.get('name') or app_state.active_profile_id,
            'group_id': vk.get('group_id', ''),
        },
        'dashboard': base,
        'subscribers': subscribers or {},
        'tracker': tracker or {},
        'growth_autopilot': {
            'settings': settings or {},
            'report': report or {},
            'cycle': cycle or {},
            'hot_hours': hot_hours,
            'smart_24h': True,
        },
    }


@router.get('/dashboard')
async def get_dashboard():
    return build_dashboard_payload()


@router.get('/dashboard/growth')
async def get_dashboard_growth():
    from services.tracker import get_summary
    from services.growth_autopilot import load_cycle_status, load_growth_settings, load_report
    from workers.growth_tasks import get_growth_stats

    base = build_dashboard_payload()
    tracker = get_summary()
    subscribers = get_growth_stats()
    settings = load_growth_settings()
    report = load_report()
    cycle = load_cycle_status()
    return build_growth_dashboard_payload(base, tracker, subscribers, settings, report, cycle)
