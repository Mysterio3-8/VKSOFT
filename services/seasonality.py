# -*- coding: utf-8 -*-
"""Сезонные веса источников (таблица из growth-отчёта).

Бот не видит картинку, поэтому сезонность привязана к source_bucket —
ручной метке источника (`"bucket": "sea"` в config.json → sources).
Источники без метки получают вес 1.0 и порядок не теряют.
"""

import time
from datetime import datetime

SEASON_BY_MONTH = {
    12: 'winter', 1: 'winter', 2: 'winter',
    3: 'spring', 4: 'spring', 5: 'spring',
    6: 'summer', 7: 'summer', 8: 'summer',
    9: 'autumn', 10: 'autumn', 11: 'autumn',
}

# source_bucket → вес по сезону (лето/осень/зима/весна), таблица отчёта
SEASON_WEIGHTS = {
    'sea':       {'summer': 1.30, 'autumn': 0.95, 'winter': 0.80, 'spring': 1.10},
    'mountain':  {'summer': 1.15, 'autumn': 1.10, 'winter': 1.00, 'spring': 1.15},
    'forest':    {'summer': 0.95, 'autumn': 1.25, 'winter': 1.10, 'spring': 1.05},
    'snow':      {'summer': 0.70, 'autumn': 0.95, 'winter': 1.35, 'spring': 0.80},
    'waterfall': {'summer': 0.95, 'autumn': 0.90, 'winter': 0.85, 'spring': 1.25},
}

# Синонимы для удобства разметки в UI
_BUCKET_ALIASES = {
    'lake': 'sea', 'tropical': 'sea', 'ocean': 'sea', 'beach': 'sea',
    'hiking': 'mountain', 'mountains': 'mountain',
    'fog': 'forest', 'cabin': 'forest', 'cabins': 'forest',
    'northern': 'snow', 'winter': 'snow',
    'waterfalls': 'waterfall', 'bloom': 'waterfall',
}


def detect_season(month: int | None = None) -> str:
    m = month or datetime.fromtimestamp(time.time()).month
    return SEASON_BY_MONTH.get(int(m), 'summer')


def source_season_weight(source: dict, season: str | None = None) -> float:
    bucket = str(source.get('bucket', '') or '').strip().lower()
    bucket = _BUCKET_ALIASES.get(bucket, bucket)
    weights = SEASON_WEIGHTS.get(bucket)
    if not weights:
        return 1.0
    return weights.get(season or detect_season(), 1.0)


def order_sources_by_season(sources: list, season: str | None = None) -> list:
    """Источники в порядке убывания сезонного веса (стабильная сортировка)."""
    season = season or detect_season()
    return sorted(sources, key=lambda s: source_season_weight(s, season), reverse=True)
