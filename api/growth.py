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


# ── Обучаемые подписи ────────────────────────────────────────────

@router.get('/growth/caption_stats')
async def caption_stats():
    """Статистика подписей по семействам и форматам + текущие веса выбора."""
    try:
        from services.content_library import load_library
        from services.tracker import get_caption_stats
        lib = load_library()
        return {
            'status': 'ok',
            'stats': {
                'all': get_caption_stats(),
                'photo': get_caption_stats('photo'),
                'clip': get_caption_stats('clip'),
            },
            'category_weights': lib.get('category_weights', {}),
        }
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.get('/growth/post_scores')
async def post_scores():
    """Нормированные score постов + медианные базы по форматам."""
    try:
        from services.tracker import build_format_baselines, get_scored_posts, get_all
        scored = sorted(get_scored_posts(), key=lambda p: p.get('norm_score', 0), reverse=True)
        return {
            'status': 'ok',
            'baselines': build_format_baselines(get_all()),
            'top': scored[:20],
            'bottom': scored[-20:][::-1],
            'total': len(scored),
        }
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.get('/growth/boost_candidates')
async def boost_candidates():
    """Победители для платного буста: score ≥ 2.0 (Scale-порог отчёта)."""
    try:
        from services.tracker import get_scored_posts
        group_id = str(app_state.profile.get('vk', {}).get('group_id', '')).lstrip('-')
        winners = [
            {
                **p,
                'url': f'https://vk.com/wall-{group_id}_{p["post_id"]}',
            }
            for p in get_scored_posts() if p.get('norm_score', 0) >= 2.0
        ]
        winners.sort(key=lambda p: p['norm_score'], reverse=True)
        return {'status': 'ok', 'candidates': winners[:20], 'total': len(winners)}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.get('/growth/weekly_report')
async def weekly_report():
    """Сводка для недельной ревизии: winners/losers, семейства, источники."""
    try:
        from services.content_library import load_library
        from services.source_quality import load_states
        from services.tracker import (
            get_caption_stats,
            get_overlay_stats,
            get_reach_trend,
            get_reach_trend_by_type,
            get_scored_posts,
        )

        week_ago = int(time.time()) - 7 * 86400
        scored = get_scored_posts()
        recent = [p for p in scored if int(p.get('published_at', 0)) >= week_ago]
        recent.sort(key=lambda p: p.get('norm_score', 0), reverse=True)
        return {
            'status': 'ok',
            'posts_week': len(recent),
            'winners': recent[:10],
            'losers': recent[-10:][::-1] if len(recent) > 10 else [],
            'caption_stats': {
                'photo': get_caption_stats('photo'),
                'clip': get_caption_stats('clip'),
            },
            'overlay_stats': get_overlay_stats(),
            'category_weights': load_library().get('category_weights', {}),
            'reach_trend': get_reach_trend(),
            'reach_trend_by_type': get_reach_trend_by_type(),
            'sources': load_states(),
        }
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.get('/growth/source_quality')
async def source_quality():
    """Белые/стоп-листы источников по rolling median score."""
    try:
        from services.source_quality import load_states
        return {'status': 'ok', 'sources': load_states()}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.post('/growth/source_quality_recalc')
async def source_quality_recalc():
    """Пересчитать статусы источников прямо сейчас."""
    try:
        from services.source_quality import update_source_states
        return {'status': 'ok', 'sources': update_source_states()}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


# ── Повтор победителей ───────────────────────────────────────────

@router.post('/growth/repeat_winner_run')
async def repeat_winner_run():
    """Переиздать одного победителя прямо сейчас (вручную)."""
    try:
        from workers.repeat_winners import run_repeat_winner
        return run_repeat_winner()
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.get('/growth/repeat_winners_state')
async def repeat_winners_state():
    """Настройки и последний отчёт цикла повторов."""
    try:
        from workers.repeat_winners import load_settings, _load_state
        return {
            'status': 'ok',
            'settings': load_settings(app_state.profile),
            'state': _load_state(),
        }
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


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

@router.post('/growth/sync_stats')
async def sync_stats():
    """Принудительно подтянуть views/likes по всем постам из VK."""
    import threading

    def _run():
        try:
            from services.tracker import bootstrap_from_wall, run_check
            bootstrap_from_wall()
            run_check()
        except Exception as e:
            app_state.add_log(f'sync_stats: {e}', 'error')

    threading.Thread(target=_run, daemon=True, name='sync_stats_manual').start()
    return {'status': 'ok', 'message': 'Синхронизация запущена в фоне (~30 сек). Обнови дашборд через минуту.'}


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


# ── Learning & Competitor endpoints ──────────────────────────────

@router.get('/growth/learning_state')
async def get_learning_state_api():
    """Текущее состояние обучения бота."""
    try:
        from services.learning import get_learning_state
        state = get_learning_state(app_state.active_profile_id)
        return {'status': 'ok', 'data': state}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.post('/growth/learning_run')
async def trigger_learning():
    """Запустить цикл обучения вручную."""
    try:
        from services.learning import run_learning_cycle
        state = run_learning_cycle()
        return {'status': 'ok', 'data': state}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.get('/growth/competitor_insights')
async def get_competitor_insights_api():
    """Агрегированные инсайты конкурентов."""
    try:
        from services.competitor import get_competitor_insights
        insights = get_competitor_insights(app_state.active_profile_id)
        return {'status': 'ok', 'data': insights}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.post('/growth/competitor_scan')
async def trigger_competitor_scan():
    """Запустить сканирование конкурентов вручную."""
    import threading

    def _run():
        try:
            from services.competitor import scan_all_competitors
            scan_all_competitors()
        except Exception as e:
            app_state.add_log(f'competitor scan: {e}', 'error')

    threading.Thread(target=_run, daemon=True, name='competitor_scan_manual').start()
    return {'status': 'ok', 'message': 'Сканирование запущено в фоне'}


# ── Stories, гивэвей, пин, трекинг подписчиков ───────────────────

@router.get('/growth/subscribers')
async def get_subscribers():
    from workers.growth_tasks import get_growth_stats, track_subscribers_once
    stats = get_growth_stats()
    if not stats.get('members'):
        track_subscribers_once()
        stats = get_growth_stats()
    return {'status': 'ok', **stats}


@router.post('/growth/subscribers/update')
async def update_subscribers():
    from workers.growth_tasks import track_subscribers_once
    point = track_subscribers_once()
    return {'status': 'ok', **point}


@router.post('/growth/stories/post')
async def post_story():
    from workers.stories import auto_post_story_worker
    threading.Thread(target=auto_post_story_worker, args=('photo',), daemon=True).start()
    return {'status': 'ok', 'message': 'Stories фото: публикация запущена'}


@router.post('/growth/stories/video')
async def post_story_video():
    from workers.stories import auto_post_story_worker
    threading.Thread(target=auto_post_story_worker, args=('video',), daemon=True).start()
    return {'status': 'ok', 'message': 'Stories видео: публикация запущена'}


@router.post('/growth/giveaway/post')
async def post_giveaway(data: dict = {}):
    from workers.growth_tasks import post_giveaway
    from vk.api import get_vk_api

    profile = app_state.profile
    vk_cfg  = profile.get('vk', {})
    gt  = vk_cfg.get('group_token', '').strip()
    gid = vk_cfg.get('group_id', '').strip()
    if not gt or not gid:
        return {'status': 'error', 'message': 'Group Token и Group ID не заданы'}

    vk = get_vk_api(gt, vk_cfg.get('api_version', '5.131'))
    owner_id = f'-{gid.lstrip("-")}'
    prize = data.get('prize', '')
    days  = int(data.get('days', 7))

    threading.Thread(target=post_giveaway, args=(vk, owner_id, prize or None, days), daemon=True).start()
    return {'status': 'ok', 'message': 'Гивэвей публикуется...'}


@router.post('/growth/pin/update')
async def update_pin():
    from workers.growth_tasks import update_pinned_post
    threading.Thread(target=update_pinned_post, daemon=True).start()
    return {'status': 'ok', 'message': 'Ищу лучший пост для закрепления...'}
