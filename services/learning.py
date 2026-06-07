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
    }

    _save_state(profile_id, state)
    logger.info(
        f'learning: цикл завершён. own_sample={own_sample}, '
        f'comp_sources={state["competitor_sources"]}, '
        f'recommended_hours={recommended_hours}'
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
        time.sleep(LEARN_INTERVAL_SEC)
