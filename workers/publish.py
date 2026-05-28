# -*- coding: utf-8 -*-
"""Publish worker."""

import json
import random
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

import requests as req_lib
import vk_api

from config import app_state
from services.storage import read_last_scheduled, write_last_scheduled
from services.ocr import photo_has_text
from services.google_image import fetch_google_image
from services.polls import create_poll
from vk.api import get_vk_api, vk_call_safe, normalize_owner_id, fetch_last_postponed_from_vk, get_postponed_count, VK_POSTPONED_LIMIT, send_critical_alert
from vk.upload import upload_photo_from_file


def publish_worker(count: int):
    try:
        profile = app_state.profile
        vk_cfg = profile.get('vk', {})
        pub_cfg = profile.get('publishing_settings', {})
        processing = profile.get('processing', {})

        group_token = vk_cfg.get('group_token', '').strip()
        user_token = vk_cfg.get('user_token', '').strip()
        group_id = vk_cfg.get('group_id', '').strip()
        api_ver = vk_cfg.get('api_version', '5.131')

        if not group_token:
            app_state.add_log('Ошибка: Group Token не задан', 'error')
            return
        if not user_token:
            app_state.add_log('Ошибка: User Token не задан', 'error')
            return
        if not group_id:
            app_state.add_log('Ошибка: Group ID не задан', 'error')
            return

        vk = get_vk_api(group_token, api_ver)
        vk_user = get_vk_api(user_token, api_ver)
        gid_num = int(group_id.strip().lstrip('-'))
        owner_id = f'-{gid_num}'

        postponed = pub_cfg.get('postponed_enabled', True)
        delay_min = int(pub_cfg.get('publish_delay_min', 3600))
        delay_max = int(pub_cfg.get('publish_delay_max', delay_min))
        # Ensure delay_min <= delay_max to avoid empty range errors in randint/randrange
        if delay_min > delay_max:
            app_state.add_log(
                f'Исправлены настройки задержки: publish_delay_min ({delay_min}) > publish_delay_max ({delay_max}), значения поменяны местами',
                'warning'
            )
            delay_min, delay_max = delay_max, delay_min
        hours_on = pub_cfg.get('publish_hours_enabled', False)
        h_start = int(pub_cfg.get('publish_hours_start', 9))
        h_end = int(pub_cfg.get('publish_hours_end', 22))

        # ── Пункт 2: пиковые часы ────────────────────────────────
        peak_cfg = profile.get('peak_hours', {})
        peak_on = peak_cfg.get('enabled', False)
        peak_hours_list = peak_cfg.get('hours', [])

        polls_cfg = profile.get('polls', {})

        post_files = sorted(app_state.posts_dir.glob('*.json'))[:count]
        if not post_files:
            app_state.add_log('Нет постов для публикации', 'warning')
            return

        app_state.add_log(f'Публикация {len(post_files)} постов в {owner_id}', 'info')
        stats = app_state.load_stats()

        # Determine first publish time
        if postponed:
            file_ts = read_last_scheduled()
            ts_file = app_state.last_scheduled_file

            # Throttle VK API sync: skip if local file was updated less than 1 hour ago.
            # fetch_last_postponed_from_vk uses user_token and makes multiple wall.get calls
            # which can trigger rate limits and account restrictions.
            file_age = (time.time() - ts_file.stat().st_mtime) if ts_file.exists() else float('inf')
            if file_age > 3600:
                app_state.add_log('Синхронизация с VK: ищу последний отложенный пост...', 'info')
                vk_ts = fetch_last_postponed_from_vk(vk_user, owner_id)
            else:
                vk_ts = None
                app_state.add_log(
                    f'Синхронизация пропущена (файл обновлён {int(file_age // 60)} мин назад, используем локальный)',
                    'info'
                )

            if vk_ts and file_ts:
                last_ts = max(vk_ts, file_ts)
                src = 'VK' if vk_ts >= file_ts else 'файл'
                app_state.add_log(
                    f'Опорная дата: {datetime.fromtimestamp(last_ts).strftime("%d.%m.%Y %H:%M")} (источник: {src})',
                    'info'
                )
            elif vk_ts:
                last_ts = vk_ts
                app_state.add_log(
                    f'Опорная дата из VK: {datetime.fromtimestamp(last_ts).strftime("%d.%m.%Y %H:%M")}', 'info'
                )
            elif file_ts:
                last_ts = file_ts
                app_state.add_log(
                    f'Опорная дата из файла: {datetime.fromtimestamp(last_ts).strftime("%d.%m.%Y %H:%M")}',
                    'info'
                )
            else:
                last_ts = int(time.time())
                app_state.add_log('Отложенных постов нет, начинаю с текущего времени', 'info')

            write_last_scheduled(last_ts)
            next_ts = last_ts + random.randint(delay_min, delay_max)
        else:
            next_ts = int(time.time())

        published = failed = 0
        _poll_counter = 0

        for post_file in post_files:
            if not app_state.is_publishing:
                break
            try:
                post = json.loads(post_file.read_text(encoding='utf-8'))
                text = post.get('text', '').strip()
                ol = profile.get('ollama', {})
                tags = ' '.join(processing.get('hashtags', []))
                ap_cfg = profile.get('antiplagiaat', {})

                # Photo-only: discard text, skip Ollama
                if processing.get('photo_only', False):
                    text = ''

                # Антиплагиат: убрать оригинальный текст (оставить только свои хэштеги)
                if ap_cfg.get('enabled') and ap_cfg.get('clear_text', True):
                    text = ''

                # Ollama rewrite
                if text and ol.get('enabled'):
                    rw = rewrite_with_ollama(text, ol['url'], ol['model'],
                                             ol.get('target_words_min', 50),
                                             ol.get('target_words_max', 80))
                    if rw:
                        text = rw

                # Контент-библиотека: заменить текст+теги случайным вариантом
                from services.content_library import get_random_caption
                text = get_random_caption(text, add_tags=True)

                # Hashtags (если библиотека выключена — стандартный путь)
                if not text or (tags and (processing.get('add_hashtags') or not text)):
                    if tags and (processing.get('add_hashtags') or not text):
                        text = f'{text}\n\n{tags}'.strip() if text else tags

                # Upload photos
                attachments = []
                local_photos = post.get('_local_photos', [])

                # Антиплагиат: ограничить количество фото и перемешать
                if ap_cfg.get('enabled'):
                    max_ph = int(ap_cfg.get('max_photos', 5))
                    if len(local_photos) > max_ph:
                        mode = ap_cfg.get('remove_photo', 'last')
                        if mode == 'first':
                            local_photos = local_photos[1:]
                        elif mode == 'random':
                            idx = random.randint(0, len(local_photos) - 1)
                            local_photos = local_photos[:idx] + local_photos[idx + 1:]
                        else:  # last
                            local_photos = local_photos[:-1]
                        app_state.add_log(
                            f'Антиплагиат: фото {len(local_photos) + 1} → {len(local_photos)} (режим: {mode})',
                            'info'
                        )
                    # Перемешиваем фото — уникальный порядок для каждого поста
                    random.shuffle(local_photos)
                    app_state.add_log('Антиплагиат: фото перемешаны', 'info')

                for pp_str in local_photos:
                    pp = Path(pp_str)
                    if not pp.exists():
                        app_state.add_log(f'Фото не найдено локально: {pp.name}', 'warning')
                        continue
                    att = upload_photo_from_file(vk_user, gid_num, pp)
                    if att:
                        attachments.append(att)

                if local_photos:
                    app_state.add_log(
                        f'Фото загружено: {len(attachments)}/{len(local_photos)}',
                        'info' if attachments else 'error'
                    )
                    if not attachments:
                        app_state.add_log(
                            f'Пост {post_file.stem}: все фото не загружены — пропускаю',
                            'error'
                        )
                        failed += 1
                        app_state.bump_daily_stat('errors')
                        continue

                # Видео — прикрепляем по VK ID без повторной загрузки
                for vid_ref in post.get('_vk_videos', []):
                    attachments.append(vid_ref)
                if post.get('_vk_videos'):
                    app_state.add_log(f'Видео прикреплено: {len(post["_vk_videos"])}', 'info')

                # Polls: attach every N posts
                _poll_counter += 1
                poll_freq = max(1, int(polls_cfg.get('frequency', 5)))
                if polls_cfg.get('enabled') and polls_cfg.get('questions') and _poll_counter % poll_freq == 0:
                    poll_att = create_poll(
                        vk_user, gid_num,
                        polls_cfg['questions'],
                        polls_cfg.get('is_anonymous', True),
                        polls_cfg.get('multiple', False),
                    )
                    if poll_att:
                        attachments.append(poll_att)

                params = {'owner_id': owner_id, 'message': text}
                if attachments:
                    params['attachments'] = ','.join(attachments)

                if postponed:
                    # Ensure publish_date is in the future (VK API requirement)
                    now = int(time.time())
                    if next_ts <= now:
                        next_ts = now + random.randint(delay_min, delay_max)
                        app_state.add_log(
                            f'Дата в прошлом, скорректировано на {delay_min}-{delay_max}с',
                            'warning'
                        )
                    if peak_on and peak_hours_list:
                        next_ts = adjust_to_peak_hours(next_ts, peak_hours_list)
                    elif hours_on:
                        next_ts = adjust_to_publish_window(next_ts, h_start, h_end)
                    params['publish_date'] = next_ts
                    scheduled_label = datetime.fromtimestamp(next_ts).strftime('%d.%m %H:%M')

                result = vk_call_safe(vk.wall.post, **params)

                # ── Пункт 7: трекинг поста ────────────────────────
                if result and isinstance(result, dict):
                    vk_post_id = result.get('post_id')
                    if vk_post_id:
                        try:
                            from services.tracker import track as _track
                            source_cid = post.get('owner_id', '')
                            _track(vk_post_id, owner_id, str(source_cid))
                        except Exception:
                            pass

                # ── Пункт 3: кросс-постинг ───────────────────────
                cross_cfg = profile.get('cross_post', {})
                if cross_cfg.get('enabled') and cross_cfg.get('profile_ids'):
                    _cross_post(params, local_photos, cross_cfg['profile_ids'], vk_cfg, api_ver)

                # Save last scheduled
                if postponed:
                    write_last_scheduled(next_ts)
                    next_ts += random.randint(delay_min, delay_max)

                # Auto-cleanup: delete JSON + photo dir
                post_file.unlink(missing_ok=True)
                photo_dir = app_state.photos_dir / post_file.stem
                if photo_dir.exists():
                    shutil.rmtree(photo_dir, ignore_errors=True)

                published += 1
                stats['published'] = stats.get('published', 0) + 1
                app_state.save_stats(stats)
                app_state.bump_daily_stat('published')

                if postponed:
                    app_state.add_log(f'Запланирован {published}/{len(post_files)} → {scheduled_label}', 'info')
                else:
                    app_state.add_log(f'Опубликован {published}/{len(post_files)}', 'info')
                    if delay_min > 0:
                        random_delay(delay_min, delay_max)
                    else:
                        time.sleep(0.5)

            except vk_api.exceptions.ApiError as e:
                code = getattr(e, 'code', 0)
                msg = f'VK API ошибка {code}: {e}'
                app_state.add_log(msg, 'error')
                if code == 214 and postponed:
                    # Time slot taken — shift to the next random slot and retry
                    next_ts += random.randint(max(60, delay_min), max(120, delay_max))
                    app_state.add_log(
                        f'Время занято, сдвигаю → {datetime.fromtimestamp(next_ts).strftime("%d.%m %H:%M")}',
                        'warning'
                    )
                failed += 1
                stats['failed'] = stats.get('failed', 0) + 1
                app_state.save_stats(stats)
                app_state.bump_daily_stat('errors')
                if code in (5, 28):
                    send_critical_alert(f'Токен VK недействителен (код {code}). Бот остановлен.')
                    app_state.is_publishing = False
                    break
            except Exception as e:
                app_state.add_log(f'Ошибка поста: {e}', 'error')
                failed += 1
                app_state.bump_daily_stat('errors')

        result_msg = f'Публикация завершена: {published} запланировано, {failed} ошибок'
        app_state.add_log(result_msg, 'info')

        if published == 0 and failed > 0:
            send_critical_alert(f'Публикация: 0 успехов, {failed} ошибок. Проверь токены.')

    except Exception as e:
        app_state.add_log(f'Критическая ошибка публикации: {e}', 'error')
    finally:
        app_state.is_publishing = False


def rewrite_with_ollama(text: str, url: str, model: str, min_w: int, max_w: int):
    prompt = (
        f"Перепиши текст для публикации ВКонтакте. "
        f"Требования:\n- Строго от {min_w} до {max_w} слов\n"
        f"- Сохрани тему и смысл\n- Живой естественный русский\n"
        f"- Без вводных слов\n- Только переписанный текст\n\nТекст: {text}"
    )
    try:
        resp = req_lib.post(
            f'{url.rstrip("/")}/api/generate',
            json={'model': model, 'prompt': prompt, 'stream': False},
            timeout=90
        )
        resp.raise_for_status()
        result = resp.json().get('response', '').strip()
        if result:
            app_state.add_log(f'Ollama: переписано ({len(result.split())} слов)', 'info')
        return result or None
    except req_lib.exceptions.ConnectionError:
        app_state.add_log(f'Ollama недоступна по {url}', 'error')
        return None
    except Exception as e:
        app_state.add_log(f'Ollama: {e}', 'error')
        return None


def random_delay(min_s: float, max_s: float):
    time.sleep(random.uniform(min_s, max_s))


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


def adjust_to_peak_hours(ts: int, peak_hours: list) -> int:
    """Сдвинуть timestamp на ближайший пиковый час (пункт 2)."""
    if not peak_hours:
        return ts
    from datetime import datetime as _dt, timedelta
    peak_hours = sorted(set(int(h) for h in peak_hours if 0 <= int(h) <= 23))
    d = _dt.fromtimestamp(ts)
    # Ищем ближайший пиковый час >= текущего часа сегодня
    for h in peak_hours:
        if h >= d.hour:
            d = d.replace(hour=h, minute=random.randint(0, 59), second=random.randint(0, 59))
            return int(d.timestamp())
    # Все пики сегодня позади — берём первый пик завтра
    d = (d + timedelta(days=1)).replace(
        hour=peak_hours[0], minute=random.randint(0, 59), second=random.randint(0, 59)
    )
    return int(d.timestamp())


def _cross_post(params: dict, local_photos: list, target_pids: list,
                src_vk_cfg: dict, api_ver: str):
    """Опубликовать тот же пост в другие каналы (пункт 3)."""
    from vk.api import get_vk_api, vk_call_safe
    from vk.upload import upload_photo_from_file
    from pathlib import Path

    all_profiles = app_state.config.get('profiles', {})
    for pid in target_pids:
        prof = all_profiles.get(pid)
        if not prof:
            continue
        try:
            t_vk = prof.get('vk', {})
            g_token = t_vk.get('group_token', '').strip()
            u_token = t_vk.get('user_token', '').strip()
            gid = t_vk.get('group_id', '').strip()
            if not g_token or not gid:
                continue

            vk_g = get_vk_api(g_token, api_ver)
            vk_u = get_vk_api(u_token, api_ver)
            gid_num = int(gid.lstrip('-'))

            cross_att = []
            for pp_str in local_photos:
                pp = Path(pp_str)
                if pp.exists():
                    att = upload_photo_from_file(vk_u, gid_num, pp)
                    if att:
                        cross_att.append(att)

            cp = {**params, 'owner_id': f'-{gid_num}'}
            if cross_att:
                cp['attachments'] = ','.join(cross_att)
            elif 'publish_date' in cp:
                pass  # оставляем как есть

            vk_call_safe(vk_g.wall.post, **cp)
            app_state.add_log(f'Кросс-пост → канал «{prof.get("name", pid)}»', 'info')
        except Exception as e:
            app_state.add_log(f'Кросс-пост {pid}: {e}', 'warning')
