# -*- coding: utf-8 -*-
"""Фото-воркер: скачать из раздела Фото VK + загрузить в альбом + wall post."""

import json
import random
import time
from pathlib import Path

import requests as req_lib
import vk_api

from config import app_state, STORAGE_DIR
from vk.api import get_vk_api, vk_call_safe, normalize_owner_id, send_critical_alert
from vk.api import NETWORK_ERRORS


# ── Seen IDs (дедупликация) ───────────────────────────────────────

def _seen_file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'seen_photos.json'


def _load_seen() -> set:
    f = _seen_file()
    if f.exists():
        try:
            return set(json.loads(f.read_text(encoding='utf-8')))
        except Exception:
            pass
    return set()


def _add_seen(photo_key: str):
    seen = _load_seen()
    seen.add(photo_key)
    if len(seen) > 30000:
        seen = set(list(seen)[-25000:])
    try:
        f = _seen_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(list(seen)), encoding='utf-8')
    except Exception:
        pass


# ── Альбом группы ────────────────────────────────────────────────

def _get_or_create_album(vk_user, gid_num: int, title: str) -> int:
    """Найти альбом по названию или создать новый. Возвращает album_id."""
    try:
        resp = vk_call_safe(vk_user.photos.getAlbums, owner_id=-gid_num, need_system=0)
        albums = resp.get('items', []) if isinstance(resp, dict) else []
        for a in albums:
            if a.get('title', '').strip().lower() == title.strip().lower():
                return a['id']
        # Создаём новый
        new_album = vk_call_safe(
            vk_user.photos.createAlbum,
            title=title,
            group_id=gid_num,
            privacy_view=['all'],
            privacy_comment=['all'],
        )
        return new_album['id']
    except Exception as e:
        app_state.add_log(f'Альбом: {e}', 'error')
        raise


# ── Скачать одно фото ─────────────────────────────────────────────

def _get_best_url(photo: dict) -> str:
    sizes = photo.get('sizes', [])
    if not sizes:
        for key in ('photo_2560', 'photo_1280', 'photo_807', 'photo_604'):
            if photo.get(key):
                return photo[key]
        return ''
    order = {'w': 0, 'z': 1, 'y': 2, 'x': 3, 'r': 4, 'q': 5, 'p': 6, 'o': 7}
    best = sorted(sizes, key=lambda s: order.get(s.get('type', 'z'), 99))[0]
    return best.get('url', '')


def _download_file(url: str, dest: Path) -> bool:
    for attempt in range(3):
        try:
            r = req_lib.get(url, timeout=30, stream=True)
            r.raise_for_status()
            dest.write_bytes(r.content)
            return True
        except NETWORK_ERRORS:
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
        except Exception:
            break
    return False


# ── Загрузить фото в альбом VK ────────────────────────────────────

def _upload_to_album(vk_user, gid_num: int, album_id: int, photo_path: Path):
    """Загрузить файл в альбом группы. Возвращает 'photoOWNER_ID' или None."""
    server = vk_call_safe(
        vk_user.photos.getUploadServer,
        group_id=gid_num,
        album_id=album_id,
    )
    upload_url = server['upload_url']
    with open(photo_path, 'rb') as fh:
        resp = req_lib.post(
            upload_url,
            files={'file1': (photo_path.name, fh, 'image/jpeg')},
            timeout=60,
        ).json()

    saved = vk_call_safe(
        vk_user.photos.save,
        server=resp['server'],
        photos_list=resp['photos_list'],
        hash=resp['hash'],
        group_id=gid_num,
        album_id=album_id,
    )
    if saved:
        p = saved[0]
        return f"photo{p['owner_id']}_{p['id']}"
    return None


# ── Основная логика скачивания ────────────────────────────────────

def _download_photos_source(community_id: str, count: int):
    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    ph_cfg = profile.get('photos_settings', {})
    user_token = vk_cfg.get('user_token', '').strip()
    api_ver = vk_cfg.get('api_version', '5.131')

    if not user_token:
        app_state.add_log('Фото: User Token не задан', 'error')
        return

    vk = get_vk_api(user_token, api_ver)
    owner_id = normalize_owner_id(community_id)
    delay_min = float(ph_cfg.get('delay_min', 1))
    delay_max = float(ph_cfg.get('delay_max', 3))

    seen = _load_seen()
    downloaded = skipped = 0
    offset = 0

    app_state.add_log(f'Фото: загрузка {count} из {owner_id}', 'info')

    while downloaded < count and app_state.is_downloading_photos:
        try:
            resp = vk_call_safe(
                vk.photos.getAll,
                owner_id=owner_id,
                count=min(200, count - downloaded),
                offset=offset,
                extended=1,
                no_service_albums=1,
            )
        except vk_api.exceptions.ApiError as e:
            code = getattr(e, 'code', 0)
            app_state.add_log(f'Фото VK API {code}: {e}', 'error')
            if code in (5, 28):
                send_critical_alert(f'Токен недействителен ({code}). Фото остановлено.')
                app_state.is_downloading_photos = False
            break

        items = resp.get('items', []) if isinstance(resp, dict) else []
        if not items:
            app_state.add_log(f'Фото {owner_id}: больше нет', 'info')
            break

        for photo in items:
            if not app_state.is_downloading_photos or downloaded >= count:
                break

            photo_id = photo.get('id')
            key = f'{community_id}_{photo_id}'
            if key in seen:
                skipped += 1
                continue

            url = _get_best_url(photo)
            if not url:
                skipped += 1
                continue

            # Скачиваем файл
            dest = app_state.photo_files_dir / f'{key}.jpg'
            if not _download_file(url, dest):
                skipped += 1
                continue

            # Сохраняем метаданные
            meta = {
                'id': photo_id,
                'owner_id': photo.get('owner_id'),
                'text': photo.get('text', ''),
                'date': photo.get('date', 0),
                '_local_file': str(dest),
                '_source_cid': community_id,
                '_url': url,
            }
            meta_file = app_state.photos_queue_dir / f'{key}.json'
            meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
            _add_seen(key)

            downloaded += 1
            if downloaded % 10 == 0 or downloaded == 1:
                app_state.add_log(f'Фото [{owner_id}] {downloaded}/{count}', 'info')

            time.sleep(random.uniform(delay_min, delay_max))

        offset += len(items)
        if len(items) < 200:
            break

    app_state.add_log(f'Фото [{owner_id}]: {downloaded} скачано, {skipped} пропущено', 'info')


def download_photos_worker():
    profile = app_state.profile
    sources = [s for s in profile.get('sources', []) if s.get('enabled')]
    ph_cfg = profile.get('photos_settings', {})
    count = int(ph_cfg.get('photos_download_per_run', ph_cfg.get('photos_per_run', 50)))

    if not sources:
        app_state.add_log('Фото: нет активных источников', 'warning')
        app_state.is_downloading_photos = False
        return
    try:
        from services.seasonality import order_sources_by_season
        from services.source_quality import is_source_blocked
        sources = order_sources_by_season(sources)
        for src in sources:
            if not app_state.is_downloading_photos:
                break
            cid = str(src.get('community_id', ''))
            if is_source_blocked(cid):
                app_state.add_log(f'Фото: источник {src.get("name", cid)} в стоп-листе — пропускаю', 'info')
                continue
            app_state.add_log(f'Фото: источник {src.get("name", cid)}', 'info')
            _download_photos_source(cid, count)
    except Exception as e:
        app_state.add_log(f'Фото загрузка: {e}', 'error')
    finally:
        app_state.is_downloading_photos = False


# ── Публикация ────────────────────────────────────────────────────

def publish_photos_worker(count: int):
    try:
        profile = app_state.profile
        vk_cfg = profile.get('vk', {})
        ph_cfg = profile.get('photos_settings', {})

        user_token  = vk_cfg.get('user_token', '').strip()
        group_token = vk_cfg.get('group_token', '').strip()
        group_id    = vk_cfg.get('group_id', '').strip()
        api_ver     = vk_cfg.get('api_version', '5.131')

        if not user_token or not group_token or not group_id:
            app_state.add_log('Фото публикация: токены не заданы', 'error')
            return

        vk_user  = get_vk_api(user_token, api_ver)
        vk_group = get_vk_api(group_token, api_ver)
        gid_num  = int(group_id.lstrip('-'))
        owner_id = f'-{gid_num}'

        album_title = ph_cfg.get('album_title', 'Фото')
        create_wall = ph_cfg.get('create_wall_post', True)
        delay_min   = int(ph_cfg.get('publish_delay_min', 3600))
        delay_max   = int(ph_cfg.get('publish_delay_max', 7200))
        if delay_min > delay_max:
            delay_min, delay_max = delay_max, delay_min

        # Получить/создать альбом
        try:
            album_id = _get_or_create_album(vk_user, gid_num, album_title)
            app_state.add_log(f'Фото: альбом "{album_title}" id={album_id}', 'info')
        except Exception as e:
            app_state.add_log(f'Фото: не удалось получить альбом: {e}', 'error')
            return

        # Очередь
        queue = sorted(app_state.photos_queue_dir.glob('*.json'))[:count]
        if not queue:
            app_state.add_log('Фото: очередь пуста', 'warning')
            return

        app_state.add_log(f'Фото: публикация {len(queue)} фото', 'info')
        published = failed = 0
        from services.storage import read_last_scheduled, write_last_scheduled
        next_ts = _get_next_ts(delay_min, delay_max)

        for meta_file in queue:
            if not app_state.is_publishing_photos:
                break
            try:
                meta = json.loads(meta_file.read_text(encoding='utf-8'))
                photo_path = Path(meta.get('_local_file', ''))

                if not photo_path.exists():
                    app_state.add_log(f'Фото файл не найден: {photo_path.name}', 'warning')
                    meta_file.unlink(missing_ok=True)
                    from services.publish_log import log_publish_event
                    log_publish_event(media_type='photos', status='failed', extra={'reason': 'file_not_found'})
                    continue

                # Антиплагиат + вотермарка — единый пайплайн для любого медиа
                try:
                    from services.media_pipeline import process_photos
                    if process_photos([str(photo_path)], profile):
                        app_state.add_log(f'Фото: антиплагиат применён к {photo_path.name}', 'info')
                except Exception as e:
                    app_state.add_log(f'Фото: обработка {e}', 'warning')

                att = _upload_to_album(vk_user, gid_num, album_id, photo_path)
                if not att:
                    app_state.add_log('Фото: не загружено в альбом', 'error')
                    failed += 1
                    from services.publish_log import log_publish_event
                    log_publish_event(media_type='photos', status='failed', extra={'reason': 'upload_failed'})
                    continue

                if create_wall:
                    from services.content_library import compose_caption_with_meta
                    base_text = meta.get('text', '')
                    processing = profile.get('processing', {})
                    text, caption_meta = compose_caption_with_meta(
                        base_text,
                        add_tags=True,
                        profile_tags=processing.get('hashtags', []),
                        add_profile_tags=processing.get('add_hashtags') or not base_text,
                    )

                    now = int(time.time())
                    if next_ts <= now:
                        next_ts = now + random.randint(delay_min, delay_max)

                    params = {
                        'owner_id': owner_id,
                        'message': text,
                        'attachments': att,
                        'publish_date': next_ts,
                    }
                    result = vk_call_safe(vk_group.wall.post, **params)
                    vk_post_id = result.get('post_id') if isinstance(result, dict) else None
                    from services.publish_log import log_publish_event
                    log_publish_event(
                        media_type='photos',
                        status='success',
                        post_id=vk_post_id,
                        publish_date=next_ts,
                    )
                    if vk_post_id:
                        try:
                            from services.tracker import track as _track
                            _track(
                                vk_post_id, owner_id, str(meta.get('owner_id', '')),
                                published_at=next_ts,
                                caption_category=caption_meta.get('caption_category', ''),
                                caption_text=caption_meta.get('caption_text', ''),
                                caption_id=caption_meta.get('caption_id', ''),
                                media_type='photo',
                            )
                        except Exception:
                            pass
                    from datetime import datetime
                    app_state.add_log(
                        f'Фото: запланировано → {datetime.fromtimestamp(next_ts).strftime("%d.%m %H:%M")}',
                        'info'
                    )
                    write_last_scheduled(next_ts)
                    next_ts += random.randint(delay_min, delay_max)

                # Cleanup
                photo_path.unlink(missing_ok=True)
                meta_file.unlink(missing_ok=True)
                published += 1

            except vk_api.exceptions.ApiError as e:
                code = getattr(e, 'code', 0)
                app_state.add_log(f'Фото VK API {code}: {e}', 'error')
                failed += 1
                if code in (5, 28):
                    app_state.is_publishing_photos = False
                    break
            except Exception as e:
                app_state.add_log(f'Фото пост ошибка: {e}', 'error')
                failed += 1

        app_state.add_log(f'Фото: {published} опубликовано, {failed} ошибок', 'info')
        if published > 0 and profile.get('storage_cleanup', {}).get('clean_orphans_after_run', True):
            try:
                from services.cleanup_storage import cleanup_junk
                junk = cleanup_junk()
                removed = sum(int(v or 0) for v in junk.values())
                if removed:
                    app_state.add_log(f'Фото автоочистка: удалено {removed} остаточных файлов/папок', 'info')
            except Exception as e:
                app_state.add_log(f'Фото автоочистка: {e}', 'warning')

    except Exception as e:
        app_state.add_log(f'Фото публикация критическая ошибка: {e}', 'error')
    finally:
        app_state.is_publishing_photos = False


def _get_next_ts(delay_min: int, delay_max: int, media_type: str = 'photos') -> int:
    from services.slot_scheduler import reserve_slot
    return reserve_slot(media_type, delay_min, delay_max)


def queue_count() -> int:
    try:
        return len(list(app_state.photos_queue_dir.glob('*.json')))
    except Exception:
        return 0
