# -*- coding: utf-8 -*-
"""VK API utilities."""

import time
import vk_api
from typing import Optional
from requests.exceptions import ConnectionError as ReqConnectionError, Timeout as ReqTimeout

from config import app_state, STORAGE_DIR, logger

# Коды VK API для retry (временные ошибки)
VK_RETRY_CODES = {1, 6, 9, 10}  # unknown, too many requests, flood control, internal server
NETWORK_ERRORS = (ReqConnectionError, ReqTimeout)

VK_POSTPONED_LIMIT = 150


def get_postponed_count(vk, owner_id: str) -> int:
    """Текущее количество отложенных постов (1 API-вызов)."""
    try:
        resp = vk_call_safe(vk.wall.get, owner_id=owner_id, filter='postponed', count=1, offset=0)
        return resp.get('count', 0)
    except Exception as e:
        app_state.add_log(f'Не удалось получить количество отложенных: {e}', 'warning')
        return 0


def get_vk_api(token: str, api_version: str = '5.131'):
    s = vk_api.VkApi(token=token, api_version=api_version)
    return s.get_api()


def vk_call_safe(fn, *args, retries: int = 3, **kwargs):
    """
    Вызов VK API с автоматическим retry при временных ошибках.
    Коды 1, 6, 9, 10 и сетевые ошибки — повтор через 5→10→20 сек.
    """
    delay = 5
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except vk_api.exceptions.ApiError as e:
            code = getattr(e, 'code', 0)
            if code in VK_RETRY_CODES and attempt < retries:
                app_state.add_log(
                    f'VK ошибка {code}, повтор через {delay}с (попытка {attempt + 1}/{retries})',
                    'warning'
                )
                time.sleep(delay)
                delay = min(delay * 2, 30)
            else:
                raise
        except NETWORK_ERRORS as e:
            if attempt < retries:
                app_state.add_log(
                    f'Сеть недоступна, повтор через {delay}с (попытка {attempt + 1}/{retries})',
                    'warning'
                )
                time.sleep(delay)
                delay = min(delay * 2, 30)
            else:
                raise


def send_critical_alert(message: str):
    """Write a critical alert to the local log."""
    app_state.add_log(f'🚨 {message}', 'error')


def normalize_owner_id(community_id: str) -> str:
    return f'-{str(community_id).strip().lstrip("-")}'


def post_passes_filters(text: str, profile: dict) -> bool:
    f = profile.get('filters', {})
    if not f.get('enable_auto_filters'):
        return True
    if f.get('min_content_length', 0) and len(text) < f['min_content_length']:
        return False
    tl = text.lower()
    for kw in f.get('block_keywords', []):
        if kw.lower() in tl:
            return False
    for tag in f.get('block_hashtags', []):
        if tag.lower() in tl:
            return False
    return True


def get_best_photo_url(photo_obj: dict) -> Optional[str]:
    sizes = photo_obj.get('sizes', [])
    if not sizes:
        for key in ('photo_2560', 'photo_1280', 'photo_807', 'photo_604', 'photo_130'):
            if photo_obj.get(key):
                return photo_obj[key]
        return None
    order = {'w': 0, 'z': 1, 'y': 2, 'x': 3, 'r': 4, 'q': 5, 'p': 6, 'o': 7, 'm': 8, 's': 9}
    return sorted(sizes, key=lambda s: order.get(s.get('type', 'z'), 99))[0].get('url')


def validate_vk_tokens() -> dict:
    """
    Проверяет user_token и group_token.
    Возвращает {'user_ok': bool, 'group_ok': bool, 'errors': [str]}.
    """
    vk_cfg = app_state.profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    group_token = vk_cfg.get('group_token', '').strip()
    group_id = vk_cfg.get('group_id', '').strip()
    api_ver = vk_cfg.get('api_version', '5.131')
    errors = []
    user_ok = group_ok = False

    if user_token:
        try:
            vk = get_vk_api(user_token, api_ver)
            vk.users.get()
            user_ok = True
        except vk_api.exceptions.ApiError as e:
            errors.append(f'User Token невалидный (код {getattr(e, "code", 0)}): {e}')
        except Exception as e:
            errors.append(f'User Token: {e}')
    else:
        errors.append('User Token не задан')

    if group_token:
        try:
            vk = get_vk_api(group_token, api_ver)
            if group_id:
                vk.groups.getById(group_id=group_id.lstrip('-'))
            else:
                vk.users.get()
            group_ok = True
        except vk_api.exceptions.ApiError as e:
            errors.append(f'Group Token невалидный (код {getattr(e, "code", 0)}): {e}')
        except Exception as e:
            errors.append(f'Group Token: {e}')
    else:
        errors.append('Group Token не задан')

    return {'user_ok': user_ok, 'group_ok': group_ok, 'errors': errors}


def fetch_last_postponed_from_vk(vk, owner_id: str) -> Optional[int]:
    """
    Перебирает ВСЕ отложенные посты с пагинацией и возвращает
    максимальную дату (Unix timestamp) или None.
    """
    try:
        latest_ts = 0
        offset = 0

        first = vk_call_safe(vk.wall.get, owner_id=owner_id, filter='postponed',
                             count=100, offset=0)
        total = first.get('count', 0)
        items = first.get('items', [])

        if not items:
            app_state.add_log('VK: отложенных постов нет', 'info')
            return None

        for p in items:
            ts = p.get('date', 0)
            if ts > latest_ts:
                latest_ts = ts
        offset += len(items)

        app_state.add_log(f'VK: получаю отложенные... всего {total} постов', 'info')

        while offset < total:
            try:
                resp = vk_call_safe(vk.wall.get, owner_id=owner_id, filter='postponed',
                                    count=100, offset=offset)
                batch = resp.get('items', [])
                if not batch:
                    break
                for p in batch:
                    ts = p.get('date', 0)
                    if ts > latest_ts:
                        latest_ts = ts
                offset += len(batch)
                time.sleep(0.35)
            except Exception as e:
                app_state.add_log(f'VK paginate: {e}', 'warning')
                break

        if latest_ts:
            from datetime import datetime
            human = datetime.fromtimestamp(latest_ts).strftime('%d.%m.%Y %H:%M')
            app_state.add_log(
                f'VK: последний отложенный пост → {human} (просмотрено {offset}/{total})',
                'info'
            )
            return latest_ts
    except Exception as e:
        app_state.add_log(f'VK postponed fetch: {e}', 'warning')
    return None
