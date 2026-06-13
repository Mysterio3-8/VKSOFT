# -*- coding: utf-8 -*-
"""Read-only Growth Autopilot logic.

The first slice is deliberately safe: it scores existing/local posts, builds
dry-run reports, and writes only Growth Autopilot report files.
"""

import hashlib
import json
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from config import STORAGE_DIR, app_state


DEFAULT_GROWTH_SETTINGS = {
    'source_mode': 'single',
    'single_source_id': '',
    'preset': 'custom',
    'preset_values': {
        'careful': 4,
        'active': 10,
        'aggressive': 18,
        'max_24': 24,
    },
    'posts_per_day_min': 12,
    'posts_per_day_max': 24,
    'allowed_hours_start': 0,
    'allowed_hours_end': 23,
    'auto_apply_recommendations': True,
    'interval_jitter_min': 20,
    'queue_days': 1,
    'postponed_limit': 140,
    'min_viral_score': 30,
    'global_dedup': True,
    'run_mode': 'dry_run',
    'shortage_strategy': 'improve_then_reduce',
    'horizon_days': 2,
    'posts_per_day': 12,
    'download_multiplier': 2,
    'hard_antiplagiat': True,
    'smart_24h_schedule': True,
    'exploitation_percent': 75,
}


BAD_TEXT_MARKERS = (
    'реклама', 'продам', 'скидка', 'казино', 'ставки', '18+',
    'подпишись на меня', 'заработок',
)


def _profile_dir(profile_id: Optional[str] = None) -> Path:
    return STORAGE_DIR / (profile_id or app_state.active_profile_id)


def report_file(profile_id: Optional[str] = None) -> Path:
    return _profile_dir(profile_id) / 'growth_autopilot_report.json'


def global_dedup_file() -> Path:
    return STORAGE_DIR / 'global_used_posts.json'


def load_growth_settings(profile: Optional[Dict] = None) -> Dict:
    profile = profile or app_state.profile
    settings = DEFAULT_GROWTH_SETTINGS.copy()
    settings.update(profile.get('growth_autopilot', {}) or {})
    return normalize_settings(settings)


def normalize_settings(settings: Optional[Dict]) -> Dict:
    result = DEFAULT_GROWTH_SETTINGS.copy()
    result.update(settings or {})
    for key in (
        'posts_per_day_min', 'posts_per_day_max', 'allowed_hours_start',
        'allowed_hours_end', 'queue_days', 'horizon_days', 'posts_per_day',
        'download_multiplier', 'exploitation_percent',
    ):
        try:
            result[key] = int(result.get(key, DEFAULT_GROWTH_SETTINGS[key]))
        except Exception:
            result[key] = DEFAULT_GROWTH_SETTINGS[key]

    if result['posts_per_day_min'] < 1:
        result['posts_per_day_min'] = 1
    if result['posts_per_day_max'] < result['posts_per_day_min']:
        result['posts_per_day_max'] = result['posts_per_day_min']
    result['allowed_hours_start'] = max(0, min(23, result['allowed_hours_start']))
    result['allowed_hours_end'] = max(0, min(23, result['allowed_hours_end']))
    if result['allowed_hours_end'] <= result['allowed_hours_start']:
        result['allowed_hours_end'] = 23
    result['exploitation_percent'] = max(50, min(95, result.get('exploitation_percent', 75)))
    result['auto_apply_recommendations'] = bool(result.get('auto_apply_recommendations', True))
    return result


@dataclass(frozen=True)
class ScheduleSlot:
    ts: int
    hour: int
    source: str


def _top_heatmap_hours(heatmap: List[Dict], limit: int = 8) -> List[int]:
    ranked = sorted(
        [item for item in (heatmap or []) if int(item.get('posts', 0) or 0) > 0],
        key=lambda item: (float(item.get('avg_score', 0) or 0), int(item.get('posts', 0) or 0)),
        reverse=True,
    )
    return [int(item['hour']) for item in ranked[:limit] if 0 <= int(item['hour']) <= 23]


def _round_robin_fill(hours: List[int], n: int) -> List[int]:
    """Заполнить n слотов часами: полные круги по всем часам, затем случайный
    добор. Гарантирует представленность каждого часа при n >= len(hours)."""
    if not hours or n <= 0:
        return []
    full_rounds = n // len(hours)
    remainder = n % len(hours)
    result: List[int] = []
    for _ in range(full_rounds):
        chunk = list(hours)
        random.shuffle(chunk)
        result.extend(chunk)
    if remainder:
        result.extend(random.sample(hours, remainder))
    return result


def build_learned_24h_schedule(
    count: int,
    start_ts: int,
    heatmap: Optional[List[Dict]] = None,
    horizon_days: int = 1,
    exploitation_percent: int = 75,
) -> List[ScheduleSlot]:
    count = max(0, int(count or 0))
    if count <= 0:
        return []
    horizon_days = max(1, int(horizon_days or 1))
    exploitation_percent = max(50, min(95, int(exploitation_percent or 75)))

    preferred = _top_heatmap_hours(heatmap or [], limit=8)
    if not preferred:
        # Разнообразный fallback по всему активному дню, пока трекер не обучился.
        preferred = [8, 10, 12, 14, 16, 18, 20, 22]

    explore_hours = [hour for hour in range(24) if hour not in preferred] or list(range(24))
    exploit_count = min(count, max(1, round(count * exploitation_percent / 100)))
    explore_count = max(0, count - exploit_count)

    # Сначала гарантируем каждый preferred-час хотя бы раз (полные «круги»),
    # затем добиваем остаток случайной выборкой — так топовые часы не теряются,
    # но один и тот же час не идёт подряд.
    best_seq = _round_robin_fill(preferred, exploit_count)
    test_seq = _round_robin_fill(explore_hours, explore_count)

    selected = [(h, 'best') for h in best_seq]
    selected += [(h, 'test') for h in test_seq]
    random.shuffle(selected)

    start_dt = datetime.fromtimestamp(int(start_ts))
    slots = []
    used_ts: set[int] = set()
    for idx, (hour, source) in enumerate(selected):
        # Раскидываем по дням горизонта циклически, чтобы заполнить все дни.
        day_offset = idx % horizon_days
        for _ in range(8):  # до 8 попыток найти свободную минуту в этом часе
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            dt = (start_dt + timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=second)
            while int(dt.timestamp()) <= int(start_ts):
                dt += timedelta(days=1)
            ts = int(dt.timestamp())
            # Избегаем коллизий минут (иначе VK 214) — округляем уникальность до минуты.
            ts_minute = ts - (ts % 60)
            if ts_minute not in used_ts:
                used_ts.add(ts_minute)
                slots.append(ScheduleSlot(ts=ts, hour=hour, source=source))
                break
        else:
            slots.append(ScheduleSlot(ts=int(dt.timestamp()), hour=hour, source=source))

    slots.sort(key=lambda item: item.ts)
    return slots[:count]


def cycle_target_count(settings: Dict) -> int:
    settings = normalize_settings(settings)
    horizon_days = max(1, _safe_int(settings.get('horizon_days', 2), 2))
    posts_per_day = max(1, _safe_int(settings.get('posts_per_day', settings.get('posts_per_day_max', 12)), 12))
    return max(1, horizon_days * posts_per_day)


def distribute_download_count(total_count: int, source_count: int) -> int:
    if source_count <= 0:
        return max(1, int(total_count))
    return max(1, int((int(total_count) + source_count - 1) / source_count))


def build_cycle_patch(settings: Dict) -> Dict:
    settings = normalize_settings(settings)
    target = cycle_target_count(settings)
    horizon_days = max(1, _safe_int(settings.get('horizon_days', 2), 2))
    start_h = settings['allowed_hours_start']
    end_h = settings['allowed_hours_end']
    active_seconds = max(3600, (end_h - start_h) * 3600 * horizon_days)
    base_delay = max(900, int(active_seconds / max(target, 1)))
    delay_min = max(600, int(base_delay * 0.75))
    delay_max = max(delay_min + 60, int(base_delay * 1.25))
    download_count = max(target, target * max(1, _safe_int(settings.get('download_multiplier', 2), 2)))
    try:
        from services.tracker import get_summary
        tracking_summary = get_summary()
    except Exception:
        tracking_summary = {}
    hour_heatmap = tracking_summary.get('hour_heatmap', [])
    preferred_hours = _top_heatmap_hours(hour_heatmap, limit=8)

    patch = {
        'download_settings': {
            'posts_to_download': download_count,
            'check_duplicates': True,
            'batch_size': 100,
            'delay_min': 0,
            'delay_max': 0,
            'max_scan_posts': max(100, download_count * 4),
            'max_photos_per_post': 2,
        },
        'filters': {
            'ad_stopper_enabled': True,
        },
        'publishing_settings': {
            'posts_to_publish': target,
            'publish_delay_min': delay_min,
            'publish_delay_max': delay_max,
            'postponed_enabled': True,
            'skip_vk_sync': True,
            'publish_hours_enabled': not bool(settings.get('smart_24h_schedule', True)),
            'publish_hours_start': start_h,
            'publish_hours_end': end_h,
        },
        'growth_schedule': {
            'enabled': bool(settings.get('smart_24h_schedule', True)),
            'mode': 'learned_24h',
            'horizon_days': horizon_days,
            'exploitation_percent': settings.get('exploitation_percent', 75),
            'preferred_hours': preferred_hours,
            'hour_heatmap': hour_heatmap,
        },
        'peak_hours': {
            'enabled': False,
        },
        'antiplagiaat': {
            'enabled': True,
            'clear_text': True,
            'max_photos': 2,
            'remove_photo': 'random',
            'transforms': {
                'crop': bool(settings.get('hard_antiplagiat', True)),
                'color_shift': bool(settings.get('hard_antiplagiat', True)),
                'mirror': bool(settings.get('hard_antiplagiat', True)),
                'strip_metadata': bool(settings.get('hard_antiplagiat', True)),
            },
        },
        'phash': {
            'enabled': False,
        },
        'polls': {
            'enabled': False,
        },
        'autopost_cycle': {
            'horizon_days': horizon_days,
            'posts_per_day': target // horizon_days,
            'last_target_count': target,
        },
    }
    return patch


def apply_profile_patch(patch: Dict) -> None:
    pid = app_state.active_profile_id
    current = app_state.config['profiles'][pid]
    app_state.config['profiles'][pid] = app_state._deep_merge(current, patch)
    app_state.save_config()


def cycle_status_file(profile_id: Optional[str] = None) -> Path:
    return _profile_dir(profile_id) / 'autopost_cycle_status.json'


def save_cycle_status(data: Dict) -> Dict:
    fp = cycle_status_file()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def load_cycle_status() -> Dict:
    fp = cycle_status_file()
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def _rank_sources_by_er() -> List[str]:
    """Вернуть список community_id источников, отсортированных по ER конкурентов.

    Если данных нет — возвращает источники в исходном порядке.
    """
    sources = [s for s in app_state.profile.get('sources', []) if s.get('enabled', True)]
    if not sources:
        return []
    try:
        from services.competitor import get_competitor_insights
        insights = get_competitor_insights(app_state.active_profile_id)
        source_er: Dict[str, float] = insights.get('source_er', {})
        if source_er:
            return sorted(
                [str(s.get('community_id', '')).strip() for s in sources],
                key=lambda cid: source_er.get(cid, 0.0),
                reverse=True,
            )
    except Exception:
        pass
    return [str(s.get('community_id', '')).strip() for s in sources]


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _post_text(post: Dict) -> str:
    return (post.get('text') or '').strip()


def _attachment_counts(post: Dict) -> Dict:
    photos = len(post.get('_local_photos') or [])
    videos = len(post.get('_vk_videos') or [])
    for att in post.get('attachments', []) or []:
        if att.get('type') == 'photo':
            photos += 1
        if att.get('type') == 'video':
            videos += 1
    return {'photos': photos, 'videos': videos}


def is_bad_text(text: str) -> bool:
    low = (text or '').lower()
    return any(marker in low for marker in BAD_TEXT_MARKERS)


def text_fingerprint(text: str) -> str:
    cleaned = ' '.join((text or '').lower().split())
    return hashlib.sha1(cleaned.encode('utf-8')).hexdigest()


def source_post_key(post: Dict, source_id: str = '') -> str:
    owner = str(post.get('owner_id') or source_id or '').lstrip('-')
    post_id = str(post.get('id') or post.get('post_id') or '')
    return f'{owner}_{post_id}' if owner and post_id else text_fingerprint(_post_text(post))


def score_candidate(post: Dict, source_id: str = '', source_weight: float = 0) -> Dict:
    likes = _safe_int(post.get('likes', {}).get('count', 0))
    reposts = _safe_int(post.get('reposts', {}).get('count', 0))
    comments = _safe_int(post.get('comments', {}).get('count', 0))
    views = _safe_int(post.get('views', {}).get('count', 0))
    post_ts = _safe_int(post.get('date', 0))
    age_hours = max(0, (int(time.time()) - post_ts) / 3600) if post_ts else 72
    text = _post_text(post)
    media = _attachment_counts(post)
    er = (likes + reposts * 2 + comments * 1.5) / max(views, 1) * 100 if views else 0

    score = 15
    score += min(likes * 0.8, 28)
    score += min(reposts * 3.0, 24)
    score += min(comments * 2.0, 16)
    score += min(views / 250, 20)
    score += min(er * 8, 18)
    score += max(0, 18 - min(age_hours / 8, 18))
    score += min(float(source_weight or 0), 12)
    score += min(media['photos'] * 4, 14)
    score += 6 if 20 <= len(text) <= 700 else 2 if text else 0
    if is_bad_text(text):
        score -= 35

    reasons = []
    if likes:
        reasons.append(f'{likes} likes')
    if reposts:
        reasons.append(f'{reposts} reposts')
    if comments:
        reasons.append(f'{comments} comments')
    if views:
        reasons.append(f'{views} views')
    if media['photos']:
        reasons.append(f"{media['photos']} photos")
    if er:
        reasons.append(f'{er:.2f}% ER')
    if is_bad_text(text):
        reasons.append('bad text marker')

    return {
        'source_id': str(source_id or post.get('owner_id', '')).lstrip('-'),
        'post_id': post.get('id') or post.get('post_id'),
        'owner_id': post.get('owner_id'),
        'file': post.get('_file', ''),
        'viral_score': round(max(score, 0), 1),
        'likes': likes,
        'reposts': reposts,
        'comments': comments,
        'views': views,
        'photos': media['photos'],
        'videos': media['videos'],
        'text_preview': text[:180],
        'fingerprint': text_fingerprint(text),
        'dedup_key': source_post_key(post, source_id),
        'reasons': reasons[:6],
    }


def _push_to_allowed_window(ts: int, start_h: int, end_h: int) -> int:
    d = datetime.fromtimestamp(ts)
    if d.hour < start_h:
        d = d.replace(hour=start_h, minute=random.randint(0, 50), second=random.randint(0, 59))
    elif d.hour >= end_h:
        d = (d + timedelta(days=1)).replace(
            hour=start_h, minute=random.randint(0, 50), second=random.randint(0, 59)
        )
    return int(d.timestamp())


def build_schedule_preview(candidates: List[Dict], settings: Dict, start_ts: Optional[int] = None) -> List[Dict]:
    settings = normalize_settings(settings)
    if not candidates:
        return []
    daily_limit = random.randint(settings['posts_per_day_min'], settings['posts_per_day_max'])
    limit = min(len(candidates), daily_limit * max(1, settings['queue_days']))
    start_ts = start_ts or int(time.time())
    if settings.get('smart_24h_schedule', True):
        try:
            from services.tracker import get_summary
            heatmap = settings.get('hour_heatmap') or get_summary().get('hour_heatmap', [])
        except Exception:
            heatmap = settings.get('hour_heatmap') or []
        slots = build_learned_24h_schedule(
            count=limit,
            start_ts=start_ts,
            heatmap=heatmap,
            horizon_days=max(1, settings.get('queue_days', 1)),
            exploitation_percent=settings.get('exploitation_percent', 75),
        )
        result = []
        for cand, slot in zip(candidates[:limit], slots):
            result.append({
                'file': cand.get('file', ''),
                'post_id': cand.get('post_id'),
                'source_id': cand.get('source_id'),
                'viral_score': cand.get('viral_score', 0),
                'publish_ts': slot.ts,
                'publish_at': datetime.fromtimestamp(slot.ts).strftime('%d.%m.%Y %H:%M'),
                'schedule_source': slot.source,
            })
        return result

    start_h = settings['allowed_hours_start']
    end_h = settings['allowed_hours_end']
    active_seconds = max(3600, (end_h - start_h) * 3600)
    base_interval = max(900, active_seconds // max(daily_limit, 1))
    jitter = max(0, _safe_int(settings.get('interval_jitter_min', 20), 20) * 60)

    next_ts = _push_to_allowed_window(start_ts, start_h, end_h)
    result = []
    for cand in candidates[:limit]:
        next_ts = _push_to_allowed_window(next_ts, start_h, end_h)
        result.append({
            'file': cand.get('file', ''),
            'post_id': cand.get('post_id'),
            'source_id': cand.get('source_id'),
            'viral_score': cand.get('viral_score', 0),
            'publish_ts': next_ts,
            'publish_at': datetime.fromtimestamp(next_ts).strftime('%d.%m.%Y %H:%M'),
        })
        delta = base_interval + random.randint(-jitter, jitter) if jitter else base_interval
        next_ts += max(900, delta)
    return result


def load_used_posts(used_file: Optional[Path] = None) -> Dict:
    used_file = used_file or global_dedup_file()
    if used_file.exists():
        try:
            return json.loads(used_file.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def save_used_posts(data: Dict, used_file: Optional[Path] = None) -> None:
    used_file = used_file or global_dedup_file()
    used_file.parent.mkdir(parents=True, exist_ok=True)
    used_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def mark_used_post(candidate: Dict, used_file: Optional[Path] = None, profile_id: Optional[str] = None) -> None:
    data = load_used_posts(used_file)
    key = candidate.get('dedup_key')
    if not key:
        return
    data[key] = {
        'source_id': candidate.get('source_id'),
        'post_id': candidate.get('post_id'),
        'profile_id': profile_id or app_state.active_profile_id,
        'used_at': datetime.now().isoformat(timespec='seconds'),
        'fingerprint': candidate.get('fingerprint', ''),
    }
    save_used_posts(data, used_file)


def filter_global_duplicates(candidates: List[Dict], used_file: Optional[Path] = None) -> List[Dict]:
    used = load_used_posts(used_file)
    return [item for item in candidates if item.get('dedup_key') not in used]


def _load_local_posts(posts_dir: Path) -> List[Dict]:
    posts = []
    for fp in sorted(posts_dir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            post = json.loads(fp.read_text(encoding='utf-8'))
            post['_file'] = fp.name
            posts.append(post)
        except Exception:
            continue
    return posts


def build_technical_checks() -> List[Dict]:
    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    sources = [s for s in profile.get('sources', []) if s.get('enabled', True)]
    return [
        {'name': 'User Token', 'ok': bool(vk_cfg.get('user_token', '').strip())},
        {'name': 'Group Token', 'ok': bool(vk_cfg.get('group_token', '').strip())},
        {'name': 'Group ID', 'ok': bool(vk_cfg.get('group_id', '').strip())},
        {'name': 'Sources', 'ok': bool(sources), 'value': len(sources)},
        {'name': 'Queue', 'ok': app_state.posts_dir.exists(), 'value': len(list(app_state.posts_dir.glob('*.json')))},
    ]


def fetch_vk_posts(source_id: str, count: int = 50) -> List[Dict]:
    """Fetch VK wall posts for dry-run scoring without downloading media."""
    from vk.api import get_vk_api, normalize_owner_id, vk_call_safe

    vk_cfg = app_state.profile.get('vk', {})
    token = vk_cfg.get('user_token', '').strip()
    if not token:
        raise RuntimeError('User Token is not set')

    vk = get_vk_api(token, vk_cfg.get('api_version', '5.131'))
    owner_id = normalize_owner_id(str(source_id))
    resp = vk_call_safe(vk.wall.get, owner_id=owner_id, count=max(1, min(int(count), 100)), filter='owner')
    items = resp.get('items', []) if isinstance(resp, dict) else []
    for post in items:
        post['_source_id'] = str(source_id).lstrip('-')
        post['_file'] = f'vk_{str(source_id).lstrip("-")}_{post.get("id", "")}.json'
    return items


def save_report(report: Dict) -> Dict:
    fp = report_file()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def load_report() -> Dict:
    fp = report_file()
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def build_readonly_report(
    posts_dir: Optional[Path] = None,
    settings: Optional[Dict] = None,
    used_file: Optional[Path] = None,
    save: bool = True,
) -> Dict:
    settings = normalize_settings(settings or load_growth_settings())
    posts_dir = posts_dir or app_state.posts_dir
    warnings = []
    posts = []
    if settings.get('source_mode') == 'single' and settings.get('single_source_id') and posts_dir == app_state.posts_dir:
        try:
            posts = fetch_vk_posts(settings.get('single_source_id'), count=100)
        except Exception as e:
            warnings.append(f'Single source fetch failed: {e}')
    if not posts:
        posts = _load_local_posts(posts_dir)
    candidates = [
        score_candidate(post, source_id=str(post.get('_source_id') or post.get('owner_id', '')).lstrip('-'))
        for post in posts
    ]
    candidates = [
        c for c in candidates
        if c['viral_score'] >= float(settings.get('min_viral_score', 30))
    ]
    if settings.get('global_dedup', True):
        candidates = filter_global_duplicates(candidates, used_file=used_file)
    candidates.sort(key=lambda c: c['viral_score'], reverse=True)
    schedule = build_schedule_preview(candidates, settings)

    report = {
        'status': 'ok',
        'mode': 'read_only',
        'generated_at': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
        'settings': settings,
        'summary': {
            'queue_files': len(posts),
            'candidate_count': len(candidates),
            'scheduled_preview': len(schedule),
            'min_viral_score': settings.get('min_viral_score', 30),
        },
        'checks': build_technical_checks(),
        'warnings': warnings,
        'top_candidates': candidates[:50],
        'schedule_preview': schedule,
    }
    return save_report(report) if save else report


def build_cycle_dry_run(settings: Optional[Dict] = None) -> Dict:
    settings = normalize_settings(settings or load_growth_settings())
    patch = build_cycle_patch(settings)
    target = cycle_target_count(settings)
    current_queue = len(list(app_state.posts_dir.glob('*.json')))
    report = build_readonly_report(settings={
        **settings,
        'posts_per_day_min': target,
        'posts_per_day_max': target,
        'min_viral_score': settings.get('min_viral_score', 0),
    }, save=False)
    report['mode'] = 'cycle_dry_run'
    report['cycle'] = {
        'target_posts': target,
        'horizon_days': settings.get('horizon_days', 2),
        'posts_per_day': settings.get('posts_per_day', 12),
        'download_count': patch['download_settings']['posts_to_download'],
        'current_queue': current_queue,
        'patch': patch,
    }
    save_report(report)
    return report


def _run_cycle_worker(settings: Dict) -> None:
    from workers.download import _download_source
    from workers.publish import publish_worker

    status = {
        'running': True,
        'phase': 'starting',
        'started_at': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
        'message': 'Cycle started',
    }
    save_cycle_status(status)

    try:
        settings = normalize_settings(settings)
        patch = build_cycle_patch(settings)
        apply_profile_patch(patch)
        target = cycle_target_count(settings)
        download_count = patch['download_settings']['posts_to_download']

        status.update({'phase': 'download', 'message': f'Downloading up to {download_count} posts'})
        save_cycle_status(status)
        app_state.is_downloading = True
        app_state.download_progress = {
            'phase': 'download',
            'current': 0,
            'total': download_count,
            'source': settings.get('single_source_id') or 'enabled sources',
            'message': 'Growth cycle download',
            'cancelled': False,
        }

        if settings.get('source_mode') == 'single' and settings.get('single_source_id'):
            _download_source(str(settings['single_source_id']).strip(), download_count)
            app_state.is_downloading = False
        else:
            # Источники ранжируются по ER конкурентов — лучшие качают больше
            ranked_cids = [cid for cid in _rank_sources_by_er() if cid]
            if not ranked_cids:
                ranked_cids = [
                    str(s.get('community_id', '')).strip()
                    for s in app_state.profile.get('sources', [])
                    if s.get('enabled', True) and s.get('community_id', '')
                ]
            total_sources = len(ranked_cids)
            per_source_count = distribute_download_count(download_count, total_sources)
            for index, cid in enumerate(ranked_cids, 1):
                if not app_state.is_downloading:
                    break
                status.update({
                    'phase': 'download',
                    'message': f'Источник {index}/{total_sources}: до {per_source_count} постов',
                })
                save_cycle_status(status)
                _download_source(cid, per_source_count)
            app_state.is_downloading = False

        pending = len(list(app_state.posts_dir.glob('*.json')))
        if pending <= 0:
            status.update({'running': False, 'phase': 'empty', 'message': 'No posts after download'})
            save_cycle_status(status)
            return

        publish_count = min(target, pending)
        status.update({'phase': 'publish', 'message': f'Scheduling {publish_count} postponed posts'})
        save_cycle_status(status)
        app_state.is_publishing = True
        publish_worker(publish_count)

        # Видео и клипы — отдельные циклы автопилота (workers/media_autopilot.py),
        # к growth-циклу постов больше не цепляются

        # Заполнить пустые слоты в уже занятых днях очереди VK
        try:
            from services.slot_finder import find_empty_slots, fill_slots_with_queue, fetch_postponed_timestamps
            from services.engagement import load_engagement_model
            from vk.api import get_vk_api
            remaining = len(list(app_state.posts_dir.glob('*.json')))
            if remaining > 0:
                vk_cfg = app_state.profile.get('vk', {})
                group_token = vk_cfg.get('group_token', '').strip()
                group_id = vk_cfg.get('group_id', '').strip()
                user_token = vk_cfg.get('user_token', '').strip()
                if group_token and group_id and user_token:
                    status.update({'phase': 'fill_slots', 'message': 'Заполняю пустые слоты'})
                    save_cycle_status(status)
                    api_ver = vk_cfg.get('api_version', '5.131')
                    vk_user = get_vk_api(user_token, api_ver)
                    vk_group = get_vk_api(group_token, api_ver)
                    # user_token нужен для чтения postponed (group_token не имеет доступа)
                    postponed = fetch_postponed_timestamps(vk_user, group_id)
                    model = load_engagement_model(app_state.active_profile_id)
                    empty_slots = find_empty_slots(
                        postponed, app_state.profile, model,
                        max_slots=20, profile_id=app_state.active_profile_id,
                    )
                    if empty_slots:
                        result = fill_slots_with_queue(
                            empty_slots, app_state.posts_dir, vk_user, vk_group, group_id,
                            app_state.profile, app_state.add_log,
                        )
                        filled = result.get('filled', 0)
                        if filled:
                            app_state.add_log(f'Цикл: заполнено {filled} пустых слотов', 'info')
                            _save_bot_change(f'Заполнено {filled} пустых слотов в очереди VK')
        except Exception as e:
            app_state.add_log(f'Цикл: fill_slots: {e}', 'warning')

        # Авто-синхронизация статистики: подтягиваем views/likes из VK
        try:
            from services.tracker import run_check
            status.update({'phase': 'stats', 'message': 'Syncing stats from VK'})
            save_cycle_status(status)
            run_check()
            app_state.add_log('Цикл: статистика синхронизирована', 'info')
        except Exception as e:
            app_state.add_log(f'Цикл: синх. статистики: {e}', 'warning')

        # Обучение — смешиваем сигнал своих постов + конкурентов
        try:
            from services.learning import run_learning_cycle
            status.update({'phase': 'learn', 'message': 'Обучение: анализ конкурентов и своих постов'})
            save_cycle_status(status)
            run_learning_cycle()
        except Exception as e:
            app_state.add_log(f'Цикл: обучение: {e}', 'warning')

        # Авто-анализ и применение рекомендаций (posts_per_day, часы)
        try:
            rec_result = build_algorithmic_recommendations()
            if rec_result.get('auto_applied'):
                rec = rec_result.get('recommendation', {})
                _save_bot_change(
                    f'{rec.get("posts_per_day", "?")} постов/день, '
                    f'часы: {rec.get("hours", [])[:6]} — {rec.get("reason", "")}'
                )
        except Exception as e:
            app_state.add_log(f'Цикл: авто-анализ: {e}', 'warning')

        status.update({
            'running': False,
            'phase': 'done',
            'finished_at': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
            'message': f'Цикл завершён: {publish_count} постов в очередь VK',
        })
        save_cycle_status(status)
    except Exception as e:
        app_state.add_log(f'Growth cycle: {e}', 'error')
        status.update({
            'running': False,
            'phase': 'error',
            'finished_at': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
            'message': str(e),
        })
        save_cycle_status(status)
    finally:
        app_state.is_downloading = False
        app_state.is_publishing = False


def start_cycle(settings: Optional[Dict] = None) -> Dict:
    if app_state.is_downloading or app_state.is_publishing:
        return {'status': 'error', 'message': 'Download or publish is already running'}

    # Берём настройки из профиля — бот сам знает что делать.
    # UI-override применяется только если явно передан (пользователь поменял вручную).
    base = load_growth_settings()
    if settings:
        base.update({k: v for k, v in settings.items() if v is not None})
    final_settings = normalize_settings(base)

    t = threading.Thread(target=_run_cycle_worker, args=(final_settings,), daemon=True, name='growth_cycle')
    t.start()
    save_cycle_status({
        'running': True,
        'phase': 'queued',
        'started_at': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
        'message': 'Cycle queued',
    })
    return {'status': 'ok', 'message': 'Цикл запущен'}


def build_algorithmic_recommendations() -> Dict:
    from services.tracker import get_summary

    summary = get_summary()
    checked = int(summary.get('checked', 0) or 0)
    current = app_state.profile
    current_cycle = current.get('autopost_cycle', {})
    current_posts_per_day = int(current_cycle.get('posts_per_day') or current.get('publishing_settings', {}).get('posts_to_publish', 12))
    avg_views = int(summary.get('avg_views', 0) or 0)
    avg_likes = int(summary.get('avg_likes', 0) or 0)
    # Берём часы только из реально обученного трекера.
    # peak_hours из профиля — устаревшие, не используем как fallback.
    recommended_hours = summary.get('recommended_hours') or []
    hour_heatmap = summary.get('hour_heatmap', [])

    if checked < 5:
        recommended_posts_per_day = current_posts_per_day
        reason = 'Накапливаю данные (нужно минимум 5 проверенных постов)'
    elif avg_views <= 0:
        recommended_posts_per_day = max(4, current_posts_per_day - 2)
        reason = 'Views are empty; reduce tempo until tracker has better data'
    elif avg_likes >= 10:
        recommended_posts_per_day = min(36, current_posts_per_day + 2)
        reason = 'Good likes signal; tempo can be increased carefully'
    else:
        recommended_posts_per_day = max(4, current_posts_per_day - 1)
        reason = 'Weak reaction; reduce tempo and focus on stronger hours'

    patch = {
        'peak_hours': {
            'enabled': False,
            'hours': recommended_hours[:8],
        },
        'growth_schedule': {
            'enabled': True,
            'mode': 'learned_24h',
            'horizon_days': int(current_cycle.get('horizon_days') or 2),
            'exploitation_percent': 75,
            'preferred_hours': recommended_hours[:8],
            'hour_heatmap': hour_heatmap,
        },
        'autopost_cycle': {
            'posts_per_day': recommended_posts_per_day,
            'horizon_days': int(current_cycle.get('horizon_days') or 2),
        },
    }
    # Авто-применение рекомендаций если включено в профиле (по умолчанию True)
    auto_apply = app_state.profile.get('growth_autopilot', {}).get('auto_apply_recommendations', True)
    applied = False
    if auto_apply:
        try:
            apply_profile_patch(patch)
            applied = True
            app_state.add_log(
                f'Анализ: авто-применены рекомендации — {recommended_posts_per_day} постов/день, '
                f'часы: {recommended_hours[:8]}',
                'info',
            )
        except Exception as e:
            app_state.add_log(f'Анализ: не удалось применить рекомендации: {e}', 'warning')

    return {
        'status': 'ok',
        'summary': summary,
        'auto_applied': applied,
        'recommendation': {
            'posts_per_day': recommended_posts_per_day,
            'hours': recommended_hours[:8],
            'hour_heatmap': hour_heatmap,
            'reason': reason,
            'patch': patch,
        },
    }
