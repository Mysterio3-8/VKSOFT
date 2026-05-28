# -*- coding: utf-8 -*-
"""Growth API — пункты 3, 4, 7, 8, 9, 10."""

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from config import app_state, STORAGE_DIR

router = APIRouter()


# ── 8. Поиск источников по нише ─────────────────────────────────

@router.get('/growth/search_sources')
async def search_sources(q: str, count: int = 20):
    """Поиск VK-сообществ по ключевому слову."""
    try:
        from vk.api import get_vk_api, vk_call_safe
        vk_cfg = app_state.profile.get('vk', {})
        token = vk_cfg.get('user_token', '').strip()
        if not token:
            return {'status': 'error', 'message': 'User Token не задан'}

        vk = get_vk_api(token, vk_cfg.get('api_version', '5.131'))
        resp = vk_call_safe(
            vk.groups.search,
            q=q, count=min(count, 50), type='page',
            sort=6,  # по числу подписчиков
            fields=['members_count', 'activity']
        )
        groups = resp.get('items', []) if isinstance(resp, dict) else []
        result = []
        for g in groups:
            result.append({
                'id':       str(g.get('id', '')),
                'name':     g.get('name', ''),
                'members':  g.get('members_count', 0),
                'activity': g.get('activity', ''),
                'is_closed': g.get('is_closed', 0),
            })
        return {'status': 'ok', 'groups': result}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


# ── 4. Рейтинг источников ────────────────────────────────────────

def _stats_file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'source_stats.json'


def load_source_stats() -> dict:
    f = _stats_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def save_source_stats(data: dict):
    f = _stats_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data), encoding='utf-8')


def update_source_stat(cid: str, downloaded: int, avg_likes: float, avg_views: float):
    stats = load_source_stats()
    if cid not in stats:
        stats[cid] = {'downloads': 0, 'avg_likes': 0, 'avg_views': 0, 'last_run': ''}
    s = stats[cid]
    s['downloads'] = s.get('downloads', 0) + downloaded
    # Скользящее среднее
    alpha = 0.3
    if s.get('avg_likes', 0) == 0:
        s['avg_likes'] = round(avg_likes, 1)
        s['avg_views'] = round(avg_views, 1)
    else:
        s['avg_likes'] = round(s['avg_likes'] * (1 - alpha) + avg_likes * alpha, 1)
        s['avg_views'] = round(s['avg_views'] * (1 - alpha) + avg_views * alpha, 1)
    s['last_run'] = datetime.now().strftime('%d.%m %H:%M')
    save_source_stats(stats)


@router.get('/growth/source_stats')
async def get_source_stats():
    stats = load_source_stats()
    sources = app_state.profile.get('sources', [])
    result = []
    for src in sources:
        cid = str(src.get('community_id', ''))
        s = stats.get(cid, {})
        result.append({
            'cid':       cid,
            'name':      src.get('name', cid),
            'enabled':   src.get('enabled', True),
            'downloads': s.get('downloads', 0),
            'avg_likes': s.get('avg_likes', 0),
            'avg_views': s.get('avg_views', 0),
            'last_run':  s.get('last_run', '—'),
        })
    result.sort(key=lambda x: x['avg_likes'], reverse=True)
    return {'status': 'ok', 'stats': result}


# ── 7. Трекинг после публикации ──────────────────────────────────

@router.get('/growth/tracker')
async def get_tracker():
    from services.tracker import get_summary
    return {'status': 'ok', **get_summary()}


@router.post('/growth/tracker/check_now')
async def tracker_check_now():
    from services.tracker import run_check
    threading.Thread(target=run_check, daemon=True).start()
    return {'status': 'ok', 'message': 'Проверка запущена в фоне'}


# ── 5. Переиспользование топ-контента ────────────────────────────

@router.post('/growth/recycle')
async def recycle_top():
    """Взять топ посты из трекера и переложить их в очередь заново."""
    profile = app_state.profile
    recycle_cfg = profile.get('recycle', {})
    if not recycle_cfg.get('enabled', False):
        return {'status': 'error', 'message': 'Рециклинг отключён в настройках'}

    from services.tracker import get_all
    from vk.api import get_vk_api, vk_call_safe, get_best_photo_url
    from vk.upload import download_photos_for_post

    min_days  = int(recycle_cfg.get('min_days', 30))
    min_likes = int(recycle_cfg.get('min_likes', 50))
    max_run   = int(recycle_cfg.get('max_per_run', 5))
    now = int(time.time())

    candidates = [
        p for p in get_all()
        if p.get('checked')
        and p.get('likes', 0) >= min_likes
        and (now - p.get('published_at', now)) >= min_days * 86400
    ]
    candidates.sort(key=lambda p: p.get('likes', 0), reverse=True)
    candidates = candidates[:max_run]

    if not candidates:
        return {'status': 'ok', 'message': 'Нет постов для рециклинга (проверь min_likes и min_days)', 'recycled': 0}

    vk_cfg = profile.get('vk', {})
    token = vk_cfg.get('user_token', '').strip()
    if not token:
        return {'status': 'error', 'message': 'User Token не задан'}

    vk = get_vk_api(token, vk_cfg.get('api_version', '5.131'))
    recycled = 0

    for p in candidates:
        try:
            ids = f'{p["owner_id"]}_{p["post_id"]}'
            resp = vk_call_safe(vk.wall.getById, posts=ids, extended=0)
            items = (resp.get('items', []) if isinstance(resp, dict) else resp) or []
            if not items:
                continue
            post = items[0]
            photos = [a for a in post.get('attachments', []) if a.get('type') == 'photo']
            if not photos:
                continue

            cid = str(p.get('source_cid', 'recycled'))
            post_id = post.get('id')
            local = download_photos_for_post(cid, post_id, photos)
            if not local:
                continue

            post['_local_photos'] = local
            post['_recycled'] = True

            fname = app_state.posts_dir / f'recycled_{cid}_{post_id}.json'
            fname.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding='utf-8')
            recycled += 1
            app_state.add_log(f'Рециклинг: добавлен пост {post_id} ({p["likes"]} лайков)', 'info')
        except Exception as e:
            app_state.add_log(f'Рециклинг ошибка: {e}', 'warning')

    return {'status': 'ok', 'recycled': recycled, 'message': f'Добавлено {recycled} постов из топа'}


# ── 10. Проверка подозрительной активности ───────────────────────

@router.get('/growth/phash_size')
async def phash_size():
    from services.phash import cache_size
    return {'status': 'ok', 'size': cache_size()}


@router.post('/growth/phash_clear')
async def phash_clear():
    from services.phash import clear_cache
    clear_cache()
    return {'status': 'ok'}


@router.post('/growth/check_suspicious')
async def check_suspicious():
    """Проверить кол-во подписчиков и средний охват."""
    try:
        from vk.api import get_vk_api, vk_call_safe
        from services.tracker import get_summary

        profile = app_state.profile
        vk_cfg = profile.get('vk', {})
        token = vk_cfg.get('user_token', '').strip()
        gid   = vk_cfg.get('group_id', '').strip()
        if not token or not gid:
            return {'status': 'error', 'message': 'Токены не заданы'}

        vk = get_vk_api(token, vk_cfg.get('api_version', '5.131'))
        resp = vk_call_safe(vk.groups.getById, group_id=gid.lstrip('-'), fields='members_count')
        group = (resp[0] if isinstance(resp, list) and resp else resp) or {}
        members = group.get('members_count', 0)

        summary = get_summary()
        alerts = []

        # Кэш предыдущего кол-ва подписчиков
        cache_f = STORAGE_DIR / app_state.active_profile_id / 'members_cache.json'
        prev = {}
        if cache_f.exists():
            try:
                prev = json.loads(cache_f.read_text())
            except Exception:
                pass

        prev_members = prev.get('members', members)
        diff = members - prev_members
        cache_f.parent.mkdir(parents=True, exist_ok=True)
        cache_f.write_text(json.dumps({'members': members, 'updated': datetime.now().isoformat()}))

        if prev_members > 0 and diff < 0 and abs(diff) > prev_members * 0.05:
            alerts.append(f'🚨 Подписчики упали на {abs(diff)} ({round(abs(diff)/prev_members*100, 1)}%)')

        if summary['avg_views'] > 0 and summary['checked'] >= 10:
            recent_checked = [p for p in get_summary().get('top', []) if p.get('views', 0) > 0]
            if recent_checked:
                recent_avg = sum(p['views'] for p in recent_checked) / len(recent_checked)
                if recent_avg < summary['avg_views'] * 0.4:
                    alerts.append(f'⚠️ Средний охват упал до {int(recent_avg)} (раньше {summary["avg_views"]})')

        return {
            'status': 'ok',
            'members': members,
            'members_diff': diff,
            'avg_views': summary['avg_views'],
            'avg_likes': summary['avg_likes'],
            'alerts': alerts,
        }
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
