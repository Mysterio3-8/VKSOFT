# -*- coding: utf-8 -*-
"""Monitor worker."""

import json
import random
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests as req_lib
import vk_api

from config import app_state
from services.storage import (
    read_monitor_last_seen, save_monitor_last_seen,
    read_monitor_published, add_monitor_published
)
from services.ocr import photo_has_text
from services.google_image import fetch_google_image
from vk.api import get_vk_api, vk_call_safe, normalize_owner_id, get_best_photo_url, post_passes_filters
from vk.upload import upload_photo_from_file


def _monitor_read_last_seen() -> Dict:
    return read_monitor_last_seen()


def _monitor_save_last_seen(data: Dict):
    save_monitor_last_seen(data)


def _monitor_read_published() -> Set:
    return read_monitor_published()


def _monitor_add_published(cid: str, post_id: int):
    add_monitor_published(cid, post_id)


def _monitor_process_post(post: Dict, cid: str, profile: Dict,
                          vk_group, vk_user, gid_num: int, owner_id: str,
                          publish_ts: Optional[int]) -> bool:
    """Обработать и опубликовать один пост из мониторинга."""
    processing = profile.get('processing', {})
    post_id = post.get('id')
    text = post.get('text', '').strip()
    attachments = post.get('attachments', [])
    tags = ' '.join(processing.get('hashtags', []))

    ap_cfg = profile.get('antiplagiaat', {})

    # Photo-only mode
    if processing.get('photo_only', False):
        text = ''

    # Антиплагиат: убрать оригинальный текст (оставить только свои хэштеги)
    if ap_cfg.get('enabled') and ap_cfg.get('clear_text', True):
        text = ''

    # Hashtags
    if tags and (processing.get('add_hashtags') or not text):
        text = f'{text}\n\n{tags}'.strip() if text else tags

    # Скачиваем фото
    photos = [a for a in attachments if a.get('type') == 'photo']
    mon_cfg = profile.get('monitoring', {})

    # Антиплагиат: ограничить количество фото и перемешать
    if ap_cfg.get('enabled'):
        max_ph = int(ap_cfg.get('max_photos', 5))
        if len(photos) > max_ph:
            mode = ap_cfg.get('remove_photo', 'last')
            if mode == 'first':
                photos = photos[1:]
            elif mode == 'random':
                idx = random.randint(0, len(photos) - 1)
                photos = photos[:idx] + photos[idx + 1:]
            else:  # last
                photos = photos[:-1]
            app_state.add_monitor_log(
                f'Антиплагиат: фото {len(photos) + 1} → {len(photos)} (режим: {mode})',
                'info'
            )
        # Перемешиваем фото — уникальный порядок для каждого поста
        random.shuffle(photos)
        app_state.add_monitor_log('Антиплагиат: фото перемешаны', 'info')

    vk_attachments = []

    if photos or mon_cfg.get('google_image'):
        # Временная папка — сразу удаляем после загрузки
        tmp_dir = app_state.photos_dir / f'monitor_{cid}_{post_id}'
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            clean_local: List[Path] = []  # фото прошедшие OCR-фильтр

            for i, a in enumerate(photos):
                url = get_best_photo_url(a.get('photo', {}))
                if not url:
                    continue
                try:
                    resp = req_lib.get(url, timeout=30)
                    resp.raise_for_status()
                    p = tmp_dir / f'photo_{i}.jpg'
                    p.write_bytes(resp.content)

                    # OCR: пропускаем фото с текстом
                    if mon_cfg.get('ocr_filter') and photo_has_text(p):
                        app_state.add_monitor_log(f'OCR: фото {i} содержит текст — пропускаю', 'info')
                        p.unlink(missing_ok=True)
                        continue

                    clean_local.append(p)
                except Exception as e:
                    app_state.add_monitor_log(f'Фото {i}: {e}', 'warning')

            # Если все фото отфильтрованы OCR → пробуем Google Image
            if not clean_local and mon_cfg.get('google_image'):
                query = post.get('text', '').split('\n')[0][:120].strip()
                if not query:
                    query = 'news photo'
                img_data = fetch_google_image(
                    query,
                    mon_cfg.get('google_api_key', ''),
                    mon_cfg.get('google_cx', '')
                )
                if img_data:
                    gp = tmp_dir / 'google_0.jpg'
                    gp.write_bytes(img_data)
                    clean_local.append(gp)
                    app_state.add_monitor_log('Добавлена картинка из Google Images', 'info')

            # Загружаем отфильтрованные фото в VK
            for p in clean_local:
                att = upload_photo_from_file(vk_user, gid_num, p)
                if att:
                    vk_attachments.append(att)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # Видео — прикрепляем по VK ID без повторной загрузки
    if mon_cfg.get('allow_video', False) or profile.get('processing', {}).get('allow_video', False):
        for a in attachments:
            if a.get('type') == 'video':
                vid_obj = a.get('video', {})
                vid_owner = vid_obj.get('owner_id')
                vid_id = vid_obj.get('id')
                access_key = vid_obj.get('access_key', '')
                if vid_owner and vid_id:
                    ref = f'video{vid_owner}_{vid_id}'
                    if access_key:
                        ref += f'_{access_key}'
                    vk_attachments.append(ref)

    # Если были фото но ни одно не загрузилось — пропускаем (не публиковать голые хэштеги)
    if photos and not vk_attachments:
        app_state.add_monitor_log(
            f'Пост {post_id}: фото не загружены — пропускаю', 'error'
        )
        return False

    # Если нет ни текста ни фото/видео — пропускаем
    if not text and not vk_attachments:
        return False

    params: Dict = {'owner_id': owner_id, 'message': text}
    if vk_attachments:
        params['attachments'] = ','.join(vk_attachments)
    if publish_ts:
        params['publish_date'] = publish_ts

    vk_group.wall.post(**params)
    _monitor_add_published(cid, post_id)
    return True


def _monitor_cycle():
    """Один цикл проверки всех источников мониторинга."""
    profile = app_state.profile
    mon_cfg = profile.get('monitoring', {})
    vk_cfg = profile.get('vk', {})

    group_token = vk_cfg.get('group_token', '').strip()
    user_token = vk_cfg.get('user_token', '').strip()
    group_id = vk_cfg.get('group_id', '').strip()
    api_ver = vk_cfg.get('api_version', '5.131')

    if not group_token or not user_token or not group_id:
        app_state.add_monitor_log('VK токены не настроены', 'error')
        return

    vk_group = get_vk_api(group_token, api_ver)
    vk_user = get_vk_api(user_token, api_ver)
    gid_num = int(group_id.strip().lstrip('-'))
    owner_id = f'-{gid_num}'

    sources = [s for s in mon_cfg.get('sources', []) if s.get('enabled', True)]
    max_per_cycle = int(mon_cfg.get('max_per_cycle', 3))
    catch_up_days = int(mon_cfg.get('catch_up_days', 3))
    catch_up_ts = int(time.time()) - catch_up_days * 86400

    last_seen = _monitor_read_last_seen()
    published = _monitor_read_published()

    all_new: List[Dict] = []  # (post, cid) — все новые посты с меткой источника

    # Сбор новых постов из всех источников
    for src in sources:
        if not app_state.is_monitoring:
            return
        cid = str(src.get('community_id', ''))
        src_name = src.get('name', cid)
        since_ts = max(catch_up_ts, last_seen.get(cid, 0))
        owner = normalize_owner_id(cid)

        app_state.add_monitor_log(f'Проверяю: {src_name}')
        try:
            resp = vk_call_safe(vk_user.wall.get, owner_id=owner, count=20, filter='owner')
            items = resp.get('items', [])
        except Exception as e:
            app_state.add_monitor_log(f'{src_name}: {e}', 'error')
            continue

        allow_video = profile.get('processing', {}).get('allow_video', False)
        min_views = int(mon_cfg.get('min_views', 0))
        max_ts = last_seen.get(cid, 0)
        for post in items:
            post_ts = post.get('date', 0)
            post_id = post.get('id')
            # Уже опубликован?
            if f'{cid}_{post_id}' in published:
                continue
            # Слишком старый?
            if post_ts <= since_ts:
                continue
            # Фильтр по просмотрам
            if min_views > 0:
                views_obj = post.get('views', {})
                view_count = views_obj.get('count', 0) if isinstance(views_obj, dict) else 0
                if view_count < min_views:
                    continue
            # Видео пропускаем если не разрешено
            if not allow_video and any(a.get('type') == 'video' for a in post.get('attachments', [])):
                continue
            # Фильтры
            if not post_passes_filters(post.get('text', ''), profile):
                continue
            all_new.append({'post': post, 'cid': cid, 'src_name': src_name})
            if post_ts > max_ts:
                max_ts = post_ts

        if max_ts > last_seen.get(cid, 0):
            last_seen[cid] = max_ts

    _monitor_save_last_seen(last_seen)

    if not all_new:
        app_state.add_monitor_log('Новых постов не найдено')
        return

    app_state.add_monitor_log(f'Найдено новых постов: {len(all_new)}')

    # Сортируем по дате (старые первыми)
    all_new.sort(key=lambda x: x['post'].get('date', 0))

    immediate = all_new[:max_per_cycle]
    postponed_posts = all_new[max_per_cycle:]

    stats = app_state.load_stats()

    # Немедленная публикация (первые max_per_cycle)
    for item in immediate:
        if not app_state.is_monitoring:
            break
        try:
            ok = _monitor_process_post(
                item['post'], item['cid'], profile,
                vk_group, vk_user, gid_num, owner_id,
                publish_ts=None
            )
            if ok:
                stats['published'] = stats.get('published', 0) + 1
                app_state.save_stats(stats)
                app_state.bump_daily_stat('published')
                app_state.add_monitor_log(
                    f'✅ Опубликован: [{item["src_name"]}] ID {item["post"].get("id")}', 'info'
                )
                time.sleep(random.uniform(2, 5))
        except vk_api.exceptions.ApiError as e:
            code = getattr(e, 'code', 0)
            app_state.add_monitor_log(f'VK API ошибка {code}: {e}', 'error')
            app_state.bump_daily_stat('errors')
        except Exception as e:
            app_state.add_monitor_log(f'Ошибка поста: {e}', 'error')
            app_state.bump_daily_stat('errors')

    # Отложенная публикация (остальные)
    if postponed_posts:
        pub_cfg = profile.get('publishing_settings', {})
        delay_min = int(pub_cfg.get('publish_delay_min', 3600))
        delay_max = int(pub_cfg.get('publish_delay_max', delay_min))
        hours_on = pub_cfg.get('publish_hours_enabled', False)
        h_start = int(pub_cfg.get('publish_hours_start', 9))
        h_end = int(pub_cfg.get('publish_hours_end', 22))

        vk_ts = fetch_last_postponed_from_vk(vk_user, owner_id)
        file_ts = read_last_scheduled()
        if vk_ts and file_ts:
            last_ts = max(vk_ts, file_ts)
        elif vk_ts:
            last_ts = vk_ts
        elif file_ts:
            last_ts = file_ts
        else:
            last_ts = int(time.time())
        write_last_scheduled(last_ts)
        next_ts = last_ts + random.randint(delay_min, delay_max)

        for item in postponed_posts:
            if not app_state.is_monitoring:
                break
            try:
                if hours_on:
                    next_ts = adjust_to_publish_window(next_ts, h_start, h_end)
                ok = _monitor_process_post(
                    item['post'], item['cid'], profile,
                    vk_group, vk_user, gid_num, owner_id,
                    publish_ts=next_ts
                )
                if ok:
                    write_last_scheduled(next_ts)
                    next_ts += random.randint(delay_min, delay_max)
                    stats['published'] = stats.get('published', 0) + 1
                    app_state.save_stats(stats)
                    app_state.bump_daily_stat('published')
                    scheduled_label = datetime.fromtimestamp(next_ts).strftime('%d.%m %H:%M')
                    app_state.add_monitor_log(
                        f'🕑 Запланирован: [{item["src_name"]}] → {scheduled_label}', 'info'
                    )
            except vk_api.exceptions.ApiError as e:
                code = getattr(e, 'code', 0)
                app_state.add_monitor_log(f'VK API (отложенный) ошибка {code}: {e}', 'error')
                app_state.bump_daily_stat('errors')
            except Exception as e:
                app_state.add_monitor_log(f'Ошибка отложенного: {e}', 'error')
                app_state.bump_daily_stat('errors')


def fetch_last_postponed_from_vk(vk, owner_id: str):
    """Перебирает ВСЕ отложенные посты с пагинацией и возвращает максимальную дату."""
    try:
        latest_ts = 0
        offset = 0

        first = vk_call_safe(vk.wall.get, owner_id=owner_id, filter='postponed',
                             count=100, offset=0)
        total = first.get('count', 0)
        items = first.get('items', [])

        if not items:
            app_state.add_monitor_log('VK: отложенных постов нет', 'info')
            return None

        for p in items:
            ts = p.get('date', 0)
            if ts > latest_ts:
                latest_ts = ts
        offset += len(items)

        app_state.add_monitor_log(f'VK: получаю отложенные... всего {total} постов', 'info')

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
                app_state.add_monitor_log(f'VK paginate: {e}', 'warning')
                break

        if latest_ts:
            human = datetime.fromtimestamp(latest_ts).strftime('%d.%m.%Y %H:%M')
            app_state.add_monitor_log(
                f'VK: последний отложенный пост → {human} (просмотрено {offset}/{total})',
                'info'
            )
            return latest_ts
    except Exception as e:
        app_state.add_monitor_log(f'VK postponed fetch: {e}', 'warning')
    return None


def adjust_to_publish_window(ts: int, start_h: int, end_h: int) -> int:
    """Push a Unix timestamp into the [start_h, end_h) window."""
    from datetime import datetime as _dt, timedelta
    d = _dt.fromtimestamp(ts)
    if d.hour < start_h:
        d = d.replace(hour=start_h, minute=random.randint(0, 59), second=random.randint(0, 59))
    elif d.hour >= end_h:
        d = (d + timedelta(days=1)).replace(
            hour=start_h, minute=random.randint(0, 59), second=random.randint(0, 59)
        )
    return int(d.timestamp())


def random_delay(min_s: float, max_s: float):
    time.sleep(random.uniform(min_s, max_s))


def monitor_worker():
    """Одна проверка источников → стоп. Работает в фоне (daemon-поток).

    Повторов по интервалу нет: бот запускают на короткое время, одной
    проверки достаточно, чтобы закинуть свежие посты в отложку VK.
    """
    app_state.is_monitoring = True
    app_state.add_monitor_log('🔭 Мониторинг запущен (один проход)', 'info')

    try:
        app_state.monitor_last_check = datetime.now().strftime('%d.%m.%Y %H:%M')
        app_state.add_monitor_log(f'Начало проверки: {app_state.monitor_last_check}')
        try:
            _monitor_cycle()
        except Exception as e:
            app_state.add_monitor_log(f'Ошибка цикла: {e}', 'error')
    except Exception as e:
        app_state.add_monitor_log(f'Критическая ошибка: {e}', 'error')
    finally:
        app_state.is_monitoring = False
        app_state.monitor_last_check = None
        app_state.monitor_next_check = None
        app_state.add_monitor_log('🔴 Мониторинг остановлен', 'warning')


def _watchdog_loop():
    """
    Watchdog-поток: каждую минуту проверяет что monitor_worker жив.
    Если поток завис (is_monitoring=True но поток мёртв) — перезапускает.
    """
    while True:
        time.sleep(60)
        try:
            if app_state.is_monitoring:
                t = app_state._monitor_thread
                if t and not t.is_alive():
                    app_state.add_log('⚠️ Watchdog: мониторинг упал, перезапуск...', 'warning')
                    app_state.is_monitoring = False
                    time.sleep(3)
                    nt = threading.Thread(target=monitor_worker, daemon=True)
                    app_state._monitor_thread = nt
                    nt.start()
        except Exception as e:
            app_state.add_log(f'Watchdog: {e}', 'warning')
