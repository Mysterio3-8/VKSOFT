# -*- coding: utf-8 -*-
"""Видео-воркер: скачать mp4 из VK → перезалить в группу → wall post."""

import json
import random
import time
from pathlib import Path

import requests as req_lib
import vk_api

from config import app_state, STORAGE_DIR
from vk.api import get_vk_api, vk_call_safe, normalize_owner_id, send_critical_alert


# ── Seen IDs ──────────────────────────────────────────────────────

def _seen_file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'seen_videos.json'


def _load_seen() -> set:
    f = _seen_file()
    if f.exists():
        try:
            return set(json.loads(f.read_text(encoding='utf-8')))
        except Exception:
            pass
    return set()


def _add_seen(key: str):
    seen = _load_seen()
    seen.add(key)
    if len(seen) > 10000:
        seen = set(list(seen)[-8000:])
    try:
        f = _seen_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(list(seen)), encoding='utf-8')
    except Exception:
        pass


# ── Внешние embed-видео ───────────────────────────────────────────

def _is_external_video(video: dict) -> bool:
    """True для внешних embed-видео (Coub/Vimeo/YouTube).

    У них в `files` есть только `external` и нет `mp4_*`. Их нельзя скачать
    как нативный VK mp4 — yt-dlp падает (Coub → KeyError('params'),
    Vimeo → HTTP 401). Качать такое бессмысленно, пропускаем заранее.
    """
    files = video.get('files') or {}
    if not files:
        return False
    has_mp4 = any(k.startswith('mp4_') for k in files)
    return bool(files.get('external')) and not has_mp4


# ── Скачать mp4 через yt-dlp ──────────────────────────────────────

def _download_video(video_owner: int, video_id: int, dest: Path,
                    quality: str = '720', max_mb: int = 500) -> bool:
    """Скачать VK-видео через yt-dlp по публичному URL."""
    url = f'https://vk.com/video{video_owner}_{video_id}'
    # Высота качества
    try:
        h = int(quality)
    except ValueError:
        h = 720

    ydl_opts = {
        'format': f'best[ext=mp4][height<={h}]/best[height<={h}]/best',
        'outtmpl': str(dest.with_suffix('')),   # yt-dlp добавит расширение
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        },
    }

    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # yt-dlp может добавить расширение .mp4 или .webm
            actual = Path(ydl.prepare_filename(info))
            if actual.exists() and actual != dest:
                actual.rename(dest)
            elif not dest.exists():
                # Попробуем найти скачанный файл рядом
                for ext in ('.mp4', '.webm', '.mkv'):
                    candidate = dest.with_suffix(ext)
                    if candidate.exists():
                        candidate.rename(dest)
                        break

        if not dest.exists():
            return False

        size_mb = dest.stat().st_size / 1024 / 1024
        if size_mb > max_mb:
            app_state.add_log(f'Видео: {size_mb:.0f}МБ > лимита {max_mb}МБ, пропускаю', 'warning')
            dest.unlink(missing_ok=True)
            return False
        return True

    except Exception as e:
        app_state.add_log(f'Видео скачивание {video_owner}_{video_id}: {e}', 'warning')
        dest.unlink(missing_ok=True)
        return False


# ── Загрузить видео в группу ──────────────────────────────────────

def _upload_video(vk_user, gid_num: int, video_path: Path, title: str, desc: str,
                  is_clip: bool = False) -> tuple:
    """Вернуть (owner_id, video_id) или (None, None)."""
    params = {
        'name': title[:120],
        'description': desc[:1000] if desc else '',
        'group_id': gid_num,
        'wallpost': 0,
        'is_private': 0,
    }
    if is_clip:
        params['is_reels'] = 1

    save_resp = vk_call_safe(vk_user.video.save, **params)
    upload_url = save_resp.get('upload_url')
    if not upload_url:
        return None, None

    with open(video_path, 'rb') as fh:
        up_resp = req_lib.post(
            upload_url,
            files={'video_file': (video_path.name, fh, 'video/mp4')},
            timeout=600,
        ).json()

    vid_id   = up_resp.get('video_id') or save_resp.get('video_id')
    owner_id = up_resp.get('owner_id') or save_resp.get('owner_id') or f'-{gid_num}'
    return owner_id, vid_id


# ── Основная логика скачивания ────────────────────────────────────

def _download_videos_source(community_id: str, count: int,
                             max_duration: int = 0, max_mb: int = 500,
                             quality: str = '720', is_clips_mode: bool = False):
    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    api_ver = vk_cfg.get('api_version', '5.131')

    flag = 'is_downloading_clips' if is_clips_mode else 'is_downloading_videos'
    queue_dir = app_state.clips_queue_dir if is_clips_mode else app_state.videos_queue_dir
    files_dir = app_state.clip_files_dir  if is_clips_mode else app_state.video_files_dir

    if not user_token:
        app_state.add_log(f'{"Клипы" if is_clips_mode else "Видео"}: User Token не задан', 'error')
        return

    vk = get_vk_api(user_token, api_ver)
    owner_id = normalize_owner_id(community_id)
    seen = _load_seen() if not is_clips_mode else _load_clips_seen()
    downloaded = skipped = 0
    offset = 0
    label = 'Клипы' if is_clips_mode else 'Видео'

    app_state.add_log(f'{label}: загрузка {count} из {owner_id}', 'info')
    from workers.media_autopilot import _set_progress
    progress_type = 'clips' if is_clips_mode else 'videos'
    _set_progress(progress_type, phase='download', current=0, total=count, label=f'Загрузка из {owner_id}')

    while downloaded < count and getattr(app_state, flag):
        try:
            resp = vk_call_safe(
                vk.video.get,
                owner_id=owner_id,
                count=min(200, count - downloaded),
                offset=offset,
                extended=1,
            )
        except vk_api.exceptions.ApiError as e:
            code = getattr(e, 'code', 0)
            if code == 204:
                app_state.add_log(f'{label} {owner_id}: нет доступа к видео источника (204)', 'info')
                break
            app_state.add_log(f'{label} VK API {code}: {e}', 'error')
            if code in (5, 28):
                send_critical_alert(f'Токен недействителен ({code}). {label} остановлен.')
                setattr(app_state, flag, False)
            break

        items = (resp.get('items', []) if isinstance(resp, dict) else [])
        if not items:
            app_state.add_log(f'{label} {owner_id}: больше нет', 'info')
            break

        for video in items:
            if not getattr(app_state, flag) or downloaded >= count:
                break

            vid_id   = video.get('id')
            vid_owner = video.get('owner_id')
            key = f'{vid_owner}_{vid_id}'

            if key in seen:
                skipped += 1
                continue

            if _is_external_video(video):
                skipped += 1
                continue

            duration = video.get('duration', 0)
            # Для клипов фильтруем по длительности
            if is_clips_mode:
                if max_duration > 0 and duration > max_duration:
                    skipped += 1
                    continue
                if duration > 180:
                    skipped += 1
                    continue
            else:
                if duration < 10:
                    skipped += 1
                    continue

            dest = files_dir / f'{key}.mp4'
            if not _download_video(vid_owner, vid_id, dest, quality, max_mb):
                skipped += 1
                continue

            # pHash дедупликация по первому кадру (видео/клипы)
            phash_cfg = profile.get('phash', {})
            if phash_cfg.get('enabled', False):
                from services.phash import hash_video_frame, is_duplicate, add_to_cache
                frame_hash = hash_video_frame(dest)
                if frame_hash:
                    if is_duplicate(dest, int(phash_cfg.get('threshold', 10)), precomputed_hash=frame_hash):
                        app_state.add_log(f'{label}: дубликат по кадру, пропускаю {dest.name}', 'info')
                        dest.unlink(missing_ok=True)
                        skipped += 1
                        continue
                    add_to_cache(dest, f'video_{key}', precomputed_hash=frame_hash)

            meta = {
                'id': vid_id,
                'owner_id': vid_owner,
                'title': video.get('title', ''),
                'description': video.get('description', ''),
                'duration': duration,
                '_local_file': str(dest),
                '_source_cid': community_id,
                '_is_clip': is_clips_mode,
            }
            meta_file = queue_dir / f'{key}.json'
            meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')

            if is_clips_mode:
                _add_clips_seen(key)
            else:
                _add_seen(key)

            downloaded += 1
            _set_progress(progress_type, phase='download', current=downloaded, total=count, label=f'Скачано {downloaded} из {count}')
            if downloaded % 5 == 0 or downloaded == 1:
                app_state.add_log(f'{label} [{owner_id}] {downloaded}/{count}', 'info')

            time.sleep(random.uniform(1, 3))

        offset += len(items)
        if len(items) < 200:
            break

    app_state.add_log(f'{label} [{owner_id}]: {downloaded} скачано, {skipped} пропущено', 'info')
    return downloaded


def download_videos_worker():
    profile = app_state.profile
    sources = profile.get('sources', [])
    cfg = profile.get('videos_settings', {})
    count  = int(cfg.get('videos_download_per_run', cfg.get('videos_per_run', 10)))
    max_mb = int(cfg.get('max_filesize_mb', 500))
    quality = cfg.get('quality', '720')

    enabled_count = sum(1 for s in sources if s.get('enabled'))
    if not enabled_count:
        app_state.add_log('Видео: нет активных источников', 'warning')
        app_state.is_downloading_videos = False
        return
    try:
        from workers.download import eligible_sources_in_season, per_source_download_count
        eligible = eligible_sources_in_season(sources)
        if not eligible:
            app_state.add_log('Видео: все источники в стоп-листе', 'warning')
            return
        blocked = enabled_count - len(eligible)
        if blocked:
            app_state.add_log(f'Видео: пропущено стоп-источников {blocked}', 'info')
        total = len(eligible)
        remaining = count
        for i, src in enumerate(eligible, 1):
            if not app_state.is_downloading_videos or remaining <= 0:
                break
            cid = str(src.get('community_id', ''))
            name = src.get('name', cid)
            per = per_source_download_count(remaining, total - i + 1)
            app_state.add_log(f'Видео: канал {i}/{total} «{name}» — беру до {per}', 'info')
            got = int(_download_videos_source(cid, per, max_mb=max_mb, quality=quality, is_clips_mode=False) or 0)
            remaining = max(0, remaining - got)
    except Exception as e:
        app_state.add_log(f'Видео загрузка: {e}', 'error')
    finally:
        app_state.is_downloading_videos = False


# ── Публикация видео ──────────────────────────────────────────────

def publish_videos_worker(count: int, is_clips_mode: bool = False):
    label = 'Клипы' if is_clips_mode else 'Видео'
    flag  = 'is_publishing_clips' if is_clips_mode else 'is_publishing_videos'
    queue_dir = app_state.clips_queue_dir if is_clips_mode else app_state.videos_queue_dir
    cfg_key   = 'clips_settings' if is_clips_mode else 'videos_settings'

    try:
        profile = app_state.profile
        vk_cfg = profile.get('vk', {})
        cfg = profile.get(cfg_key, {})

        user_token  = vk_cfg.get('user_token', '').strip()
        group_token = vk_cfg.get('group_token', '').strip()
        group_id    = vk_cfg.get('group_id', '').strip()
        api_ver     = vk_cfg.get('api_version', '5.131')

        if not user_token or not group_id:
            app_state.add_log(f'{label} публикация: токены не заданы', 'error')
            return

        vk_user  = get_vk_api(user_token, api_ver)
        vk_group = get_vk_api(group_token, api_ver) if group_token else vk_user
        gid_num  = int(group_id.lstrip('-'))
        owner_id = f'-{gid_num}'

        create_wall = cfg.get('create_wall_post', True)
        delay_min   = int(cfg.get('publish_delay_min', 3600))
        delay_max   = int(cfg.get('publish_delay_max', 7200))
        if delay_min > delay_max:
            delay_min, delay_max = delay_max, delay_min

        queue = sorted(queue_dir.glob('*.json'))[:count]
        if not queue:
            app_state.add_log(f'{label}: очередь пуста', 'warning')
            return

        app_state.add_log(f'{label}: публикация {len(queue)}', 'info')
        from workers.media_autopilot import _set_progress
        published = failed = 0
        media_type = 'clips' if is_clips_mode else 'videos'
        _set_progress(media_type, phase='publish', current=0, total=len(queue), label=f'Публикация 0 из {len(queue)}')

        for index, meta_file in enumerate(queue, 1):
            if not getattr(app_state, flag):
                break
            _set_progress(media_type, phase='publish', current=index - 1, total=len(queue), label=f'Публикация {index} из {len(queue)}')
            try:
                meta = json.loads(meta_file.read_text(encoding='utf-8'))
                video_path = Path(meta.get('_local_file', ''))

                if not video_path.exists():
                    app_state.add_log(f'{label}: файл не найден {video_path.name}', 'warning')
                    meta_file.unlink(missing_ok=True)
                    continue

                # Антиплагиат: кроп, вырез, лого, скорость, фейды, blur-плашки
                try:
                    from services.media_pipeline import process_video
                    if process_video(
                        video_path, profile,
                        title=meta.get('title', ''),
                        is_clip=is_clips_mode,
                    ):
                        app_state.add_log(f'{label}: антиплагиат применён к {video_path.name}', 'info')
                except Exception as e:
                    app_state.add_log(f'{label}: обработка видео {e}', 'warning')

                # Hook-текст поверх клипа (slideshow получает оверлей при сборке)
                overlay_family = meta.get('overlay_family', '')
                if is_clips_mode and not overlay_family:
                    try:
                        from services.clip_assembler import apply_overlay_from_profile
                        overlay_family = apply_overlay_from_profile(video_path, profile) or ''
                        if overlay_family:
                            app_state.add_log(f'{label}: hook-оверлей ({overlay_family})', 'info')
                    except Exception as e:
                        app_state.add_log(f'{label}: оверлей {e}', 'warning')

                # Своя подпись вместо оригинального текста источника: идёт и в
                # описание видео/клипа (его видно под рилсом), и в запись на
                # стене. Раньше в video.save уходили title/description исходника
                # — на клипах оставался чужой текст.
                from services.content_library import compose_caption_with_meta
                processing = profile.get('processing', {})
                # Для видео и клипов — клиповые веса семейств (CTA важнее)
                text, caption_meta = compose_caption_with_meta(
                    '',
                    add_tags=True,
                    profile_tags=processing.get('hashtags', []),
                    add_profile_tags=processing.get('add_hashtags', False),
                    media_format='clip',
                )
                own_title = (text.split('\n', 1)[0][:100].strip()
                             or ('Клип' if is_clips_mode else 'Видео'))

                vid_owner, vid_id = _upload_video(
                    vk_user, gid_num, video_path,
                    title=own_title,
                    desc=text,
                    is_clip=is_clips_mode,
                )
                if not vid_id:
                    app_state.add_log(f'{label}: загрузка не удалась', 'error')
                    failed += 1
                    from services.publish_log import log_publish_event
                    log_publish_event(media_type=media_type, status='failed', extra={'reason': 'upload_failed'})
                    continue

                att = f'video{vid_owner}_{vid_id}'

                if create_wall:
                    from services.slot_scheduler import reserve_slot
                    next_ts = reserve_slot(media_type, delay_min, delay_max)

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
                        media_type=media_type,
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
                                media_type=meta.get('media_kind')
                                or ('clip' if is_clips_mode else 'video'),
                                overlay_family=overlay_family,
                            )
                        except Exception:
                            pass
                    from datetime import datetime
                    app_state.add_log(
                        f'{label}: → {datetime.fromtimestamp(next_ts).strftime("%d.%m %H:%M")}',
                        'info'
                    )

                video_path.unlink(missing_ok=True)
                meta_file.unlink(missing_ok=True)
                published += 1

            except vk_api.exceptions.ApiError as e:
                code = getattr(e, 'code', 0)
                app_state.add_log(f'{label} VK API {code}: {e}', 'error')
                failed += 1
                if code in (5, 28):
                    setattr(app_state, flag, False)
                    break
            except Exception as e:
                app_state.add_log(f'{label} ошибка поста: {e}', 'error')
                failed += 1

        _set_progress(media_type, phase='publish', current=published + failed, total=len(queue), label=f'Опубликовано {published}, ошибок {failed}')
        app_state.add_log(f'{label}: {published} опубликовано, {failed} ошибок', 'info')
        if published > 0 and profile.get('storage_cleanup', {}).get('clean_orphans_after_run', True):
            try:
                from services.cleanup_storage import cleanup_junk
                junk = cleanup_junk()
                removed = sum(int(v or 0) for v in junk.values())
                if removed:
                    app_state.add_log(f'{label} автоочистка: удалено {removed} остаточных файлов/папок', 'info')
            except Exception as e:
                app_state.add_log(f'{label} автоочистка: {e}', 'warning')

    except Exception as e:
        app_state.add_log(f'{label} публикация критическая ошибка: {e}', 'error')
    finally:
        setattr(app_state, flag, False)


# ── Clips seen IDs ────────────────────────────────────────────────

def _clips_seen_file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'seen_clips.json'

def _load_clips_seen() -> set:
    f = _clips_seen_file()
    if f.exists():
        try:
            return set(json.loads(f.read_text(encoding='utf-8')))
        except Exception:
            pass
    return set()

def _add_clips_seen(key: str):
    seen = _load_clips_seen()
    seen.add(key)
    if len(seen) > 10000:
        seen = set(list(seen)[-8000:])
    try:
        f = _clips_seen_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(list(seen)), encoding='utf-8')
    except Exception:
        pass


# ── Скачивание топ видео конкурентов по ER ────────────────────────

def download_top_competitor_videos(count: int = 5, is_clips_mode: bool = False) -> int:
    """Скачать топ-видео конкурентов по Engagement Rate.

    Использует данные из competitor_data.json (накопленные competitor_scan_loop).
    Отбирает видео из top20 конкурентов с наивысшим ER, которых ещё нет в seen.
    Возвращает количество скачанных видео.
    """
    from services.competitor import _load_data
    from vk.api import get_vk_api, normalize_owner_id

    profile = app_state.profile
    profile_id = app_state.active_profile_id
    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    if not user_token:
        app_state.add_log('Топ видео конкурентов: user_token не задан', 'error')
        return 0

    cfg_key = 'clips_settings' if is_clips_mode else 'videos_settings'
    cfg = profile.get(cfg_key, {})
    max_mb = int(cfg.get('max_filesize_mb', 500))
    quality = cfg.get('quality', '720')
    max_duration = int(cfg.get('max_duration_sec', 180)) if is_clips_mode else 0

    competitor_data = _load_data(profile_id)
    if not competitor_data:
        app_state.add_log('Топ видео конкурентов: нет данных по конкурентам (сканирование ещё не прошло)', 'warning')
        return 0

    # Собираем кандидатов из top20 каждого конкурента (только посты с видео)
    candidates: list[dict] = []
    for cid, source in competitor_data.items():
        for post in source.get('top20', []):
            if post.get('type') != 'video':
                continue
            candidates.append({
                'cid': cid,
                'post_id': post['post_id'],
                'er': post['er'],
                'owner_id': int(normalize_owner_id(cid).replace('-', '-')),
            })

    # Сортируем по ER, берём лучших
    candidates.sort(key=lambda x: x['er'], reverse=True)

    seen = _load_seen() if not is_clips_mode else _load_clips_seen()
    queue_dir = app_state.clips_queue_dir if is_clips_mode else app_state.videos_queue_dir
    files_dir = app_state.clip_files_dir if is_clips_mode else app_state.video_files_dir
    label = 'Топ клипы' if is_clips_mode else 'Топ видео'

    try:
        vk = get_vk_api(user_token, vk_cfg.get('api_version', '5.131'))
    except Exception as e:
        app_state.add_log(f'{label}: VK API init error: {e}', 'error')
        return 0

    downloaded = 0
    for cand in candidates:
        if downloaded >= count:
            break

        cid = cand['cid']
        post_id = cand['post_id']

        # Получаем видео-аттачменты поста
        try:
            from vk.api import vk_call_safe, normalize_owner_id
            owner_str = normalize_owner_id(cid)
            resp = vk_call_safe(
                vk.wall.getById,
                posts=f'{owner_str}_{post_id}',
                extended=0,
            )
            items = resp.get('items', []) if isinstance(resp, dict) else (resp or [])
            if not items:
                continue
            post = items[0]
            atts = post.get('attachments', [])
            vid_atts = [a for a in atts if a.get('type') == 'video']
        except Exception as e:
            app_state.add_log(f'{label}: getById {cid}_{post_id}: {e}', 'warning')
            continue

        for va in vid_atts:
            vid_obj = va.get('video', {})
            vid_id = vid_obj.get('id')
            vid_owner = vid_obj.get('owner_id')
            if not vid_id or not vid_owner:
                continue

            key = f'{vid_owner}_{vid_id}'
            if key in seen:
                continue

            if _is_external_video(vid_obj):
                continue

            duration = vid_obj.get('duration', 0)
            if is_clips_mode:
                if duration > 180 or (max_duration > 0 and duration > max_duration):
                    continue
            else:
                if duration < 10:
                    continue

            dest = files_dir / f'{key}.mp4'
            if not _download_video(vid_owner, vid_id, dest, quality, max_mb):
                continue

            meta = {
                'id': vid_id,
                'owner_id': vid_owner,
                'title': vid_obj.get('title', ''),
                'description': vid_obj.get('description', ''),
                'duration': duration,
                '_local_file': str(dest),
                '_source_cid': cid,
                '_is_clip': is_clips_mode,
                '_competitor_er': cand['er'],
            }
            meta_file = queue_dir / f'{key}.json'
            meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')

            if is_clips_mode:
                _add_clips_seen(key)
            else:
                _add_seen(key)

            downloaded += 1
            app_state.add_log(
                f'{label}: скачал {key} (ER={cand["er"]:.2f}%, из {cid})',
                'info'
            )
            time.sleep(random.uniform(1, 2))
            break  # один видео на пост

    app_state.add_log(f'{label} конкурентов: {downloaded} скачано', 'info')
    return downloaded
