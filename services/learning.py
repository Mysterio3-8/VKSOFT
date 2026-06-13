# -*- coding: utf-8 -*-
"""Адаптивное обучение — автоматически настраивает параметры профиля.

Объединяет три источника сигнала:
  1. tracker.py     — engagement собственных постов (views/likes/reposts по часам)
  2. engagement.py  — hour_heatmap опубликованных постов
  3. competitor.py  — агрегированный сигнал конкурентов

На основе этих данных:
  - Корректирует peak_hours (лучшие часы публикации)
  - Ставит флаги рекомендаций в learning_state.json (бот видит их и применяет)
  - Ничего не ломает: применяет изменения только при достаточной уверенности

Файл learning_state.json в storage/{profile_id}/ — мозг обучения.
"""

import json
import os
import time
import threading
from pathlib import Path

from config import app_state, STORAGE_DIR, logger

LEARN_INTERVAL_SEC = 3600   # обновляем каждый час
MIN_POSTS_FOR_SIGNAL = 10   # минимум постов для доверия своему сигналу
COMPETITOR_WEIGHT = 0.35    # вес конкурентов в итоговом сигнале (остальное — свои данные)

MIN_CAPTION_POSTS = 5       # минимум проверенных постов на категорию подписей
CAPTION_WEIGHT_FLOOR = 10   # ни одна категория не падает ниже — продолжает тестироваться
CAPTION_FORMATS = ('photo', 'clip')  # веса обучаются отдельно на формат


def _state_file(profile_id: str) -> Path:
    return STORAGE_DIR / profile_id / 'learning_state.json'


def _load_state(profile_id: str) -> dict:
    f = _state_file(profile_id)
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_state(profile_id: str, state: dict) -> None:
    f = _state_file(profile_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.parent / f'.tmp_{f.name}'
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, f)


def _blend_heatmaps(
    own_heatmap: dict[int, float],
    competitor_heatmap: dict[int, float],
    own_sample: int,
) -> dict[int, float]:
    """Смешать свою тепловую карту с конкурентской.

    При малом количестве своих данных конкуренты весят больше.
    """
    own_confidence = min(own_sample / 50.0, 1.0)  # 0..1, 50 постов = полная уверенность
    w_own = own_confidence * (1 - COMPETITOR_WEIGHT)
    w_comp = 1.0 - w_own

    blended = {}
    for h in range(24):
        o = own_heatmap.get(h, 0.0)
        c = competitor_heatmap.get(h, 0.0)
        # Если конкурентских данных нет — только своё
        if c == 0.0:
            blended[h] = o
        elif o == 0.0:
            blended[h] = c * w_comp
        else:
            blended[h] = o * w_own + c * w_comp
    return blended


def _top_hours_from_heatmap(heatmap: dict[int, float], n: int = 6) -> list[int]:
    """Вернуть топ-N часов по значению heatmap."""
    return sorted(
        range(24),
        key=lambda h: heatmap.get(h, 0.0),
        reverse=True,
    )[:n]


def _normalize_heatmap(heatmap: dict[int, float]) -> dict[int, float]:
    """Привести значения heatmap к диапазону 0..1."""
    max_val = max(heatmap.values(), default=1.0)
    if max_val == 0:
        return heatmap
    return {h: v / max_val for h, v in heatmap.items()}


def compute_caption_weights(caption_stats: dict) -> dict | None:
    """Рассчитать веса категорий подписей по их вовлечённости.

    Возвращает None, если данных недостаточно (меньше MIN_CAPTION_POSTS
    хотя бы в одной категории) или сигнала нет (все ER нулевые) — тогда
    текущие веса не трогаем.
    """
    from services.content_library import CATEGORY_WEIGHTS

    for category in CATEGORY_WEIGHTS:
        bucket = caption_stats.get(category, {})
        if int(bucket.get('posts', 0)) < MIN_CAPTION_POSTS:
            return None

    ers = {c: float(caption_stats[c].get('avg_er', 0.0)) for c in CATEGORY_WEIGHTS}
    total_er = sum(ers.values())
    if total_er <= 0:
        return None

    free = 100 - CAPTION_WEIGHT_FLOOR * len(CATEGORY_WEIGHTS)
    weights = {
        c: CAPTION_WEIGHT_FLOOR + int(round(free * ers[c] / total_er))
        for c in CATEGORY_WEIGHTS
    }
    # Округление может увести сумму от 100 — корректируем лидера
    drift = 100 - sum(weights.values())
    if drift:
        leader = max(weights, key=lambda c: ers[c])
        weights[leader] += drift
    return weights


def _learn_caption_weights() -> dict:
    """Обновить веса семейств подписей по статистике трекера — на каждый формат."""
    from services.content_library import load_library, update_category_weights
    from services.tracker import get_caption_stats

    result = {'caption_stats': {}, 'caption_weights_applied': {}}
    current_all = load_library().get('category_weights', {})

    for media_format in CAPTION_FORMATS:
        caption_stats = get_caption_stats(media_type=media_format)
        result['caption_stats'][media_format] = caption_stats

        new_weights = compute_caption_weights(caption_stats)
        if not new_weights:
            continue
        if new_weights == current_all.get(media_format, {}):
            continue

        update_category_weights(new_weights, media_format)
        result['caption_weights_applied'][media_format] = new_weights
        logger.info(f'learning: веса подписей [{media_format}] → {new_weights}')
        app_state.add_log(f'[Обучение] Веса подписей ({media_format}) → {new_weights}', 'info')

    if not result['caption_weights_applied']:
        result['caption_weights_applied'] = None
    return result


def run_learning_cycle() -> dict:
    """Основной цикл обучения. Возвращает новое состояние."""
    profile_id = app_state.active_profile_id
    profile = app_state.profile

    state = _load_state(profile_id)

    # ── 1. Получить сигнал от трекера своих постов ──────────────────
    try:
        from services.tracker import get_summary
        own_summary = get_summary()
    except Exception as e:
        logger.warning(f'learning: tracker error: {e}')
        own_summary = {}

    own_heatmap_raw = {
        item['hour']: item.get('avg_score', 0.0)
        for item in own_summary.get('hour_heatmap', [])
        if isinstance(item, dict)
    }
    own_sample = own_summary.get('checked', 0)

    # ── 2. Получить сигнал конкурентов ──────────────────────────────
    try:
        from services.competitor import get_competitor_insights
        comp_insights = get_competitor_insights(profile_id)
    except Exception as e:
        logger.warning(f'learning: competitor error: {e}')
        comp_insights = {}

    comp_heatmap_raw = comp_insights.get('agg_hour_heatmap', {})
    # ключи могут быть int или str
    comp_heatmap: dict[int, float] = {
        int(k): float(v) for k, v in comp_heatmap_raw.items()
    }

    # ── 3. Нормализуем и смешиваем ──────────────────────────────────
    own_norm = _normalize_heatmap({int(k): float(v) for k, v in own_heatmap_raw.items()})
    comp_norm = _normalize_heatmap(comp_heatmap)

    blended = _blend_heatmaps(own_norm, comp_norm, own_sample)

    # ── 4. Топ часы ─────────────────────────────────────────────────
    recommended_hours = _top_hours_from_heatmap(blended, n=6)
    # Гарантируем что не пустой
    if not recommended_hours:
        recommended_hours = profile.get('peak_hours', {}).get('hours', [8, 10, 13, 17, 19, 21])

    # ── 5. Рекомендации по типу контента ────────────────────────────
    content_er = comp_insights.get('content_er', {})
    best_content_type = comp_insights.get('best_content_type', '')

    # ── 6. Рекомендации по хештегам от конкурентов ─────────────────
    competitor_hashtags = comp_insights.get('top_hashtags', [])

    # ── 7. Применяем peak_hours если уверенность достаточна ─────────
    applied_changes = []
    if own_sample >= MIN_POSTS_FOR_SIGNAL or comp_insights:
        current_hours = profile.get('peak_hours', {}).get('hours', [])
        if set(recommended_hours) != set(current_hours):
            profile.setdefault('peak_hours', {})['hours'] = sorted(recommended_hours)
            profile['peak_hours']['enabled'] = True
            app_state.save_config()
            applied_changes.append(f'peak_hours → {sorted(recommended_hours)}')
            logger.info(f'learning: обновил peak_hours → {sorted(recommended_hours)}')
            app_state.add_log(f'[Обучение] Обновил часы публикации → {sorted(recommended_hours)}', 'info')

    # ── 7.5. Обучение весов категорий подписей ──────────────────────
    try:
        caption_result = _learn_caption_weights()
        if caption_result.get('caption_weights_applied'):
            applied_changes.append(f'caption_weights → {caption_result["caption_weights_applied"]}')
    except Exception as e:
        logger.warning(f'learning: caption weights error: {e}')
        caption_result = {'caption_stats': {}, 'caption_weights_applied': None}

    # ── 7.6. Белые/стоп-листы источников по нормированному score ────
    try:
        from services.source_quality import update_source_states
        source_states = update_source_states()
    except Exception as e:
        logger.warning(f'learning: source states error: {e}')
        source_states = {}

    # ── 8. Записываем состояние ──────────────────────────────────────
    state = {
        'updated_at': int(time.time()),
        'own_sample': own_sample,
        'competitor_sources': comp_insights.get('sources_count', 0),
        'blended_heatmap': {str(h): round(v, 4) for h, v in blended.items()},
        'recommended_hours': recommended_hours,
        'best_content_type': best_content_type,
        'content_er': content_er,
        'competitor_hashtags': competitor_hashtags[:20],
        'applied_changes': applied_changes,
        # Флаг для воркеров — предпочтительный тип контента при автопилоте
        'prefer_video': best_content_type in ('video',),
        'prefer_multi_photo': best_content_type == 'multi_photo',
        'own_avg_views': own_summary.get('avg_views', 0),
        'own_avg_likes': own_summary.get('avg_likes', 0),
        'caption_stats': caption_result.get('caption_stats', {}),
        'caption_weights_applied': caption_result.get('caption_weights_applied'),
        'source_states': source_states,
    }

    _save_state(profile_id, state)
    logger.info(
        f'learning: цикл завершён. own_sample={own_sample}, '
        f'comp_sources={state["competitor_sources"]}, '
        f'recommended_hours={recommended_hours}'
    )
    app_state.add_log(
        f'[Обучение] Цикл завершён. Постов: {own_sample}, '
        f'часы: {recommended_hours}, тип контента: {best_content_type}',
        'info'
    )
    return state


def get_learning_state(profile_id: str) -> dict:
    """Получить текущее состояние обучения (без нового цикла)."""
    return _load_state(profile_id)


def should_download_video(profile_id: str) -> bool:
    """Стоит ли качать видео у конкурентов (на основе их лучшего ER типа контента)."""
    state = _load_state(profile_id)
    return state.get('prefer_video', False)


def get_smart_hashtags(profile_id: str) -> list[str]:
    """Хештеги конкурентов с высоким ER — для использования в публикациях."""
    state = _load_state(profile_id)
    return state.get('competitor_hashtags', [])


def learning_loop():
    """Фоновый поток — запускает цикл обучения каждый час."""
    time.sleep(120)  # старт через 2 минуты после запуска бота
    while True:
        try:
            run_learning_cycle()
        except Exception as e:
            logger.warning(f'learning_loop: {e}')
            app_state.add_log(f'[Обучение] Ошибка цикла: {e}', 'error')
        time.sleep(LEARN_INTERVAL_SEC)
