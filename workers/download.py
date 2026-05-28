# -*- coding: utf-8 -*-
"""Download workers."""

import json
import random
import time
from pathlib import Path
from typing import Dict

import requests as req_lib
import vk_api

from config import app_state
from services.storage import (
    read_offsets, save_offset, clear_offset,
    read_last_scheduled, write_last_scheduled
)
from vk.api import get_vk_api, vk_call_safe, normalize_owner_id, get_best_photo_url, send_critical_alert
from vk.upload import download_photos_for_post, upload_photo_from_file


def _download_source(community_id: str, count: int):
    """Core download logic — caller manages is_downloading flag."""
    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    dl_cfg = profile.get('download_settings', {})
    user_token = vk_cfg.get('user_token', '').strip()
    api_ver = vk_cfg.get('api_version', '5.131')

    if not user_token:
        app_state.add_log('Ошибка: VK User Token не задан', 'error')
        return

    vk = get_vk_api(user_token, api_ver)
    owner_id = normalize_owner_id(community_id)
    delay_min = float(dl_cfg.get('delay_min', 1))
    delay_max = float(dl_cfg.get('delay_max', 3))
    check_dup = dl_cfg.get('check_duplicates', True)

    allow_video = profile.get('processing', {}).get('allow_video', False)

    # ── Пункт 1: фильтр по вовлечённости ─────────────────────────
    eng_cfg = profile.get('engagement', {})
    eng_enabled   = eng_cfg.get('enabled', False)
    eng_min_ratio = float(eng_cfg.get('min_ratio', 0.5))  # % лайков от просмотров
    eng_min_likes = int(eng_cfg.get('min_likes', 0))

    # ── Пункт 6: phash дедупликация ──────────────────────────────
    phash_cfg = profile.get('phash', {})
    phash_enabled   = phash_cfg.get('enabled', False)
    phash_threshold = int(phash_cfg.get('threshold', 10))

    saved_offset = read_offsets().get(str(community_id), 0)
    if saved_offset:
        app_state.add_log(f'Продолжаю с позиции {saved_offset}', 'info')
    offset = saved_offset

    app_state.add_log(f'Загрузка {count} постов из {owner_id}', 'info')
    app_state.download_progress = {'current': 0, 'total': count, 'source': str(community_id)}

    downloaded = skipped = 0
    # Для статистики источника (пункт 4)
    total_likes = total_views = stat_posts = 0

    while downloaded < count and app_state.is_downloading:
        batch = min(100, count - downloaded)
        try:
            resp = vk_call_safe(vk.wall.get, owner_id=owner_id, count=batch, offset=offset, filter='owner')
        except vk_api.exceptions.ApiError as e:
            code = getattr(e, 'code', 0)
            msg = f'VK API (загрузка) ошибка {code}: {e}'
            app_state.add_log(msg, 'error')
            if code in (5, 28):
                send_critical_alert(f'Токен VK недействителен (код {code}). Загрузка остановлена.')
                app_state.is_downloading = False
            break

        items = resp.get('items', [])
        if not items:
            app_state.add_log(f'{owner_id}: постов больше нет', 'info')
            clear_offset(str(community_id))
            break

        for post in items:
            if not app_state.is_downloading or downloaded >= count:
                break

            post_id = post.get('id')
            text = post.get('text', '')
            attachments = post.get('attachments', [])

            has_video = any(a.get('type') == 'video' for a in attachments)
            photos = [a for a in attachments if a.get('type') == 'photo']
            videos = [a for a in attachments if a.get('type') == 'video'] if allow_video else []

            if has_video and not allow_video:
                skipped += 1
                continue

            if not photos and not videos:
                skipped += 1
                continue

            if not post_passes_filters(text, profile):
                skipped += 1
                continue

            # ── Пункт 1: фильтр по вовлечённости ─────────────────
            if eng_enabled:
                likes = post.get('likes', {}).get('count', 0)
                views = post.get('views', {}).get('count', 1)
                ratio = likes / max(views, 1) * 100
                if eng_min_likes > 0 and likes < eng_min_likes:
                    skipped += 1
                    continue
                if eng_min_ratio > 0 and ratio < eng_min_ratio:
                    skipped += 1
                    continue

            fname = app_state.posts_dir / f'{community_id}_{post_id}.json'
            if check_dup and fname.exists():
                continue

            local_photos = download_photos_for_post(community_id, post_id, photos) if photos else []
            if not local_photos and not videos:
                skipped += 1
                continue

            # ── Пункт 6: phash дедупликация ──────────────────────
            if phash_enabled and local_photos:
                from services.phash import is_duplicate, add_to_cache
                first_photo = Path(local_photos[0])
                if is_duplicate(first_photo, phash_threshold):
                    app_state.add_log(f'Phash: пост {post_id} — дубликат, пропускаю', 'info')
                    # Удаляем скачанные фото
                    for pp in local_photos:
                        try:
                            Path(pp).unlink(missing_ok=True)
                        except Exception:
                            pass
                    skipped += 1
                    continue
                # Добавляем первое фото в кэш
                add_to_cache(first_photo, f'{community_id}_{post_id}')

            post['_local_photos'] = local_photos

            if videos:
                vk_videos = []
                for v in videos:
                    vid_obj = v.get('video', {})
                    vid_owner = vid_obj.get('owner_id')
                    vid_id = vid_obj.get('id')
                    access_key = vid_obj.get('access_key', '')
                    if vid_owner and vid_id:
                        ref = f'video{vid_owner}_{vid_id}'
                        if access_key:
                            ref += f'_{access_key}'
                        vk_videos.append(ref)
                if vk_videos:
                    post['_vk_videos'] = vk_videos

            fname.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding='utf-8')

            # Накапливаем для рейтинга источника
            total_likes += post.get('likes', {}).get('count', 0)
            total_views += post.get('views', {}).get('count', 0)
            stat_posts += 1

            downloaded += 1
            app_state.download_progress['current'] = downloaded
            if downloaded % 10 == 0 or downloaded == 1:
                app_state.add_log(f'[{owner_id}] {downloaded}/{count} сохранено', 'info')

        offset += len(items)
        save_offset(str(community_id), offset)
        random_delay(delay_min, delay_max)

    if app_state.is_downloading:
        clear_offset(str(community_id))

    # ── Пункт 4: обновить рейтинг источника ──────────────────────
    if stat_posts > 0:
        from api.growth import update_source_stat
        avg_likes = total_likes / stat_posts
        avg_views = total_views / max(stat_posts, 1)
        update_source_stat(str(community_id), stat_posts, avg_likes, avg_views)

    app_state.add_log(f'[{owner_id}] Готово: {downloaded} скачано, {skipped} пропущено', 'info')


def download_worker(community_id: str, count: int):
    try:
        _download_source(community_id, count)
    except Exception as e:
        app_state.add_log(f'Ошибка загрузки: {e}', 'error')
    finally:
        app_state.is_downloading = False


def download_all_worker():
    profile = app_state.profile
    sources = [s for s in profile.get('sources', []) if s.get('enabled')]
    if not sources:
        app_state.add_log('Нет активных источников', 'warning')
        app_state.is_downloading = False
        return
    count = profile.get('download_settings', {}).get('posts_to_download', 100)
    app_state.add_log(f'Пакетная загрузка: {len(sources)} источников × {count}', 'info')
    try:
        for i, src in enumerate(sources, 1):
            if not app_state.is_downloading:
                break
            cid = str(src.get('community_id', ''))
            app_state.add_log(f'Источник {i}/{len(sources)}: {src.get("name", cid)}', 'info')
            _download_source(cid, count)
        total = len(list(app_state.posts_dir.glob('*.json')))
        app_state.add_log(f'Все источники обработаны. В очереди: {total}', 'info')
    except Exception as e:
        app_state.add_log(f'Пакетная загрузка: {e}', 'error')
    finally:
        app_state.is_downloading = False


def random_delay(min_s: float, max_s: float):
    time.sleep(random.uniform(min_s, max_s))


def adjust_to_publish_window(ts: int, start_h: int, end_h: int) -> int:
    from datetime import datetime as _dt, timedelta
    d = _dt.fromtimestamp(ts)
    if d.hour < start_h:
        d = d.replace(hour=start_h, minute=random.randint(0, 59), second=random.randint(0, 59))
    elif d.hour >= end_h:
        d = (d + timedelta(days=1)).replace(
            hour=start_h, minute=random.randint(0, 59), second=random.randint(0, 59)
        )
    return int(d.timestamp())


def post_passes_filters(text: str, profile: Dict) -> bool:
    from vk.api import post_passes_filters as _pf
    return _pf(text, profile)
