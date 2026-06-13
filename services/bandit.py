# -*- coding: utf-8 -*-
"""Батчевый UCB-бандит (из growth-отчёта).

Reward приходит с лагом 6-72ч, поэтому не real-time, а batch: статистика
пересчитывается из трекера, выбор — UCB1. Непопробованные руки исследуются
первыми; средний reward нормируется к лучшему, чтобы бонус исследования
(c=0.35) был соизмерим с эксплуатацией.
"""

import math
import random


def ucb_choose(arms: list[dict], c: float = 0.35) -> str | None:
    """Выбрать руку: [{'name', 'mean', 'trials'}]. None если рук нет.

    mean ожидается в любой неотрицательной шкале — нормируется внутри.
    """
    arms = [a for a in arms if a.get('name')]
    if not arms:
        return None

    untried = [a['name'] for a in arms if int(a.get('trials', 0)) <= 0]
    if untried:
        return random.choice(untried)

    max_mean = max(float(a.get('mean', 0.0)) for a in arms) or 1.0
    total = sum(int(a.get('trials', 0)) for a in arms)

    best_name, best_ucb = None, -1e9
    for arm in arms:
        n = int(arm.get('trials', 0))
        mean_norm = float(arm.get('mean', 0.0)) / max_mean
        ucb = mean_norm + c * math.sqrt(math.log(total + 1) / n)
        if ucb > best_ucb:
            best_ucb, best_name = ucb, arm['name']
    return best_name


def stats_to_arms(stats: dict, names: list[str] | None = None) -> list[dict]:
    """Превратить агрегаты трекера {name: {posts, avg_er}} в руки бандита.

    names — полный список рук (не попробованные получают trials=0).
    """
    keys = names if names is not None else list(stats)
    return [
        {
            'name': name,
            'mean': float(stats.get(name, {}).get('avg_er', 0.0)),
            'trials': int(stats.get(name, {}).get('posts', 0)),
        }
        for name in keys
    ]
