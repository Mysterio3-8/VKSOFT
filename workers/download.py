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


def download_batch_size(remaining: int, dl_cfg: Dict) -> int:
    try:
        batch_size = int(dl_cfg.get('batch_size', 100))
    except Exception:
        batch_size = 100
    return max(1, min(batch_size or 100, 100))


def download_scan_limit(target_count: int, dl_cfg: Dict) -> int:
    if dl_cfg.get('max_scan_posts'):
        return max(1, int(dl_cfg.get('max_scan_posts')))
    multiplier = max(1, int(dl_cfg.get('scan_multiplier', 5)))
    return max(100, int(target_count) * multiplier)


def per_source_download_count(total_count: int, source_count: int) -> int:
    if source_count <= 0:
        return max(1, int(total_count))
    return max(1, int((int(total_count) + source_count - 1) / source_count))


def select_photos_for_download(photos: list, profile: Dict, dl_cfg: Dict) -> list:
    if not photos:
        return []
    explicit_limit = int(dl_cfg.get('max_photos_per_post') or 0)
    if explicit_limit > 0:
        return photos[:explicit_limit]

    ap_cfg = profile.get('antiplagiaat', {})
    if ap_cfg.get('enabled', False):
        max_photos = max(1, int(ap_cfg.get('max_photos', 4)))
        return photos[:max_photos + 1]
    return photos


def _is_used_post(post: Dict, community_id: str) -> bool:
    try:
        from services.growth_autopilot import load_used_posts, source_post_key
        return source_post_key(post, str(community_id)) in load_used_posts()
    except Exception:
        return False


def _download_source(community_id: str, count: int):
    """Core download logic вЂ” caller manages is_downloading flag."""
    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    dl_cfg = profile.get('download_settings', {})
    user_token = vk_cfg.get('user_token', '').strip()
    api_ver = vk_cfg.get('api_version', '5.131')

    if not user_token:
        app_state.add_log('РћС€РёР±РєР°: VK User Token РЅРµ Р·Р°РґР°РЅ', 'error')
        return 0

    vk = get_vk_api(user_token, api_ver)
    owner_id = normalize_owner_id(community_id)
    delay_min = float(dl_cfg.get('delay_min', 1))
    delay_max = float(dl_cfg.get('delay_max', 3))
    if delay_min > delay_max:
        delay_min, delay_max = delay_max, delay_min
    check_dup = True

    allow_video = profile.get('processing', {}).get('allow_video', False)

    # в”Ђв”Ђ РџСѓРЅРєС‚ 1: С„РёР»СЊС‚СЂ РїРѕ РІРѕРІР»РµС‡С‘РЅРЅРѕСЃС‚Рё в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    eng_cfg = profile.get('engagement', {})
    eng_enabled   = eng_cfg.get('enabled', False)
    eng_min_ratio = float(eng_cfg.get('min_ratio', 0.5))  # % Р»Р°Р№РєРѕРІ РѕС‚ РїСЂРѕСЃРјРѕС‚СЂРѕРІ
    eng_min_likes = int(eng_cfg.get('min_likes', 0))

    # в”Ђв”Ђ РџСѓРЅРєС‚ 6: phash РґРµРґСѓРїР»РёРєР°С†РёСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    phash_cfg = profile.get('phash', {})
    phash_enabled = False
    phash_threshold = int(phash_cfg.get('threshold', 10))

    saved_offset = read_offsets().get(str(community_id), 0)
    if saved_offset:
        app_state.add_log(f'РџСЂРѕРґРѕР»Р¶Р°СЋ СЃ РїРѕР·РёС†РёРё {saved_offset}', 'info')
    offset = saved_offset

    app_state.add_log(f'Р—Р°РіСЂСѓР·РєР° {count} РїРѕСЃС‚РѕРІ РёР· {owner_id}', 'info')
    app_state.download_progress = {
        'phase': 'download',
        'current': 0,
        'total': count,
        'source': str(community_id),
        'message': f'Р—Р°РіСЂСѓР·РєР° РёР· {owner_id}',
        'cancelled': app_state.download_progress.get('cancelled', False),
    }

    started_at = time.time()
    downloaded = skipped = scanned = 0
    skip_reasons = {
        'video_disabled': 0,
        'no_media': 0,
        'filters': 0,
        'engagement': 0,
        'duplicate': 0,
        'photo_download': 0,
        'phash': 0,
    }
    max_scan = download_scan_limit(count, dl_cfg)
    # Р”Р»СЏ СЃС‚Р°С‚РёСЃС‚РёРєРё РёСЃС‚РѕС‡РЅРёРєР° (РїСѓРЅРєС‚ 4)
    total_likes = total_views = stat_posts = 0

    while downloaded < count and scanned < max_scan and app_state.is_downloading:
        batch = download_batch_size(count - downloaded, dl_cfg)
        try:
            resp = vk_call_safe(vk.wall.get, owner_id=owner_id, count=batch, offset=offset, filter='owner')
        except vk_api.exceptions.ApiError as e:
            code = getattr(e, 'code', 0)
            msg = f'VK API (Р·Р°РіСЂСѓР·РєР°) РѕС€РёР±РєР° {code}: {e}'
            app_state.add_log(msg, 'error')
            if code in (5, 28):
                send_critical_alert(f'РўРѕРєРµРЅ VK РЅРµРґРµР№СЃС‚РІРёС‚РµР»РµРЅ (РєРѕРґ {code}). Р—Р°РіСЂСѓР·РєР° РѕСЃС‚Р°РЅРѕРІР»РµРЅР°.')
                app_state.is_downloading = False
            break

        items = resp.get('items', [])
        if not items:
            app_state.add_log(f'{owner_id}: РїРѕСЃС‚РѕРІ Р±РѕР»СЊС€Рµ РЅРµС‚', 'info')
            clear_offset(str(community_id))
            break

        for post in items:
            if not app_state.is_downloading or downloaded >= count:
                break
            scanned += 1

            post_id = post.get('id')
            text = post.get('text', '')
            attachments = post.get('attachments', [])

            has_video = any(a.get('type') == 'video' for a in attachments)
            photos = [a for a in attachments if a.get('type') == 'photo']
            videos = [a for a in attachments if a.get('type') == 'video'] if allow_video else []

            if has_video and not allow_video:
                skipped += 1
                skip_reasons['video_disabled'] += 1
                continue

            if not photos and not videos:
                skipped += 1
                skip_reasons['no_media'] += 1
                continue

            if not post_passes_filters(text, profile):
                skipped += 1
                skip_reasons['filters'] += 1
                continue

            # в”Ђв”Ђ РџСѓРЅРєС‚ 1: С„РёР»СЊС‚СЂ РїРѕ РІРѕРІР»РµС‡С‘РЅРЅРѕСЃС‚Рё в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
            if eng_enabled:
                likes = post.get('likes', {}).get('count', 0)
                views = post.get('views', {}).get('count', 1)
                ratio = likes / max(views, 1) * 100
                if eng_min_likes > 0 and likes < eng_min_likes:
                    skipped += 1
                    skip_reasons['engagement'] += 1
                    continue
                if eng_min_ratio > 0 and ratio < eng_min_ratio:
                    skipped += 1
                    skip_reasons['engagement'] += 1
                    continue

            fname = app_state.posts_dir / f'{community_id}_{post_id}.json'
            if check_dup and (fname.exists() or _is_used_post(post, str(community_id))):
                skipped += 1
                skip_reasons['duplicate'] += 1
                continue

            photos_to_download = select_photos_for_download(photos, profile, dl_cfg)
            if photos and len(photos_to_download) < len(photos):
                app_state.add_log(
                    f'[{owner_id}] post {post_id}: photos {len(photos_to_download)}/{len(photos)} selected',
                    'info'
                )
            local_photos = download_photos_for_post(community_id, post_id, photos_to_download) if photos_to_download else []
            if not local_photos and not videos:
                skipped += 1
                skip_reasons['photo_download'] += 1
                continue

            # в”Ђв”Ђ РџСѓРЅРєС‚ 6: phash РґРµРґСѓРїР»РёРєР°С†РёСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
            if phash_enabled and local_photos:
                from services.phash import is_duplicate, add_to_cache
                first_photo = Path(local_photos[0])
                if is_duplicate(first_photo, phash_threshold):
                    app_state.add_log(f'Phash: РїРѕСЃС‚ {post_id} вЂ” РґСѓР±Р»РёРєР°С‚, РїСЂРѕРїСѓСЃРєР°СЋ', 'info')
                    # РЈРґР°Р»СЏРµРј СЃРєР°С‡Р°РЅРЅС‹Рµ С„РѕС‚Рѕ
                    for pp in local_photos:
                        try:
                            Path(pp).unlink(missing_ok=True)
                        except Exception:
                            pass
                    skipped += 1
                    skip_reasons['phash'] += 1
                    continue
                # Р”РѕР±Р°РІР»СЏРµРј РїРµСЂРІРѕРµ С„РѕС‚Рѕ РІ РєСЌС€
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

            # РќР°РєР°РїР»РёРІР°РµРј РґР»СЏ СЂРµР№С‚РёРЅРіР° РёСЃС‚РѕС‡РЅРёРєР°
            total_likes += post.get('likes', {}).get('count', 0)
            total_views += post.get('views', {}).get('count', 0)
            stat_posts += 1

            downloaded += 1
            app_state.download_progress['current'] = downloaded
            app_state.download_progress['message'] = f'РЎРѕС…СЂР°РЅРµРЅРѕ {downloaded} РёР· {count}'
            if downloaded % 10 == 0 or downloaded == 1:
                app_state.add_log(f'[{owner_id}] {downloaded}/{count} СЃРѕС…СЂР°РЅРµРЅРѕ', 'info')

        offset += len(items)
        elapsed = max(1, int(time.time() - started_at))
        app_state.add_log(
            f'[{owner_id}] batch: saved {downloaded}/{count}, scanned {scanned}/{max_scan}, skipped {skipped}, {elapsed}s',
            'info'
        )
        save_offset(str(community_id), offset)
        if downloaded < count and scanned < max_scan and app_state.is_downloading:
            random_delay(delay_min, delay_max)

    if downloaded < count and scanned >= max_scan:
        app_state.add_log(
            f'[{owner_id}] РћСЃС‚Р°РЅРѕРІРёР» СЃРєР°РЅРёСЂРѕРІР°РЅРёРµ: РїСЂРѕСЃРјРѕС‚СЂРµРЅРѕ {scanned}, СЃРѕС…СЂР°РЅРµРЅРѕ {downloaded}/{count}. '
            'РЈРІРµР»РёС‡СЊС‚Рµ max_scan_posts, РµСЃР»Рё РЅСѓР¶РЅРѕ РёСЃРєР°С‚СЊ РіР»СѓР±Р¶Рµ.',
            'warning'
        )

    if app_state.is_downloading:
        clear_offset(str(community_id))

    # в”Ђв”Ђ РџСѓРЅРєС‚ 4: РѕР±РЅРѕРІРёС‚СЊ СЂРµР№С‚РёРЅРі РёСЃС‚РѕС‡РЅРёРєР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    if stat_posts > 0:
        from api.growth import update_source_stat
        avg_likes = total_likes / stat_posts
        avg_views = total_views / max(stat_posts, 1)
        update_source_stat(str(community_id), stat_posts, avg_likes, avg_views)

    elapsed = max(1, int(time.time() - started_at))
    active_reasons = ', '.join(f'{k}={v}' for k, v in skip_reasons.items() if v)
    reason_suffix = f' ({active_reasons})' if active_reasons else ''
    app_state.add_log(
        f'[{owner_id}] done: downloaded {downloaded}, skipped {skipped}, scanned {scanned} in {elapsed}s{reason_suffix}',
        'info'
    )

    app_state.add_log(f'[{owner_id}] Р“РѕС‚РѕРІРѕ: {downloaded} СЃРєР°С‡Р°РЅРѕ, {skipped} РїСЂРѕРїСѓС‰РµРЅРѕ', 'info')
    return downloaded


def download_worker(community_id: str, count: int):
    try:
        _download_source(community_id, count)
    except Exception as e:
        app_state.add_log(f'РћС€РёР±РєР° Р·Р°РіСЂСѓР·РєРё: {e}', 'error')
    finally:
        app_state.is_downloading = False


def download_all_worker():
    profile = app_state.profile
    sources = [s for s in profile.get('sources', []) if s.get('enabled')]
    if not sources:
        app_state.add_log('РќРµС‚ Р°РєС‚РёРІРЅС‹С… РёСЃС‚РѕС‡РЅРёРєРѕРІ', 'warning')
        app_state.is_downloading = False
        return
    count = int(profile.get('download_settings', {}).get('posts_to_download', 100))
    app_state.download_progress = {
        'phase': 'download',
        'current': 0,
        'total': int(count),
        'source': 'Р’СЃРµ РёСЃС‚РѕС‡РЅРёРєРё',
        'message': 'РџР°РєРµС‚РЅР°СЏ Р·Р°РіСЂСѓР·РєР° Р·Р°РїСѓС‰РµРЅР°',
        'cancelled': False,
    }
    app_state.add_log(f'РџР°РєРµС‚РЅР°СЏ Р·Р°РіСЂСѓР·РєР°: {count} РІСЃРµРіРѕ, {len(sources)} РёСЃС‚РѕС‡РЅРёРєРѕРІ', 'info')
    try:
        from services.seasonality import order_sources_by_season
        from services.source_quality import is_source_blocked
        sources = order_sources_by_season(sources)
        eligible_sources = [
            src for src in sources
            if not is_source_blocked(str(src.get('community_id', '')))
        ]
        blocked_count = len(sources) - len(eligible_sources)
        if blocked_count:
            app_state.add_log(f'РџР°РєРµС‚РЅР°СЏ Р·Р°РіСЂСѓР·РєР°: РїСЂРѕРїСѓС‰РµРЅРѕ СЃС‚РѕРї-РёСЃС‚РѕС‡РЅРёРєРѕРІ {blocked_count}', 'info')
        remaining = count
        for i, src in enumerate(eligible_sources, 1):
            if not app_state.is_downloading:
                break
            if remaining <= 0:
                break
            cid = str(src.get('community_id', ''))
            sources_left = len(eligible_sources) - i + 1
            per_source_count = per_source_download_count(remaining, sources_left)
            app_state.download_progress.update({
                'source': src.get('name', cid),
                'message': f'РСЃС‚РѕС‡РЅРёРє {i}/{len(eligible_sources)}',
            })
            app_state.add_log(f'РСЃС‚РѕС‡РЅРёРє {i}/{len(eligible_sources)}: {src.get("name", cid)} РґРѕ {per_source_count}', 'info')
            downloaded = int(_download_source(cid, per_source_count) or 0)
            remaining = max(0, remaining - downloaded)
        total = len(list(app_state.posts_dir.glob('*.json')))
        app_state.add_log(f'Р’СЃРµ РёСЃС‚РѕС‡РЅРёРєРё РѕР±СЂР°Р±РѕС‚Р°РЅС‹. Р’ РѕС‡РµСЂРµРґРё: {total}', 'info')
    except Exception as e:
        app_state.add_log(f'РџР°РєРµС‚РЅР°СЏ Р·Р°РіСЂСѓР·РєР°: {e}', 'error')
    finally:
        app_state.is_downloading = False


def download_then_publish_worker():
    try:
        app_state.download_progress['cancelled'] = False
        download_all_worker()
        if app_state.download_progress.get('cancelled'):
            app_state.add_log('РђРІС‚РѕРїСѓР±Р»РёРєР°С†РёСЏ РѕС‚РјРµРЅРµРЅР°: Р·Р°РіСЂСѓР·РєР° РѕСЃС‚Р°РЅРѕРІР»РµРЅР° РїРѕР»СЊР·РѕРІР°С‚РµР»РµРј', 'warning')
            return

        pending = len(list(app_state.posts_dir.glob('*.json')))
        if pending <= 0:
            app_state.download_progress.update({
                'phase': 'idle',
                'current': 0,
                'total': 0,
                'message': 'РџРѕСЃР»Рµ Р·Р°РіСЂСѓР·РєРё РЅРµС‚ РїРѕСЃС‚РѕРІ РґР»СЏ РїСѓР±Р»РёРєР°С†РёРё',
            })
            app_state.add_log('РџРѕСЃР»Рµ Р·Р°РіСЂСѓР·РєРё РЅРµС‚ РїРѕСЃС‚РѕРІ РґР»СЏ РїСѓР±Р»РёРєР°С†РёРё', 'warning')
            return

        from workers.publish import publish_worker
        count = int(app_state.profile.get('publishing_settings', {}).get('posts_to_publish', 50))
        app_state.download_progress.update({
            'phase': 'publish',
            'current': 0,
            'total': min(count, pending),
            'source': 'РћС‡РµСЂРµРґСЊ РїСѓР±Р»РёРєР°С†РёРё',
            'message': 'РџСѓР±Р»РёРєР°С†РёСЏ РѕС‡РµСЂРµРґРё',
        })
        app_state.is_publishing = True
        publish_worker(min(count, pending))
    except Exception as e:
        app_state.add_log(f'Р—Р°РіСЂСѓР·РєР° Рё РїСѓР±Р»РёРєР°С†РёСЏ: {e}', 'error')
    finally:
        if not app_state.is_downloading and not app_state.is_publishing:
            app_state.download_progress['phase'] = 'idle'

    # Видео и клипы больше не цепляются к циклу постов — у каждого типа
    # медиа свой цикл автопилота (workers/media_autopilot.py)


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
