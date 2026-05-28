# -*- coding: utf-8 -*-
"""Dashboard routes."""

from fastapi import APIRouter
from datetime import datetime, timedelta

from config import app_state
from services.storage import read_last_scheduled

router = APIRouter()


@router.get('/dashboard')
async def get_dashboard():
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
