# -*- coding: utf-8 -*-
"""Safe organic-growth autopilot.

The default path is dry-run only: inspect current sources/queue/statistics and
produce a report. Live publishing is guarded by an explicit config flag.
"""

import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

from config import STORAGE_DIR, app_state
from services.content_library import apply_niche_preset, load_library, save_library
from services.storage import read_last_scheduled


def _report_file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'autopilot_report.json'


def _source_stats_file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'source_stats.json'


def load_last_report() -> Dict:
    if app_state.autopilot_last_report:
        return app_state.autopilot_last_report
    f = _report_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def save_report(report: Dict) -> Dict:
    app_state.autopilot_last_report = report
    f = _report_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def default_profile_patch() -> Dict:
    """Growth defaults that are safe until the user explicitly applies them."""
    return {
        'download_settings': {
            'posts_to_download': 100,
            'delay_min': 0,
            'delay_max': 0,
            'check_duplicates': True,
            'batch_size': 100,
            'max_scan_posts': 400,
            'max_photos_per_post': 2,
        },
        'publishing_settings': {
            'posts_to_publish': 100,
            'publish_delay_min': 10800,
            'publish_delay_max': 18000,
            'postponed_enabled': True,
            'skip_vk_sync': True,
            'publish_hours_enabled': True,
            'publish_hours_start': 8,
            'publish_hours_end': 22,
        },
        'processing': {
            'add_hashtags': True,
            'hashtags': ['#природа', '#красота', '#путешествия', '#земля'],
            'photo_only': False,
            'allow_video': True,
        },
        'filters': {
            'enable_auto_filters': True,
            'block_keywords': [
                'реклама', 'продам', 'скидка', 'купить', 'казино',
                'ставки', 'заработок', '18+', 'подпишись на меня',
            ],
            'block_hashtags': ['#реклама', '#ads', '#ставки'],
            'min_content_length': 0,
        },
        'antiplagiaat': {
            'enabled': True,
            'clear_text': True,
            'max_photos': 4,
            'remove_photo': 'random',
        },
        'engagement': {
            'enabled': True,
            'min_ratio': 0.15,
            'min_likes': 3,
        },
        'peak_hours': {
            'enabled': True,
            'hours': [8, 11, 14, 18, 20, 22],
        },
        'polls': {
            'enabled': True,
            'frequency': 6,
            'is_anonymous': True,
            'multiple': False,
        },
        'autopilot': {
            'enabled': False,
            'dry_run': True,
            'live_enabled': False,
            'cycle_interval_min': 180,
            'target_queue_days': 5,
            'daily_posts_min': 4,
            'daily_posts_max': 8,
            'posts_per_source': 35,
            'max_sources_per_cycle': 5,
            'min_candidate_score': 30,
        },
        'caption_engine': {
            'enabled': True,
            'cta_enabled': True,
            'question_frequency': 4,
            'hashtag_limit': 5,
            'default_niche': 'nature',
        },
        'token_manager': {
            'warn_before_hours': 24,
        },
        'storage_cleanup': {
            'after_publish_success': True,
            'clean_orphans_after_run': True,
            'keep_failed_posts': True,
            'background_enabled': True,
            'background_interval_hours': 12,
            'auto_clean_temp': True,
            'auto_clean_orphans': True,
        },
    }


def apply_growth_defaults() -> Dict:
    """Apply explicit one-click defaults. Does not touch VK tokens or sources."""
    pid = app_state.active_profile_id
    patch = default_profile_patch()
    current = app_state.config['profiles'][pid]
    app_state.config['profiles'][pid] = app_state._deep_merge(current, patch)
    app_state.save_config()

    apply_niche_preset('nature', pid)
    lib = load_library(pid)
    lib['enabled'] = True
    lib['cta_enabled'] = True
    save_library(lib, pid)

    app_state.add_log('Автопилот: безопасные дефолты применены (live выключен)', 'info')
    return patch


def get_status() -> Dict:
    profile = app_state.profile
    cfg = profile.get('autopilot', {})
    return {
        'status': 'ok',
        'running': app_state.is_autopilot,
        'config': cfg,
        'dry_run': cfg.get('dry_run', True),
        'live_enabled': cfg.get('live_enabled', False),
        'last_report': load_last_report(),
    }


def _load_source_stats() -> Dict:
    f = _source_stats_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _count_post_media(post: Dict) -> Tuple[int, int]:
    local_photos = post.get('_local_photos') or []
    photos = len(local_photos)
    videos = len(post.get('_vk_videos') or [])
    if not photos or not videos:
        for att in post.get('attachments', []):
            if not photos and att.get('type') == 'photo':
                photos += 1
            if att.get('type') == 'video':
                videos += 1
    return photos, videos


def _source_key(post: Dict, fallback: str) -> str:
    owner = post.get('owner_id')
    if owner:
        return str(owner).lstrip('-')
    return fallback.split('_')[0].replace('recycled', '').strip('-') or fallback


def _score_post(post: Dict, fname: str, source_stats: Dict) -> Dict:
    likes = _safe_int(post.get('likes', {}).get('count', 0))
    views = _safe_int(post.get('views', {}).get('count', 0))
    reposts = _safe_int(post.get('reposts', {}).get('count', 0))
    comments = _safe_int(post.get('comments', {}).get('count', 0))
    post_ts = _safe_int(post.get('date', 0))
    age_hours = max(0, (int(time.time()) - post_ts) / 3600) if post_ts else 0
    photos, videos = _count_post_media(post)
    text_len = len((post.get('text') or '').strip())
    src = _source_key(post, fname)
    src_stats = source_stats.get(src, {})

    engagement = likes / max(views, 1) * 100 if views else 0
    freshness = max(0, 18 - min(age_hours / 12, 18))
    source_bonus = min(float(src_stats.get('avg_likes', 0)) * 1.2, 18)
    media_bonus = min(photos * 4, 16) + (8 if videos else 0)
    text_bonus = 8 if 20 <= text_len <= 450 else 3 if text_len else 0

    score = (
        20
        + min(views / 120, 24)
        + min(likes * 1.8, 28)
        + min(reposts * 6, 18)
        + min(comments * 4, 16)
        + min(engagement * 10, 18)
        + freshness
        + source_bonus
        + media_bonus
        + text_bonus
    )

    reasons = []
    if photos:
        reasons.append(f'{photos} фото')
    if videos:
        reasons.append('есть видео')
    if likes:
        reasons.append(f'{likes} лайков')
    if views:
        reasons.append(f'{views} просмотров')
    if engagement:
        reasons.append(f'{engagement:.2f}% ER')
    if source_bonus:
        reasons.append('источник уже давал лайки')

    return {
        'file': fname,
        'post_id': post.get('id'),
        'source_id': src,
        'score': round(score, 1),
        'likes': likes,
        'views': views,
        'reposts': reposts,
        'comments': comments,
        'photos': photos,
        'videos': videos,
        'text_preview': (post.get('text') or '').strip()[:180],
        'reasons': reasons[:5],
    }


def _rank_sources(profile: Dict, source_stats: Dict) -> List[Dict]:
    ranked = []
    for src in profile.get('sources', []):
        if not src.get('enabled', True):
            continue
        cid = str(src.get('community_id', '')).strip()
        stat = source_stats.get(cid, {})
        downloads = _safe_int(stat.get('downloads', 0))
        avg_likes = float(stat.get('avg_likes', 0) or 0)
        avg_views = float(stat.get('avg_views', 0) or 0)
        score = 10 + min(avg_likes * 3, 40) + min(avg_views / 250, 35) + min(downloads / 25, 10)
        ranked.append({
            'cid': cid,
            'name': src.get('name', cid),
            'score': round(score, 1),
            'avg_likes': round(avg_likes, 1),
            'avg_views': round(avg_views, 1),
            'downloads': downloads,
            'last_run': stat.get('last_run', ''),
        })
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked


def _stable_choice(items: List, seed: str):
    if not items:
        return None
    rnd = random.Random(seed)
    return items[rnd.randrange(len(items))]


def _caption_preview(candidate: Dict, index: int, profile: Dict) -> Dict:
    cfg = profile.get('caption_engine', {})
    if not cfg.get('enabled', True):
        return {'mode': 'original', 'text': candidate.get('text_preview', ''), 'template_id': 'original'}

    lib = load_library()
    entries = lib.get('entries', [])
    ctas = lib.get('ctas', [])
    seed = f'{candidate.get("source_id")}_{candidate.get("post_id")}_{index}'
    entry = _stable_choice(entries, seed) or {}
    cta = ''
    if cfg.get('cta_enabled', True) and lib.get('cta_enabled', False):
        freq = max(1, _safe_int(cfg.get('question_frequency', 4), 4))
        if index % freq == 0:
            cta = _stable_choice(ctas, seed + '_cta') or ''
    tags = entry.get('tags', '')
    limit = max(1, _safe_int(cfg.get('hashtag_limit', 5), 5))
    if tags:
        tags = ' '.join(tags.split()[:limit])
    parts = [p for p in [entry.get('text', ''), tags, cta] if p]
    return {
        'mode': 'template',
        'template_id': f'nature_{abs(hash(seed)) % 10000}',
        'text': '\n\n'.join(parts)[:500],
    }


def _push_to_publish_window(ts: int, hours: List[int]) -> int:
    if not hours:
        return ts
    hours = sorted(set(_safe_int(h) for h in hours if 0 <= _safe_int(h) <= 23))
    if not hours:
        return ts
    d = datetime.fromtimestamp(ts)
    for h in hours:
        if h > d.hour or (h == d.hour and d.minute < 50):
            return int(d.replace(hour=h, minute=random.randint(0, 50), second=random.randint(0, 59)).timestamp())
    d = d + timedelta(days=1)
    return int(d.replace(hour=hours[0], minute=random.randint(0, 50), second=random.randint(0, 59)).timestamp())


def _schedule_preview(candidates: List[Dict], profile: Dict) -> List[Dict]:
    cfg = profile.get('autopilot', {})
    pub = profile.get('publishing_settings', {})
    daily_max = max(1, _safe_int(cfg.get('daily_posts_max', 8), 8))
    days = max(1, _safe_int(cfg.get('target_queue_days', 5), 5))
    limit = min(len(candidates), daily_max * days, 40)
    if limit <= 0:
        return []

    delay_min = max(60, _safe_int(pub.get('publish_delay_min', 10800), 10800))
    delay_max = max(delay_min, _safe_int(pub.get('publish_delay_max', delay_min), delay_min))
    peak_hours = profile.get('peak_hours', {}).get('hours', [8, 11, 14, 18, 20, 22])
    next_ts = max(read_last_scheduled() or 0, int(time.time())) + random.randint(delay_min, delay_max)

    result = []
    for idx, cand in enumerate(candidates[:limit], 1):
        next_ts = _push_to_publish_window(next_ts, peak_hours)
        result.append({
            'file': cand['file'],
            'post_id': cand.get('post_id'),
            'score': cand['score'],
            'publish_at': datetime.fromtimestamp(next_ts).strftime('%d.%m.%Y %H:%M'),
            'caption': _caption_preview(cand, idx, profile),
        })
        next_ts += random.randint(delay_min, delay_max)
    return result


def build_report(dry_run: bool = True) -> Dict:
    profile = app_state.profile
    cfg = profile.get('autopilot', {})
    source_stats = _load_source_stats()
    enabled_sources = [s for s in profile.get('sources', []) if s.get('enabled', True)]
    queue_files = sorted(
        app_state.posts_dir.glob('*.json'),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    checks = [
        {'name': 'User Token', 'ok': bool(profile.get('vk', {}).get('user_token', '').strip())},
        {'name': 'Group Token', 'ok': bool(profile.get('vk', {}).get('group_token', '').strip())},
        {'name': 'Group ID', 'ok': bool(profile.get('vk', {}).get('group_id', '').strip())},
        {'name': 'Активные источники', 'ok': bool(enabled_sources), 'value': len(enabled_sources)},
        {'name': 'Очередь постов', 'ok': bool(queue_files), 'value': len(queue_files)},
        {'name': 'Live публикация', 'ok': bool(cfg.get('live_enabled', False)), 'value': 'выключена' if not cfg.get('live_enabled') else 'разрешена'},
    ]

    warnings = []
    if not enabled_sources:
        warnings.append('Нет активных источников: автопилот сможет только анализировать текущую очередь.')
    if not queue_files:
        warnings.append('Очередь пустая: сначала нужно скачать посты или включить live-режим вручную.')
    if dry_run:
        warnings.append('Dry-run: ничего не будет опубликовано и очередь не изменится.')

    candidates = []
    for fp in queue_files[:250]:
        try:
            post = json.loads(fp.read_text(encoding='utf-8'))
            candidates.append(_score_post(post, fp.name, source_stats))
        except Exception as e:
            warnings.append(f'Не удалось прочитать {fp.name}: {e}')

    min_score = float(cfg.get('min_candidate_score', 30) or 30)
    candidates = [c for c in candidates if c['score'] >= min_score]
    candidates.sort(key=lambda x: x['score'], reverse=True)
    ranked_sources = _rank_sources(profile, source_stats)
    schedule = _schedule_preview(candidates, profile)

    report = {
        'status': 'ok',
        'dry_run': dry_run,
        'generated_at': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
        'summary': {
            'sources': len(enabled_sources),
            'queue_files': len(queue_files),
            'candidate_count': len(candidates),
            'scheduled_preview': len(schedule),
            'min_candidate_score': min_score,
        },
        'checks': checks,
        'warnings': warnings,
        'top_sources': ranked_sources[:10],
        'top_candidates': candidates[:20],
        'schedule_preview': schedule,
        'actions': [
            'Сначала держать live выключенным и смотреть dry-run отчет.',
            'После проверки токенов и источников применить дефолты ниши, если текущие настройки не важны.',
            'Для live-режима включить autopilot.live_enabled вручную в конфиге и запускать отдельной кнопкой.',
        ],
    }
    return save_report(report)


def run_live_once() -> Dict:
    """Guarded live run: only delegates to the existing stable flow if enabled."""
    profile = app_state.profile
    cfg = profile.get('autopilot', {})
    if not cfg.get('live_enabled', False):
        app_state.add_log('Автопилот: live выключен, выполняю только dry-run', 'warning')
        return build_report(dry_run=True)
    if app_state.is_downloading or app_state.is_publishing:
        return save_report({
            'status': 'error',
            'generated_at': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
            'message': 'Загрузка или публикация уже идет',
        })

    report = build_report(dry_run=False)
    critical_missing = [
        item['name'] for item in report.get('checks', [])
        if item['name'] in ('User Token', 'Group Token', 'Group ID', 'Активные источники') and not item.get('ok')
    ]
    if critical_missing:
        report['status'] = 'error'
        report['message'] = 'Не хватает обязательных настроек: ' + ', '.join(critical_missing)
        return save_report(report)

    try:
        from workers.download import download_then_publish_worker
        app_state.add_log('Автопилот: live запуск через существующий безопасный сценарий', 'info')
        app_state.is_downloading = True
        download_then_publish_worker()
        report['live_result'] = 'download_then_publish finished'
        return save_report(report)
    except Exception as e:
        app_state.add_log(f'Автопилот live: {e}', 'error')
        report['status'] = 'error'
        report['message'] = str(e)
        return save_report(report)
