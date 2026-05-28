# -*- coding: utf-8 -*-
"""Growth extra API — Stories, гивэвей, пин, трекинг подписчиков."""

import threading
from fastapi import APIRouter
from config import app_state

router = APIRouter()


@router.get('/growth/subscribers')
async def get_subscribers():
    from workers.growth_tasks import get_growth_stats, track_subscribers_once
    stats = get_growth_stats()
    if not stats.get('members'):
        # Попробовать свежие данные
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
    gt = vk_cfg.get('group_token', '').strip()
    gid = vk_cfg.get('group_id', '').strip()
    if not gt or not gid:
        return {'status': 'error', 'message': 'Group Token и Group ID не заданы'}

    vk = get_vk_api(gt, vk_cfg.get('api_version', '5.131'))
    owner_id = f'-{gid.lstrip("-")}'
    prize = data.get('prize', '')
    days  = int(data.get('days', 7))

    def _run():
        post_giveaway(vk, owner_id, prize or None, days)

    threading.Thread(target=_run, daemon=True).start()
    return {'status': 'ok', 'message': 'Гивэвей публикуется...'}


@router.post('/growth/pin/update')
async def update_pin():
    from workers.growth_tasks import update_pinned_post
    def _run():
        update_pinned_post()
    threading.Thread(target=_run, daemon=True).start()
    return {'status': 'ok', 'message': 'Ищу лучший пост для закрепления...'}
