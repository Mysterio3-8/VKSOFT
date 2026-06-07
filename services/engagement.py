"""
Сбор и хранение engagement-данных опубликованных постов.
published_posts.json — список постов с post_id, временем, часом публикации и статистикой.
При каждом запуске бота проверяет непроверенные посты через VK API.
"""
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_RECORDS = 500
CHECK_AFTER_HOURS = [2, 24]  # через сколько часов после публикации снимать статистику


def _published_posts_file(profile_id: str) -> Path:
    from config import STORAGE_DIR
    return STORAGE_DIR / profile_id / 'published_posts.json'


def _engagement_model_file(profile_id: str) -> Path:
    from config import STORAGE_DIR
    return STORAGE_DIR / profile_id / 'engagement_model.json'


def load_published_posts(profile_id: str) -> list[dict]:
    f = _published_posts_file(profile_id)
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        return []


def save_published_posts(profile_id: str, posts: list[dict]) -> None:
    f = _published_posts_file(profile_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    # Держим только последние MAX_RECORDS
    posts = posts[-MAX_RECORDS:]
    import tempfile
    tmp = f.parent / f'.tmp_{f.name}'
    tmp.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, f)


def record_published_post(profile_id: str, post_id: int, publish_ts: int, hour: int) -> None:
    """Записать факт публикации поста для последующего отслеживания."""
    posts = load_published_posts(profile_id)
    entry = {
        'post_id': post_id,
        'publish_ts': publish_ts,
        'hour': hour,
        'checks': [],       # [{ts, views, likes, reposts}]
        'done': False,      # True когда все проверки пройдены
    }
    posts.append(entry)
    save_published_posts(profile_id, posts)


def collect_engagement(profile_id: str, group_id: str, vk_user) -> dict:
    """
    При запуске бота — проверить все непроверенные посты.
    Возвращает словарь {post_id: {views, likes, reposts}} для новых данных.
    """
    posts = load_published_posts(profile_id)
    now = int(time.time())
    updated = False
    new_data: dict[int, dict] = {}

    for entry in posts:
        if entry.get('done'):
            continue

        publish_ts = entry['publish_ts']
        hours_since = (now - publish_ts) / 3600
        existing_check_hours = {c.get('hours_after') for c in entry.get('checks', [])}

        for target_h in CHECK_AFTER_HOURS:
            if target_h in existing_check_hours:
                continue
            if hours_since >= target_h:
                stats = _fetch_post_stats(vk_user, group_id, entry['post_id'])
                if stats:
                    entry.setdefault('checks', []).append({
                        'ts': now,
                        'hours_after': target_h,
                        **stats,
                    })
                    new_data[entry['post_id']] = stats
                    updated = True

        # Пометить как done если все проверки пройдены
        done_checks = {c.get('hours_after') for c in entry.get('checks', [])}
        if all(h in done_checks for h in CHECK_AFTER_HOURS):
            entry['done'] = True
            updated = True

    if updated:
        save_published_posts(profile_id, posts)
        _update_engagement_model(profile_id, posts)

    return new_data


def _fetch_post_stats(vk_user: Any, group_id: str, post_id: int) -> dict | None:
    try:
        from vk.api import vk_call_safe
        gid = abs(int(group_id))
        result = vk_call_safe('wall.getById', {
            'posts': f'-{gid}_{post_id}',
            'extended': 0,
        }, vk_instance=vk_user)
        items = result.get('items') if isinstance(result, dict) else result
        if not items:
            return None
        item = items[0]
        return {
            'views': item.get('views', {}).get('count', 0) if isinstance(item.get('views'), dict) else 0,
            'likes': item.get('likes', {}).get('count', 0),
            'reposts': item.get('reposts', {}).get('count', 0),
            'comments': item.get('comments', {}).get('count', 0),
        }
    except Exception as e:
        logger.warning(f"engagement: ошибка получения статистики поста {post_id}: {e}")
        return None


def _update_engagement_model(profile_id: str, posts: list[dict]) -> None:
    """
    Пересчитать hour_heatmap на основе накопленных данных.
    Метрика = среднее (likes + reposts*2) за 24ч по каждому часу публикации.
    """
    from collections import defaultdict
    hour_scores: dict[int, list[float]] = defaultdict(list)

    for entry in posts:
        hour = entry.get('hour')
        if hour is None:
            continue
        check_24 = next((c for c in entry.get('checks', []) if c.get('hours_after') == 24), None)
        if not check_24:
            continue
        score = check_24.get('likes', 0) + check_24.get('reposts', 0) * 2
        hour_scores[hour].append(float(score))

    model: dict[str, Any] = {}
    heatmap: dict[int, float] = {}
    for h in range(24):
        scores = hour_scores.get(h, [])
        heatmap[h] = round(sum(scores) / len(scores), 2) if scores else 0.0

    model['hour_heatmap'] = heatmap
    model['sample_count'] = {h: len(hour_scores.get(h, [])) for h in range(24)}
    model['updated_ts'] = int(time.time())

    f = _engagement_model_file(profile_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.parent / f'.tmp_{f.name}'
    tmp.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, f)
    logger.info(f"engagement: модель обновлена для профиля {profile_id}")


def load_engagement_model(profile_id: str) -> dict:
    f = _engagement_model_file(profile_id)
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        return {}
