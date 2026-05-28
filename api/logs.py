# -*- coding: utf-8 -*-
"""Logs routes."""

from fastapi import APIRouter

from config import app_state

router = APIRouter()


@router.get('/logs')
async def get_logs(lines: int = 100):
    return {'status': 'ok', 'logs': app_state.logs[:lines]}


@router.post('/logs/clear')
async def clear_logs():
    app_state.logs = []
    return {'status': 'ok'}
