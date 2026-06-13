# -*- coding: utf-8 -*-
"""Повтор победителей: переиздание лучших постов после остывания.

Пост, набравший охват, через cooldown публикуется снова: фото скачиваются
со своей же стены, проходят антиплагиат (файлы становятся визуально другими)
и ставятся в отложку со свежей подписью из библиотеки.
"""

import json
import os
import random
import shutil
import time
from pathlib import Path

import requests as req_lib

from config import STORAGE_DIR, app_state, logger

CHECK_INTERVAL_SEC = 3600

DEFAULT_SETTINGS = {
    # Включён по умолчанию: пока нет постов с нужным охватом, цикл просто
    # ничего не находит и ждёт — включать руками не нужно.
    'enabled': True,
    'every_days': 7,      # как часто переиздавать по одному победителю
    'min_views': 200,     # порог охвата для статуса «победитель»
    'cooldown_days': 30,  # сколько пост должен остыть до повтора
}


def load_settings(profile: dict) -> dict:
    cfg = dict(DEFAULT_SETTINGS)
    saved = profile.get('repeat_winners')
    if isinstance(saved, dict):
        cfg.update(saved)
    return cfg


def _state_file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'repeat_winners.json'


def _load_state() -> dict:
    f = _state_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    f = _state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.parent / f'.tmp_{f.name}'
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, f)


def pick_winner(data: list, now: int, min_views: int, cooldown_days: int) -> dict | None:
    """Лучший проверенный пост: набрал охват, остыл и не переиздавался недавно."""
    from services.tracker import caption_engagement_score

    cooldown = cooldown_days * 86400
    candidates = [
        p for p in data
        if p.get('checked') and not p.get('missing')
        and int(p.get('views', 0) or 0) >= min_views
        and now - int(p.get('published_at', 0) or 0) >= cooldown
        and now - int(p.get('republished_at', 0) or 0) >= cooldown
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda p: (caption_engagement_score(p), int(p.get('views', 0) or 0)),
    )


def _download_post_photos(items: list, tmp_dir: Path) -> list[Path]:
    """Скачать фото поста со своей стены в tmp_dir (до 5 штук)."""
    from vk.api import get_best_photo_url

    paths: list[Path] = []
    photo_attachments = [
        a for a in (items or []) if a.get('type') == 'photo'
    ][:5]
    for i, attach in enumerate(photo_attachments):
        url = get_best_photo_url(attach.get('photo', {}))
        if not url:
            continue
        try:
            resp = req_lib.get(url, timeout=30)
            resp.raise_for_status()
            p = tmp_dir / f'winner_{i}.jpg'
            p.write_bytes(resp.content)
            paths.append(p)
        except Exception as e:
            app_state.add_log(f'[Повтор] Фото {i} не скачалось: {e}', 'warning')
    return paths


def run_repeat_winner() -> dict:
    """Переиздать одного победителя. Возвращает отчёт для API/логов."""
    from services.tracker import get_all, mark_republished
    from vk.api import get_vk_api, vk_call_safe

    profile = app_state.profile
    cfg = load_settings(profile)
    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    group_token = vk_cfg.get('group_token', '').strip()
    group_id = str(vk_cfg.get('group_id', '')).strip().lstrip('-')
    if not user_token or not group_token or not group_id:
        return {'status': 'error', 'message': 'Токены не заданы'}

    now = int(time.time())
    winner = pick_winner(get_all(), now, int(cfg['min_views']), int(cfg['cooldown_days']))
    if not winner:
        return {'status': 'skip', 'message': 'Нет остывших победителей (порог views или cooldown)'}

    api_ver = vk_cfg.get('api_version', '5.131')
    vk_user = get_vk_api(user_token, api_ver)
    vk_group = get_vk_api(group_token, api_ver)
    gid_num = int(group_id)
    owner_id = f'-{gid_num}'

    resp = vk_call_safe(vk_user.wall.getById, posts=f'{owner_id}_{winner["post_id"]}')
    items = (resp.get('items', []) if isinstance(resp, dict) else resp) or []
    if not items:
        # Пост удалён со стены — больше не предлагать его в победители
        mark_republished(winner['post_id'], now)
        return {'status': 'skip', 'message': f'Пост {winner["post_id"]} не найден на стене'}

    tmp_dir = STORAGE_DIR / app_state.active_profile_id / 'tmp_repeat'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        photos = _download_post_photos(items[0].get('attachments', []), tmp_dir)
        if not photos:
            mark_republished(winner['post_id'], now)
            return {'status': 'skip', 'message': f'У поста {winner["post_id"]} нет фото для повтора'}

        # Антиплагиат: повтор уходит на стену визуально другим файлом
        try:
            from services.media_pipeline import process_photos
            process_photos([str(p) for p in photos], profile)
        except Exception as e:
            app_state.add_log(f'[Повтор] Антиплагиат: {e}', 'warning')

        from vk.upload import upload_photo_from_file
        attachments = []
        for p in photos:
            att = upload_photo_from_file(vk_user, gid_num, p)
            if att:
                attachments.append(att)
        if not attachments:
            return {'status': 'error', 'message': 'Фото не загрузились в VK'}

        from services.content_library import compose_caption_with_meta
        processing = profile.get('processing', {})
        text, caption_meta = compose_caption_with_meta(
            '',
            add_tags=True,
            profile_tags=processing.get('hashtags', []),
            add_profile_tags=True,
            media_format='photo',
        )

        from services.storage import read_last_scheduled, write_last_scheduled
        pub_cfg = profile.get('publishing_settings', {})
        delay_min = int(pub_cfg.get('publish_delay_min', 3600))
        delay_max = int(pub_cfg.get('publish_delay_max', 7200))
        if delay_min > delay_max:
            delay_min, delay_max = delay_max, delay_min
        next_ts = max(read_last_scheduled() or now, now) + random.randint(delay_min, delay_max)

        result = vk_call_safe(
            vk_group.wall.post,
            owner_id=owner_id,
            from_group=1,
            message=text,
            attachments=','.join(attachments),
            publish_date=next_ts,
        )
        new_post_id = result.get('post_id') if isinstance(result, dict) else None
        if not new_post_id:
            return {'status': 'error', 'message': 'wall.post не вернул post_id'}

        write_last_scheduled(next_ts)
        mark_republished(winner['post_id'], now)
        try:
            from services.tracker import track as _track
            _track(
                new_post_id, owner_id, '',
                published_at=next_ts,
                caption_category=caption_meta.get('caption_category', ''),
                caption_text=caption_meta.get('caption_text', ''),
                caption_id=caption_meta.get('caption_id', ''),
                media_type='photo',
            )
        except Exception:
            pass

        msg = (
            f'Победитель {winner["post_id"]} (views={winner.get("views", 0)}) '
            f'переиздан как {new_post_id}'
        )
        app_state.add_log(f'[Повтор] {msg}', 'info')
        return {'status': 'ok', 'message': msg, 'new_post_id': new_post_id}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def repeat_winners_loop():
    """Фоновый поток: раз в every_days переиздаёт одного победителя."""
    time.sleep(300)  # дать трекеру и боту подняться
    while True:
        try:
            cfg = load_settings(app_state.profile)
            if cfg.get('enabled'):
                state = _load_state()
                last_run = int(state.get('last_run', 0))
                if time.time() - last_run >= int(cfg['every_days']) * 86400:
                    report = run_repeat_winner()
                    state['last_run'] = int(time.time())
                    state['last_report'] = report
                    _save_state(state)
        except Exception as e:
            logger.warning(f'repeat_winners_loop: {e}')
            app_state.add_log(f'[Повтор] Ошибка цикла: {e}', 'error')
        time.sleep(CHECK_INTERVAL_SEC)
