# -*- coding: utf-8 -*-
"""VK photo upload."""

import time
import requests as req_lib
import vk_api

from config import app_state
from vk.api import get_vk_api, vk_call_safe, NETWORK_ERRORS


def download_photos_for_post(community_id: str, post_id: int, photo_attachments: list) -> list:
    """Скачать фото поста локально."""
    from vk.api import get_best_photo_url
    local_paths = []
    post_photos_dir = app_state.photos_dir / f'{community_id}_{post_id}'
    post_photos_dir.mkdir(exist_ok=True)
    for i, attach in enumerate(photo_attachments):
        url = get_best_photo_url(attach.get('photo', {}))
        if not url:
            continue
        for attempt in range(3):
            try:
                resp = req_lib.get(url, timeout=30)
                resp.raise_for_status()
                p = post_photos_dir / f'photo_{i}.jpg'
                p.write_bytes(resp.content)
                local_paths.append(str(p))
                break
            except NETWORK_ERRORS:
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
                else:
                    app_state.add_log(f'Фото {i} поста {post_id}: сеть недоступна', 'warning')
            except Exception as e:
                app_state.add_log(f'Фото {i} поста {post_id}: {e}', 'warning')
                break
    return local_paths


def upload_photo_from_file(vk_user, group_id_num: int, photo_path) -> str:
    """Загрузить фото на стену VK. Retry при сетевых ошибках (3 попытки)."""
    delay = 5
    for attempt in range(3):
        try:
            server = vk_user.photos.getWallUploadServer(group_id=group_id_num)
            up_url = server['upload_url']
            with open(photo_path, 'rb') as fh:
                up_resp = req_lib.post(
                    up_url,
                    files={'photo': (photo_path.name, fh, 'image/jpeg')},
                    timeout=60
                ).json()
            if not up_resp.get('photo'):
                app_state.add_log(f'VK не принял фото: {up_resp}', 'error')
                return None
            saved = vk_user.photos.saveWallPhoto(
                group_id=group_id_num,
                photo=up_resp['photo'],
                server=up_resp['server'],
                hash=up_resp['hash']
            )
            p = saved[0]
            return f"photo{p['owner_id']}_{p['id']}"
        except vk_api.exceptions.ApiError as e:
            app_state.add_log(f'VK API фото: {e}', 'error')
            return None
        except NETWORK_ERRORS:
            if attempt < 2:
                app_state.add_log(
                    f'Загрузка фото: сеть недоступна, повтор через {delay}с',
                    'warning'
                )
                time.sleep(delay)
                delay *= 2
            else:
                app_state.add_log('Загрузка фото: сеть недоступна после 3 попыток', 'error')
                return None
        except Exception as e:
            app_state.add_log(f'Загрузка фото: {e}', 'error')
            return None
    return None
