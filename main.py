#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VK Post Reposting Bot — Multi-channel FastAPI Backend.

Refactored: split into modules for maintainability.
- config.py: AppState, configuration
- vk/: VK API helpers, upload
- services/: storage, OCR, Google Image
- workers/: download, publish, monitor
- api/: FastAPI routes
"""

import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import BASE_DIR, FRONTEND_DIR, STORAGE_DIR, app_state


# ── Ensure directories exist ─────────────────────────────────────
for _d in [STORAGE_DIR]:
    _d.mkdir(exist_ok=True)


# ── Lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    import threading
    from workers.monitor import _watchdog_loop
    from services.tracker import tracker_loop, bootstrap_from_wall
    from services.cleanup_storage import cleanup_loop
    from workers.growth_tasks import subscriber_tracker_loop
    threading.Thread(target=_watchdog_loop, daemon=True, name='watchdog').start()
    threading.Thread(target=tracker_loop, daemon=True, name='tracker').start()
    threading.Thread(target=bootstrap_from_wall, daemon=True, name='tracker_bootstrap').start()
    threading.Thread(target=cleanup_loop, daemon=True, name='cleanup').start()
    threading.Thread(target=subscriber_tracker_loop, daemon=True, name='sub_tracker').start()
    from services.competitor import competitor_scan_loop
    from services.learning import learning_loop
    threading.Thread(target=competitor_scan_loop, daemon=True, name='competitor_scan').start()
    threading.Thread(target=learning_loop, daemon=True, name='learning').start()
    app_state.add_log('VK Post Bot запущен ✅', 'info')
    yield
    app_state.is_downloading = app_state.is_publishing = False


# ── FastAPI app ──────────────────────────────────────────────────
app = FastAPI(title='VK Post Bot', version='2.0', lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)
app.mount('/static', StaticFiles(directory=str(FRONTEND_DIR)), name='static')


# ── Static routes ────────────────────────────────────────────────
@app.get('/')
async def index():
    return FileResponse(FRONTEND_DIR / 'index.html')


@app.get('/style.css')
async def css():
    return FileResponse(FRONTEND_DIR / 'style.css', media_type='text/css; charset=utf-8')


@app.get('/script.js')
async def js():
    return FileResponse(FRONTEND_DIR / 'script.js', media_type='application/javascript; charset=utf-8')


@app.get('/health')
async def health():
    return {'status': 'ok', 'version': '2.0', 'profile': app_state.active_profile_id}


# ── Include routers ──────────────────────────────────────────────
from api.profiles import router as profiles_router
from api.monitor import router as monitor_router
from api.download import router as download_router
from api.publish import router as publish_router
from api.config import router as config_router
from api.sources import router as sources_router
from api.dashboard import router as dashboard_router
from api.statistics import router as statistics_router
from api.cleanup import router as cleanup_router
from api.logs import router as logs_router
from api.tests import router as tests_router
from api.growth import router as growth_router
from api.media import router as media_router
from api.library import router as library_router
from api.growth_extra import router as growth_extra_router
from api.autopilot import router as autopilot_router
from api.tokens import router as tokens_router
from api.growth_autopilot import router as growth_autopilot_router

app.include_router(profiles_router, prefix='/api')
app.include_router(monitor_router, prefix='/api')
app.include_router(download_router, prefix='/api')
app.include_router(publish_router, prefix='/api')
app.include_router(config_router, prefix='/api')
app.include_router(sources_router, prefix='/api')
app.include_router(dashboard_router, prefix='/api')
app.include_router(statistics_router, prefix='/api')
app.include_router(cleanup_router, prefix='/api')
app.include_router(logs_router, prefix='/api')
app.include_router(tests_router, prefix='/api')
app.include_router(growth_router, prefix='/api')
app.include_router(media_router,   prefix='/api')
app.include_router(library_router,      prefix='/api')
app.include_router(growth_extra_router, prefix='/api')
app.include_router(autopilot_router, prefix='/api')
app.include_router(tokens_router, prefix='/api')
app.include_router(growth_autopilot_router, prefix='/api')
from api.niche_analyzer import router as niche_router
app.include_router(niche_router, prefix='/api')


@app.get('/niche')
async def niche_page():
    return FileResponse(FRONTEND_DIR / 'niche.html')


@app.get('/growth-autopilot')
async def growth_autopilot_page():
    return FileResponse(FRONTEND_DIR / 'growth-autopilot.html')


# ── Main ─────────────────────────────────────────────────────────
if __name__ == '__main__':
    print('\n  VK POST BOT v2.0  —  http://localhost:8000\n')
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000, log_level='warning')
