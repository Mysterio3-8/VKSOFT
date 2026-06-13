# -*- coding: utf-8 -*-
"""Publish worker."""

import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

import vk_api

from config import app_state
from services.storage import read_last_scheduled, write_last_scheduled
from services.ocr import photo_has_text
from services.google_image import fetch_google_image
from services.polls import create_poll
from vk.api import get_vk_api, vk_call_safe, normalize_owner_id, fetch_last_postponed_from_vk, get_postponed_count, VK_POSTPONED_LIMIT, send_critical_alert
from vk.upload import upload_photo_from_file


def _upload_local_photos_with_fallback(vk_user, gid_num: int, selected_photos: list, all_local_photos: list, log) -> list:
    attachments = []
    selected_paths = [Path(pp) for pp in selected_photos]

    for pp in selected_paths:
        if not pp.exists():
            log(f'Фото не найдено локально: {pp.name}', 'warning')
            continue
        att = upload_photo_from_file(vk_user, gid_num, pp)
        if att:
            attachments.append(att)

    if attachments or not all_local_photos:
        return attachments

    selected_resolved = {str(pp.resolve()) for pp in selected_paths if pp.exists()}
    fallback_paths = []
    for pp_str in all_local_photos:
        pp = Path(pp_str)
        if pp.exists() and str(pp.resolve()) not in selected_resolved:
            fallback_paths.append(pp)

    if not fallback_paths:
        return attachments

    log(f'Фото: выбранные файлы не загрузились, пробую резервные ({len(fallback_paths)})', 'warning')
    for pp in fallback_paths:
        att = upload_photo_from_file(vk_user, gid_num, pp)
        if att:
            attachments.append(att)
            break
    return attachments


def _compose_publish_text(post: dict, profile: dict, profile_id: str) -> tuple[str, dict]:
    """Вернуть (текст поста, мета выбранной подписи) — мета уходит в трекер."""
    processing = profile.get('processing', {})
    ap_cfg = profile.get('antiplagiaat', {})

    text = post.get('text', '').strip()
    if processing.get('photo_only', False):
        text = ''
    if ap_cfg.get('enabled') and ap_cfg.get('clear_text', True):
        text = ''

    from services.content_library import compose_caption_with_meta, get_active_promo_message
    from services.learning import get_smart_hashtags

    # Promo-сообщение заменяет весь текст поста если включено
    promo = get_active_promo_message(profile_id)
    if promo:
        return promo, {'caption_category': 'promo', 'caption_text': ''}

    smart_tags = get_smart_hashtags(profile_id)
    return compose_caption_with_meta(
        text,
        add_tags=True,
        profile_tags=processing.get('hashtags', []),
        add_profile_tags=processing.get('add_hashtags') or not text,
        extra_tags=smart_tags if smart_tags else None,
    )


def _prepare_local_photos_for_publish(local_photos: list, profile: dict, log) -> tuple[list, list]:
    local_photos = list(local_photos or [])
    all_local_photos = list(local_photos)
    ap_cfg = profile.get('antiplagiaat', {})

    if ap_cfg.get('enabled'):
        max_ph = int(ap_cfg.get('max_photos', 5))
        mode = ap_cfg.get('remove_photo', 'random')
        if len(local_photos) >= 2:
            before = len(local_photos)
            if mode == 'first':
                local_photos = local_photos[1:]
            elif mode == 'last':
                local_photos = local_photos[:-1]
            else:
                idx = random.randint(0, len(local_photos) - 1)
                local_photos = local_photos[:idx] + local_photos[idx + 1:]
            log(
                f'РђРЅС‚РёРїР»Р°РіРёР°С‚: С„РѕС‚Рѕ {before} в†’ {len(local_photos)} (СѓРґР°Р»РµРЅРѕ РѕРґРЅРѕ, СЂРµР¶РёРј: {mode})',
                'info'
            )
        if len(local_photos) > max_ph:
            before = len(local_photos)
            random.shuffle(local_photos)
            local_photos = local_photos[:max_ph]
            log(
                f'РђРЅС‚РёРїР»Р°РіРёР°С‚: С„РѕС‚Рѕ {before} в†’ {len(local_photos)} (Р»РёРјРёС‚: {max_ph})',
                'info'
            )
        random.shuffle(local_photos)
        if local_photos:
            log('РђРЅС‚РёРїР»Р°РіРёР°С‚: С„РѕС‚Рѕ РїРµСЂРµРјРµС€Р°РЅС‹', 'info')

    # Антиплагиат + вотермарка — единый пайплайн для любого медиа
    if local_photos:
        from services.media_pipeline import process_photos
        tr_ok = process_photos(local_photos, profile)
        if tr_ok:
            log(f'Антиплагиат+вотермарка: {tr_ok} фото', 'info')

    return local_photos, all_local_photos


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
            app_state.add_log('РћС€РёР±РєР°: Group Token РЅРµ Р·Р°РґР°РЅ', 'error')
            return
        if not user_token:
            app_state.add_log('РћС€РёР±РєР°: User Token РЅРµ Р·Р°РґР°РЅ', 'error')
            return
        if not group_id:
            app_state.add_log('РћС€РёР±РєР°: Group ID РЅРµ Р·Р°РґР°РЅ', 'error')
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
                f'РСЃРїСЂР°РІР»РµРЅС‹ РЅР°СЃС‚СЂРѕР№РєРё Р·Р°РґРµСЂР¶РєРё: publish_delay_min ({delay_min}) > publish_delay_max ({delay_max}), Р·РЅР°С‡РµРЅРёСЏ РїРѕРјРµРЅСЏРЅС‹ РјРµСЃС‚Р°РјРё',
                'warning'
            )
            delay_min, delay_max = delay_max, delay_min
        hours_on = pub_cfg.get('publish_hours_enabled', False)
        h_start = int(pub_cfg.get('publish_hours_start', 9))
        h_end = int(pub_cfg.get('publish_hours_end', 22))

        # в”Ђв”Ђ РџСѓРЅРєС‚ 2: РїРёРєРѕРІС‹Рµ С‡Р°СЃС‹ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        peak_cfg = profile.get('peak_hours', {})
        peak_on = peak_cfg.get('enabled', False)
        peak_hours_list = peak_cfg.get('hours', [])

        polls_cfg = profile.get('polls', {})

        post_files = sorted(app_state.posts_dir.glob('*.json'))[:count]
        if not post_files:
            app_state.add_log('РќРµС‚ РїРѕСЃС‚РѕРІ РґР»СЏ РїСѓР±Р»РёРєР°С†РёРё', 'warning')
            return

        app_state.download_progress = {
            'phase': 'publish',
            'current': 0,
            'total': len(post_files),
            'source': 'РћС‡РµСЂРµРґСЊ РїСѓР±Р»РёРєР°С†РёРё',
            'message': 'РџСѓР±Р»РёРєР°С†РёСЏ РѕС‡РµСЂРµРґРё',
            'cancelled': False,
        }
        app_state.add_log(f'РџСѓР±Р»РёРєР°С†РёСЏ {len(post_files)} РїРѕСЃС‚РѕРІ РІ {owner_id}', 'info')
        stats = app_state.load_stats()

        # Determine first publish time
        if postponed:
            file_ts = read_last_scheduled()
            ts_file = app_state.last_scheduled_file

            # Throttle VK API sync: skip if local file was updated less than 1 hour ago.
            # fetch_last_postponed_from_vk uses user_token and makes multiple wall.get calls
            # which can trigger rate limits and account restrictions.
            file_age = (time.time() - ts_file.stat().st_mtime) if ts_file.exists() else float('inf')
            if pub_cfg.get('skip_vk_sync', False):
                vk_ts = None
                app_state.add_log('VK sync skipped: fast postponed mode', 'info')
            elif file_age > 3600:
                app_state.add_log('РЎРёРЅС…СЂРѕРЅРёР·Р°С†РёСЏ СЃ VK: РёС‰Сѓ РїРѕСЃР»РµРґРЅРёР№ РѕС‚Р»РѕР¶РµРЅРЅС‹Р№ РїРѕСЃС‚...', 'info')
                vk_ts = fetch_last_postponed_from_vk(vk_user, owner_id)
            else:
                vk_ts = None
                app_state.add_log(
                    f'РЎРёРЅС…СЂРѕРЅРёР·Р°С†РёСЏ РїСЂРѕРїСѓС‰РµРЅР° (С„Р°Р№Р» РѕР±РЅРѕРІР»С‘РЅ {int(file_age // 60)} РјРёРЅ РЅР°Р·Р°Рґ, РёСЃРїРѕР»СЊР·СѓРµРј Р»РѕРєР°Р»СЊРЅС‹Р№)',
                    'info'
                )

            if vk_ts and file_ts:
                last_ts = max(vk_ts, file_ts)
                src = 'VK' if vk_ts >= file_ts else 'С„Р°Р№Р»'
                app_state.add_log(
                    f'РћРїРѕСЂРЅР°СЏ РґР°С‚Р°: {datetime.fromtimestamp(last_ts).strftime("%d.%m.%Y %H:%M")} (РёСЃС‚РѕС‡РЅРёРє: {src})',
                    'info'
                )
            elif vk_ts:
                last_ts = vk_ts
                app_state.add_log(
                    f'РћРїРѕСЂРЅР°СЏ РґР°С‚Р° РёР· VK: {datetime.fromtimestamp(last_ts).strftime("%d.%m.%Y %H:%M")}', 'info'
                )
            elif file_ts:
                last_ts = file_ts
                app_state.add_log(
                    f'РћРїРѕСЂРЅР°СЏ РґР°С‚Р° РёР· С„Р°Р№Р»Р°: {datetime.fromtimestamp(last_ts).strftime("%d.%m.%Y %H:%M")}',
                    'info'
                )
            else:
                last_ts = int(time.time())
                app_state.add_log('РћС‚Р»РѕР¶РµРЅРЅС‹С… РїРѕСЃС‚РѕРІ РЅРµС‚, РЅР°С‡РёРЅР°СЋ СЃ С‚РµРєСѓС‰РµРіРѕ РІСЂРµРјРµРЅРё', 'info')

            write_last_scheduled(last_ts)
            next_ts = last_ts + random.randint(delay_min, delay_max)
        else:
            next_ts = int(time.time())

        # Умное расписание: если включено — загружаем модель и занятые слоты
        _smart_schedule_enabled = pub_cfg.get('smart_schedule_enabled', False)
        _smart_occupied: list[int] = []
        _smart_model: dict = {}
        if postponed and _smart_schedule_enabled:
            try:
                from services.engagement import load_engagement_model, collect_engagement
                from services.slot_finder import fetch_postponed_timestamps
                _smart_model = load_engagement_model(app_state.active_profile_id)
                _smart_occupied = fetch_postponed_timestamps(vk, owner_id)
                # Запустить сбор engagement для непроверенных постов
                new_eng = collect_engagement(app_state.active_profile_id, group_id, vk_user)
                if new_eng:
                    app_state.add_log(f'[Обучение] Обновлены данные для {len(new_eng)} постов', 'info')
                app_state.add_log(
                    f'[Умное расписание] Модель: {"обучена" if _smart_model.get("hour_heatmap") else "стартовая"}, '
                    f'занято слотов: {len(_smart_occupied)}',
                    'info'
                )
            except Exception as e:
                app_state.add_log(f'[Умное расписание] Ошибка загрузки: {e}', 'warning')
                _smart_schedule_enabled = False

        learned_schedule_slots = []
        growth_schedule = profile.get('growth_schedule', {})
        if postponed and growth_schedule.get('enabled') and growth_schedule.get('mode') == 'learned_24h':
            try:
                from services.growth_autopilot import build_learned_24h_schedule
                learned_schedule_slots = build_learned_24h_schedule(
                    count=len(post_files),
                    start_ts=next_ts,
                    heatmap=growth_schedule.get('hour_heatmap', []),
                    horizon_days=int(growth_schedule.get('horizon_days') or profile.get('autopost_cycle', {}).get('horizon_days') or 1),
                    exploitation_percent=int(growth_schedule.get('exploitation_percent') or 75),
                )
                if learned_schedule_slots:
                    app_state.add_log(
                        f'Growth schedule 24/7: {len(learned_schedule_slots)} slots, best/test hours enabled',
                        'info'
                    )
            except Exception as e:
                app_state.add_log(f'Growth schedule 24/7 fallback: {e}', 'warning')

        published = failed = 0
        _poll_counter = 0

        publish_started_at = time.time()
        for index, post_file in enumerate(post_files, 1):
            if not app_state.is_publishing:
                break
            try:
                post_started_at = time.time()
                app_state.download_progress.update({
                    'phase': 'publish',
                    'current': index - 1,
                    'total': len(post_files),
                    'message': f'РџСѓР±Р»РёРєР°С†РёСЏ {index} РёР· {len(post_files)}',
                })
                post = json.loads(post_file.read_text(encoding='utf-8'))
                text, caption_meta = _compose_publish_text(post, profile, app_state.active_profile_id)

                # Upload photos
                attachments = []
                local_photos, all_local_photos = _prepare_local_photos_for_publish(
                    post.get('_local_photos', []),
                    profile,
                    app_state.add_log,
                )

                attachments.extend(_upload_local_photos_with_fallback(
                    vk_user,
                    gid_num,
                    local_photos,
                    all_local_photos,
                    app_state.add_log,
                ))

                if local_photos:
                    app_state.add_log(
                        f'Р¤РѕС‚Рѕ Р·Р°РіСЂСѓР¶РµРЅРѕ: {len(attachments)}/{len(local_photos)}',
                        'info' if attachments else 'error'
                    )
                    if not attachments:
                        app_state.add_log(
                            f'РџРѕСЃС‚ {post_file.stem}: РІСЃРµ С„РѕС‚Рѕ РЅРµ Р·Р°РіСЂСѓР¶РµРЅС‹ вЂ” РїСЂРѕРїСѓСЃРєР°СЋ',
                            'error'
                        )
                        failed += 1
                        app_state.download_progress.update({
                            'current': index,
                            'message': f'РћРїСѓР±Р»РёРєРѕРІР°РЅРѕ {published}, РѕС€РёР±РѕРє {failed}',
                        })
                        app_state.bump_daily_stat('errors')
                        from services.publish_log import log_publish_event
                        log_publish_event(
                            media_type='posts',
                            status='failed',
                            source_id=str(post.get('owner_id', '')),
                            extra={'reason': 'photos_upload_failed'},
                        )
                        continue

                # Р’РёРґРµРѕ вЂ” РїСЂРёРєСЂРµРїР»СЏРµРј РїРѕ VK ID Р±РµР· РїРѕРІС‚РѕСЂРЅРѕР№ Р·Р°РіСЂСѓР·РєРё
                for vid_ref in post.get('_vk_videos', []):
                    attachments.append(vid_ref)
                if post.get('_vk_videos'):
                    app_state.add_log(f'Р’РёРґРµРѕ РїСЂРёРєСЂРµРїР»РµРЅРѕ: {len(post["_vk_videos"])}', 'info')

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
                    if _smart_schedule_enabled:
                        # Умное расписание с обучением
                        try:
                            from services.smart_scheduler import next_publish_timestamp
                            _last_ts = read_last_scheduled() or int(time.time())
                            next_ts, _chosen_hour = next_publish_timestamp(
                                _last_ts, profile, _smart_model, _smart_occupied
                            )
                            _smart_occupied = sorted(_smart_occupied + [next_ts])
                            app_state.add_log(
                                f'[Умное расписание] {datetime.fromtimestamp(next_ts).strftime("%d.%m %H:%M")} (час {_chosen_hour})',
                                'info'
                            )
                        except Exception as e:
                            app_state.add_log(f'[Умное расписание] Fallback: {e}', 'warning')
                            next_ts = (read_last_scheduled() or int(time.time())) + random.randint(delay_min, delay_max)
                    elif learned_schedule_slots and index <= len(learned_schedule_slots):
                        next_ts = learned_schedule_slots[index - 1].ts
                    # Ensure publish_date is in the future (VK API requirement)
                    now = int(time.time())
                    if next_ts <= now:
                        next_ts = now + random.randint(delay_min, delay_max)
                        app_state.add_log(
                            f'Дата в прошлом, скорректировано на {delay_min}-{delay_max}с',
                            'warning'
                        )
                    if not _smart_schedule_enabled:
                        if peak_on and peak_hours_list:
                            next_ts = adjust_to_peak_hours(next_ts, peak_hours_list)
                        elif hours_on:
                            next_ts = adjust_to_publish_window(next_ts, h_start, h_end)
                    params['publish_date'] = next_ts
                    scheduled_label = datetime.fromtimestamp(next_ts).strftime('%d.%m %H:%M')

                    from services.slot_scheduler import record_slot
                    record_slot('posts', next_ts)

                result = vk_call_safe(vk.wall.post, **params)

                # ── Пункт 7: трекинг поста ────────────────────────────────
                if result and isinstance(result, dict):
                    vk_post_id = result.get('post_id')
                    if vk_post_id:
                        from services.publish_log import log_publish_event
                        log_publish_event(
                            media_type='posts',
                            status='success',
                            post_id=vk_post_id,
                            publish_date=params.get('publish_date'),
                            source_id=str(post.get('owner_id', '')),
                        )
                        try:
                            from services.growth_autopilot import mark_used_post, source_post_key
                            source_id = str(post.get('owner_id') or post_file.stem.split('_')[0]).lstrip('-')
                            mark_used_post(
                                {
                                    'dedup_key': source_post_key(post, source_id),
                                    'source_id': source_id,
                                    'post_id': post.get('id') or post.get('post_id'),
                                },
                                profile_id=app_state.active_profile_id,
                            )
                        except Exception:
                            pass
                        try:
                            from services.tracker import track as _track
                            source_cid = post.get('owner_id', '')
                            _track(
                                vk_post_id, owner_id, str(source_cid),
                                published_at=params.get('publish_date'),
                                caption_category=caption_meta.get('caption_category', ''),
                                caption_text=caption_meta.get('caption_text', ''),
                                caption_id=caption_meta.get('caption_id', ''),
                                media_type='photo',
                            )
                        except Exception:
                            pass
                        # Записать для engagement-обучения
                        if _smart_schedule_enabled:
                            try:
                                from services.engagement import record_published_post
                                from datetime import datetime as _dt, timedelta as _td
                                _pub_ts = params.get('publish_date', int(time.time()))
                                _tz_offset = 3  # fallback MSK
                                try:
                                    from services.smart_scheduler import _get_tz_offset
                                    _tz_offset = _get_tz_offset(pub_cfg.get('timezone', 'Europe/Moscow'))
                                except Exception:
                                    pass
                                _local_hour = (_dt.utcfromtimestamp(_pub_ts) + _td(hours=_tz_offset)).hour
                                record_published_post(app_state.active_profile_id, vk_post_id, _pub_ts, _local_hour)
                                app_state.add_log(f'[Обучение] Пост {vk_post_id} записан (час {_local_hour})', 'info')
                            except Exception as _e:
                                app_state.add_log(f'[Обучение] Ошибка записи: {_e}', 'warning')

                # в”Ђв”Ђ РџСѓРЅРєС‚ 3: РєСЂРѕСЃСЃ-РїРѕСЃС‚РёРЅРі в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
                cross_cfg = profile.get('cross_post', {})
                if cross_cfg.get('enabled') and cross_cfg.get('profile_ids'):
                    _cross_post(params, local_photos, cross_cfg['profile_ids'], vk_cfg, api_ver)

                # Save last scheduled
                if postponed:
                    write_last_scheduled(next_ts)
                    next_ts += random.randint(delay_min, delay_max)

                # Auto-cleanup: delete only after successful VK post.
                cleanup_cfg = profile.get('storage_cleanup', {})
                if cleanup_cfg.get('after_publish_success', True):
                    try:
                        from services.cleanup_storage import cleanup_post_artifacts
                        cleanup_result = cleanup_post_artifacts(post_file, post)
                        app_state.add_log(
                            'РђРІС‚РѕРѕС‡РёСЃС‚РєР°: СѓРґР°Р»РµРЅРѕ '
                            f'{cleanup_result.get("deleted_json", 0)} json, '
                            f'{cleanup_result.get("deleted_files", 0)} С„Р°Р№Р»РѕРІ',
                            'info'
                        )
                    except Exception as e:
                        app_state.add_log(f'РђРІС‚РѕРѕС‡РёСЃС‚РєР° РїРѕСЃС‚Р°: {e}', 'warning')

                published += 1
                post_elapsed = max(1, int(time.time() - post_started_at))
                app_state.download_progress.update({
                    'current': index,
                    'message': f'РћРїСѓР±Р»РёРєРѕРІР°РЅРѕ {published}, РѕС€РёР±РѕРє {failed}',
                })
                stats['published'] = stats.get('published', 0) + 1
                app_state.save_stats(stats)
                app_state.bump_daily_stat('published')
                if postponed:
                    app_state.add_log(f'publish timing: post {published}/{len(post_files)} in {post_elapsed}s, attachments={len(attachments)}', 'info')
                    app_state.add_log(f'Р—Р°РїР»Р°РЅРёСЂРѕРІР°РЅ {published}/{len(post_files)} в†’ {scheduled_label}', 'info')
                else:
                    app_state.add_log(f'РћРїСѓР±Р»РёРєРѕРІР°РЅ {published}/{len(post_files)}', 'info')
                    if delay_min > 0:
                        random_delay(delay_min, delay_max)
                    else:
                        time.sleep(0.5)

            except vk_api.exceptions.ApiError as e:
                code = getattr(e, 'code', 0)
                msg = f'VK API РѕС€РёР±РєР° {code}: {e}'
                app_state.add_log(msg, 'error')
                if code == 214 and postponed:
                    # Time slot taken вЂ” shift to the next random slot and retry
                    next_ts += random.randint(max(60, delay_min), max(120, delay_max))
                    app_state.add_log(
                        f'Р’СЂРµРјСЏ Р·Р°РЅСЏС‚Рѕ, СЃРґРІРёРіР°СЋ в†’ {datetime.fromtimestamp(next_ts).strftime("%d.%m %H:%M")}',
                        'warning'
                    )
                failed += 1
                app_state.download_progress.update({
                    'current': index,
                    'message': f'РћРїСѓР±Р»РёРєРѕРІР°РЅРѕ {published}, РѕС€РёР±РѕРє {failed}',
                })
                stats['failed'] = stats.get('failed', 0) + 1
                app_state.save_stats(stats)
                app_state.bump_daily_stat('errors')
                if code in (5, 28):
                    send_critical_alert(f'РўРѕРєРµРЅ VK РЅРµРґРµР№СЃС‚РІРёС‚РµР»РµРЅ (РєРѕРґ {code}). Р‘РѕС‚ РѕСЃС‚Р°РЅРѕРІР»РµРЅ.')
                    app_state.is_publishing = False
                    break
            except Exception as e:
                app_state.add_log(f'РћС€РёР±РєР° РїРѕСЃС‚Р°: {e}', 'error')
                failed += 1
                app_state.download_progress.update({
                    'current': index,
                    'message': f'РћРїСѓР±Р»РёРєРѕРІР°РЅРѕ {published}, РѕС€РёР±РѕРє {failed}',
                })
                app_state.bump_daily_stat('errors')

        result_msg = f'РџСѓР±Р»РёРєР°С†РёСЏ Р·Р°РІРµСЂС€РµРЅР°: {published} Р·Р°РїР»Р°РЅРёСЂРѕРІР°РЅРѕ, {failed} РѕС€РёР±РѕРє'
        app_state.add_log(f'publish done: scheduled {published}, errors {failed}, total {max(1, int(time.time() - publish_started_at))}s', 'info')
        app_state.add_log(result_msg, 'info')

        if published > 0 and profile.get('storage_cleanup', {}).get('clean_orphans_after_run', True):
            try:
                from services.cleanup_storage import cleanup_junk
                junk = cleanup_junk()
                removed = sum(int(v or 0) for v in junk.values())
                if removed:
                    app_state.add_log(
                        f'РђРІС‚РѕРѕС‡РёСЃС‚РєР° РјСѓСЃРѕСЂР°: СѓРґР°Р»РµРЅРѕ {removed} РѕСЃС‚Р°С‚РѕС‡РЅС‹С… С„Р°Р№Р»РѕРІ/РїР°РїРѕРє',
                        'info'
                    )
            except Exception as e:
                app_state.add_log(f'РђРІС‚РѕРѕС‡РёСЃС‚РєР° РјСѓСЃРѕСЂР°: {e}', 'warning')

        if published == 0 and failed > 0:
            send_critical_alert(f'РџСѓР±Р»РёРєР°С†РёСЏ: 0 СѓСЃРїРµС…РѕРІ, {failed} РѕС€РёР±РѕРє. РџСЂРѕРІРµСЂСЊ С‚РѕРєРµРЅС‹.')

    except Exception as e:
        app_state.add_log(f'РљСЂРёС‚РёС‡РµСЃРєР°СЏ РѕС€РёР±РєР° РїСѓР±Р»РёРєР°С†РёРё: {e}', 'error')
    finally:
        app_state.is_publishing = False
        if not app_state.is_downloading:
            app_state.download_progress['phase'] = 'idle'


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
    """РЎРґРІРёРЅСѓС‚СЊ timestamp РЅР° Р±Р»РёР¶Р°Р№С€РёР№ РїРёРєРѕРІС‹Р№ С‡Р°СЃ (РїСѓРЅРєС‚ 2)."""
    if not peak_hours:
        return ts
    from datetime import datetime as _dt, timedelta
    peak_hours = sorted(set(int(h) for h in peak_hours if 0 <= int(h) <= 23))
    d = _dt.fromtimestamp(ts)
    # РС‰РµРј Р±Р»РёР¶Р°Р№С€РёР№ РїРёРєРѕРІС‹Р№ С‡Р°СЃ >= С‚РµРєСѓС‰РµРіРѕ С‡Р°СЃР° СЃРµРіРѕРґРЅСЏ
    for h in peak_hours:
        if h >= d.hour:
            d = d.replace(hour=h, minute=random.randint(0, 59), second=random.randint(0, 59))
            return int(d.timestamp())
    # Р’СЃРµ РїРёРєРё СЃРµРіРѕРґРЅСЏ РїРѕР·Р°РґРё вЂ” Р±РµСЂС‘Рј РїРµСЂРІС‹Р№ РїРёРє Р·Р°РІС‚СЂР°
    d = (d + timedelta(days=1)).replace(
        hour=peak_hours[0], minute=random.randint(0, 59), second=random.randint(0, 59)
    )
    return int(d.timestamp())


def _cross_post(params: dict, local_photos: list, target_pids: list,
                src_vk_cfg: dict, api_ver: str):
    """РћРїСѓР±Р»РёРєРѕРІР°С‚СЊ С‚РѕС‚ Р¶Рµ РїРѕСЃС‚ РІ РґСЂСѓРіРёРµ РєР°РЅР°Р»С‹ (РїСѓРЅРєС‚ 3)."""
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
                pass  # РѕСЃС‚Р°РІР»СЏРµРј РєР°Рє РµСЃС‚СЊ

            vk_call_safe(vk_g.wall.post, **cp)
            app_state.add_log(f'РљСЂРѕСЃСЃ-РїРѕСЃС‚ в†’ РєР°РЅР°Р» В«{prof.get("name", pid)}В»', 'info')
        except Exception as e:
            app_state.add_log(f'РљСЂРѕСЃСЃ-РїРѕСЃС‚ {pid}: {e}', 'warning')
