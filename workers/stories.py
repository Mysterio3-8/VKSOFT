# -*- coding: utf-8 -*-
"""Stories worker — постить фото/видео в VK Stories из лучших постов."""

import json
import random
import time
from pathlib import Path

import requests as req_lib
import vk_api

from config import app_state, STORAGE_DIR
from vk.api import get_vk_api, vk_call_safe, NETWORK_ERRORS


def _seen_stories_file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'stories_posted.json'


def _load_seen() -> set:
    f = _seen_stories_file()
    if f.exists():
        try:
            return set(json.loads(f.read_text(encoding='utf-8')))
        except Exception:
            pass
    return set()


def _add_seen(key: str):
    seen = _load_seen()
    seen.add(key)
    if len(seen) > 1000:
        seen = set(list(seen)[-800:])
    try:
        f = _seen_stories_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(list(seen)), encoding='utf-8')
    except Exception:
        pass


def _get_best_photo_for_story() -> Path | None:
    """Найти лучшее фото из папки photo_files (недавно скачанные)."""
    files = sorted(
        app_state.photo_files_dir.glob('*.jpg'),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )
    seen = _load_seen()
    for f in files[:50]:
        if f.stem not in seen:
            return f
    return files[0] if files else None


def _get_best_video_for_story() -> Path | None:
    """Найти видео для Stories из очереди клипов или видео."""
    seen = _load_seen()
    for files_dir in [app_state.clip_files_dir, app_state.video_files_dir]:
        files = sorted(
            files_dir.glob('*.mp4'),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for f in files[:20]:
            if f.stem not in seen:
                return f
    return None


def post_photo_story(photo_path: Path) -> bool:
    """Опубликовать одно фото в Stories группы."""
    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    group_id   = vk_cfg.get('group_id', '').strip()
    api_ver    = vk_cfg.get('api_version', '5.131')

    if not user_token or not group_id:
        app_state.add_log('Stories: токены не заданы', 'error')
        return False

    vk = get_vk_api(user_token, api_ver)
    gid_num = int(group_id.lstrip('-'))

    try:
        server = vk_call_safe(
            vk.stories.getPhotoUploadServer,
            add_to_news=1,
            group_id=gid_num,
        )
        upload_url = server.get('upload_url')
        if not upload_url:
            app_state.add_log('Stories: нет upload_url', 'error')
            return False

        with open(photo_path, 'rb') as fh:
            up_resp = req_lib.post(
                upload_url,
                files={'file': (photo_path.name, fh, 'image/jpeg')},
                timeout=60,
            ).json()

        result = vk_call_safe(
            vk.stories.save,
            upload_results=up_resp.get('upload_result', ''),
        )
        if result:
            app_state.add_log(f'Stories: ✅ опубликовано фото {photo_path.name}', 'info')
            _add_seen(photo_path.stem)
            return True
        return False

    except vk_api.exceptions.ApiError as e:
        app_state.add_log(f'Stories VK API {getattr(e,"code",0)}: {e}', 'error')
        return False
    except Exception as e:
        app_state.add_log(f'Stories ошибка: {e}', 'error')
        return False


def post_video_story(video_path: Path) -> bool:
    """Опубликовать видео в Stories группы."""
    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    group_id   = vk_cfg.get('group_id', '').strip()
    api_ver    = vk_cfg.get('api_version', '5.131')

    if not user_token or not group_id:
        app_state.add_log('Stories: токены не заданы', 'error')
        return False

    vk = get_vk_api(user_token, api_ver)
    gid_num = int(group_id.lstrip('-'))

    try:
        server = vk_call_safe(
            vk.stories.getVideoUploadServer,
            add_to_news=1,
            group_id=gid_num,
        )
        upload_url = server.get('upload_url')
        if not upload_url:
            app_state.add_log('Stories: нет upload_url для видео', 'error')
            return False

        with open(video_path, 'rb') as fh:
            up_resp = req_lib.post(
                upload_url,
                files={'video_file': (video_path.name, fh, 'video/mp4')},
                timeout=300,
            ).json()

        result = vk_call_safe(
            vk.stories.save,
            upload_results=up_resp.get('upload_result', ''),
        )
        if result:
            app_state.add_log(f'Stories: ✅ опубликовано видео {video_path.name}', 'info')
            _add_seen(video_path.stem)
            return True
        return False

    except vk_api.exceptions.ApiError as e:
        app_state.add_log(f'Stories VK API {getattr(e,"code",0)}: {e}', 'error')
        return False
    except Exception as e:
        app_state.add_log(f'Stories видео ошибка: {e}', 'error')
        return False


def auto_post_story_worker(media_type: str = 'photo'):
    """Найти лучший медиафайл и запостить в Stories."""
    try:
        if media_type == 'video':
            app_state.add_log('Stories: ищу видео для публикации...', 'info')
            video = _get_best_video_for_story()
            if not video:
                app_state.add_log('Stories: нет видео (скачай клипы/видео в Медиа)', 'warning')
                return
            ok = post_video_story(video)
        else:
            app_state.add_log('Stories: ищу фото для публикации...', 'info')
            photo = _get_best_photo_for_story()
            if not photo:
                app_state.add_log('Stories: нет доступных фото (скачай фото в разделе Медиа)', 'warning')
                return
            ok = post_photo_story(photo)
        if not ok:
            app_state.add_log('Stories: не удалось опубликовать', 'error')
    except Exception as e:
        app_state.add_log(f'Stories worker: {e}', 'error')
