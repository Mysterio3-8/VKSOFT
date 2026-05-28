# -*- coding: utf-8 -*-
"""External publish worker - publish media from folder to VK."""

import json
import random
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests as req_lib
import vk_api

from config import app_state
from services.storage import write_last_scheduled
from vk.api import get_vk_api, vk_call_safe, normalize_owner_id, send_critical_alert
from vk.upload import upload_photo_from_file


def publish_from_folder(
    folder_path: str,
    text: str = "",
    publish_delay_min: int = 0,
    publish_delay_max: int = 0,
    hours_enabled: bool = False,
    hours_start: int = 9,
    hours_end: int = 22
) -> Dict:
    """
    Публикует медиа из папки в VK.
    
    Args:
        folder_path: Путь к папке с медиа файлами
        text: Текст поста
        publish_delay_min: Минимальная задержка перед публикацией (секунды)
        publish_delay_max: Максимальная задержка перед публикацией (секунды)
        hours_enabled: Ограничивать время публикации по часам
        hours_start: Час начала публикации
        hours_end: Час окончания публикации
    
    Returns:
        Dict с результатами публикации
    """
    try:
        profile = app_state.profile
        vk_cfg = profile.get('vk', {})
        
        group_token = vk_cfg.get('group_token', '').strip()
        user_token = vk_cfg.get('user_token', '').strip()
        group_id = vk_cfg.get('group_id', '').strip()
        api_ver = vk_cfg.get('api_version', '5.131')
        
        if not group_token:
            app_state.add_log('Ошибка: Group Token не задан', 'error')
            return {'status': 'error', 'message': 'Group Token не задан'}
        if not user_token:
            app_state.add_log('Ошибка: User Token не задан', 'error')
            return {'status': 'error', 'message': 'User Token не задан'}
        if not group_id:
            app_state.add_log('Ошибка: Group ID не задан', 'error')
            return {'status': 'error', 'message': 'Group ID не задан'}
        
        vk = get_vk_api(group_token, api_ver)
        vk_user = get_vk_api(user_token, api_ver)
        gid_num = int(group_id.strip().lstrip('-'))
        owner_id = f'-{gid_num}'
        
        # Проверяем существование папки
        folder = Path(folder_path)
        if not folder.exists():
            app_state.add_log(f'Папка не найдена: {folder_path}', 'error')
            return {'status': 'error', 'message': f'Папка не найдена: {folder_path}'}
        
        # Собираем список медиа файлов
        media_files = []
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.gif']:
            media_files.extend(folder.glob(ext))
        
        if not media_files:
            app_state.add_log(f'Нет медиа файлов в папке: {folder_path}', 'warning')
            return {'status': 'error', 'message': 'Нет медиа файлов в папке'}
        
        app_state.add_log(f'Найдено {len(media_files)} файлов для публикации', 'info')
        
        # Загружаем фото
        attachments = []
        uploaded = 0
        failed = 0
        
        for photo_path in media_files[:10]:  # Ограничиваем 10 фото
            try:
                att = upload_photo_from_file(vk_user, gid_num, photo_path)
                if att:
                    attachments.append(att)
                    uploaded += 1
                    app_state.add_log(f'Загружено: {photo_path.name}', 'info')
                else:
                    failed += 1
                    app_state.add_log(f'Не удалось загрузить: {photo_path.name}', 'warning')
            except Exception as e:
                failed += 1
                app_state.add_log(f'Ошибка загрузки {photo_path.name}: {e}', 'error')
        
        if not attachments:
            app_state.add_log('Не удалось загрузить ни одного фото', 'error')
            return {'status': 'error', 'message': 'Не удалось загрузить фото'}
        
        app_state.add_log(f'Успешно загружено: {uploaded}, ошибок: {failed}', 'info')
        
        # Подготавливаем параметры поста
        params = {
            'owner_id': owner_id,
            'message': text,
            'attachments': ','.join(attachments)
        }
        
        # Определяем время публикации
        publish_ts = None
        if publish_delay_min > 0 or publish_delay_max > 0:
            delay = random.randint(publish_delay_min or 0, publish_delay_max or publish_delay_min or 3600)
            publish_ts = int(time.time()) + delay
            
            if hours_enabled:
                from datetime import datetime as dt
                next_time = dt.fromtimestamp(publish_ts)
                if next_time.hour < hours_start:
                    next_time = next_time.replace(hour=hours_start, minute=random.randint(0, 59))
                elif next_time.hour >= hours_end:
                    next_time = next_time.replace(hour=hours_start, minute=random.randint(0, 59))
                    next_time = next_time.replace(day=next_time.day + 1)
                publish_ts = int(next_time.timestamp())
            
            params['publish_date'] = publish_ts
        
        # Публикуем пост
        try:
            vk_call_safe(vk.wall.post, **params)
            
            if publish_ts:
                human_time = datetime.fromtimestamp(publish_ts).strftime('%d.%m.%Y %H:%M')
                app_state.add_log(f'Пост запланирован на {human_time}', 'info')
                write_last_scheduled(publish_ts)
            else:
                app_state.add_log('Пост опубликован успешно', 'info')
            
            return {
                'status': 'ok',
                'message': 'Пост опубликован',
                'photos_uploaded': uploaded,
                'photos_failed': failed,
                'scheduled_time': publish_ts
            }
            
        except vk_api.exceptions.ApiError as e:
            code = getattr(e, 'code', 0)
            if code in (5, 28):
                send_critical_alert(f'Токен VK недействителен (код {code}). Публикация отменена.')
            app_state.add_log(f'Ошибка VK API при публикации: {e}', 'error')
            return {'status': 'error', 'message': str(e)}
        except Exception as e:
            app_state.add_log(f'Ошибка публикации: {e}', 'error')
            return {'status': 'error', 'message': str(e)}
    
    except Exception as e:
        app_state.add_log(f'Критическая ошибка: {e}', 'error')
        return {'status': 'error', 'message': str(e)}


def publish_from_folder_worker(
    folder_path: str,
    text: str = "",
    delay_min: int = 0,
    delay_max: int = 0,
    hours_enabled: bool = False,
    hours_start: int = 9,
    hours_end: int = 22
):
    """
    Воркер для публикации из папки (для запуска в отдельном потоке).
    """
    app_state.is_publishing = True
    try:
        result = publish_from_folder(
            folder_path=folder_path,
            text=text,
            publish_delay_min=delay_min,
            publish_delay_max=delay_max,
            hours_enabled=hours_enabled,
            hours_start=hours_start,
            hours_end=hours_end
        )
        return result
    finally:
        app_state.is_publishing = False
