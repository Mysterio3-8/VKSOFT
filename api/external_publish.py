# -*- coding: utf-8 -*-
"""External publish routes - publish media from folder to VK."""

from fastapi import APIRouter

from config import app_state
from workers.external_publish import publish_from_folder_worker

router = APIRouter()


@router.post('/external_publish/start')
async def start_external_publish(data: dict):
    """
    Начать публикацию медиа из папки.
    
    Параметры:
    - folder_path: Путь к папке с медиа файлами
    - text: Текст поста (опционально)
    - delay_min: Минимальная задержка перед публикацией в секундах (опционально)
    - delay_max: Максимальная задержка перед публикацией в секундах (опционально)
    - hours_enabled: Ограничивать время публикации по часам (опционально)
    - hours_start: Час начала публикации (опционально, по умолчанию 9)
    - hours_end: Час окончания публикации (опционально, по умолчанию 22)
    """
    if app_state.is_publishing:
        return {'status': 'error', 'message': 'Публикация уже идет'}
    
    folder_path = data.get('folder_path', '').strip()
    if not folder_path:
        return {'status': 'error', 'message': 'Укажите путь к папке'}
    
    text = data.get('text', '').strip()
    delay_min = int(data.get('delay_min', 0))
    delay_max = int(data.get('delay_max', 0))
    hours_enabled = data.get('hours_enabled', False)
    hours_start = int(data.get('hours_start', 9))
    hours_end = int(data.get('hours_end', 22))
    
    import threading
    threading.Thread(
        target=publish_from_folder_worker,
        args=(folder_path, text, delay_min, delay_max, hours_enabled, hours_start, hours_end),
        daemon=True
    ).start()
    
    return {'status': 'ok', 'message': 'Публикация запущена'}


@router.post('/external_publish/stop')
async def stop_external_publish():
    """Остановить публикацию."""
    app_state.is_publishing = False
    return {'status': 'ok', 'message': 'Публикация остановлена'}


@router.get('/external_publish/status')
async def external_publish_status():
    """Получить статус публикации."""
    return {
        'is_publishing': app_state.is_publishing
    }
