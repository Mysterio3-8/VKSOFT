# -*- coding: utf-8 -*-
"""
Growth tasks:
- Трекинг подписчиков (каждый час)
- Гивэвей-посты (по расписанию)
- Пин-менеджер (лучший пост недели)
- Stories автопостинг
"""

import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

import vk_api

from config import app_state, STORAGE_DIR
from vk.api import get_vk_api, vk_call_safe


# ── Шаблоны гивэвея ──────────────────────────────────────────────

GIVEAWAY_TEMPLATES = [
    """🎁 РОЗЫГРЫШ ДЛЯ ЛЮБИТЕЛЕЙ ПРИРОДЫ!

Разыгрываем {prize} среди подписчиков канала.

Условия:
✅ Подпишись на канал
✅ Сделай репост этой записи
✅ Напиши в комментарии своё любимое место в природе

Итоги подведём {date}. Удачи! 🌿

#розыгрыш #конкурс #природа #подарок""",

    """🌿 КОНКУРС «ПРИРОДА ГЛАЗАМИ ПОДПИСЧИКА»

Поделись своим лучшим фото природы в комментарии!

🥇 Лучшее фото — выбираем вместе с подписчиками
🎁 Победитель получает {prize}

Участвовать просто:
✅ Подпишись на канал
✅ Репостни эту запись
✅ Прикрепи фото природы в комментарии

Итоги: {date} 📸

#конкурс #природа #фото #розыгрыш""",

    """✨ ДАРИМ ПОДПИСЧИКАМ!

Наш канал растёт — и мы благодарим вас!

Разыгрываем {prize} просто так 🌱

Для участия:
1️⃣ Подпишись на канал
2️⃣ Сделай репост
3️⃣ Напиши любой комментарий

Победитель выбирается случайно {date}.
Расскажи друзьям — больше участников, больше шансов! 🍀

#конкурс #розыгрыш #природа #подарок""",
]

GIVEAWAY_PRIZES = [
    "книгу о природе",
    "подписку на Premium на 3 месяца",
    "набор для рисования акварелью",
    "фотоальбом с природой России",
    "сертификат в магазин туристического снаряжения",
]


# ── Хранилище трекинга подписчиков ───────────────────────────────

def _members_history_file() -> Path:
    return STORAGE_DIR / app_state.active_profile_id / 'members_history.json'


def _load_history() -> list:
    f = _members_history_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            pass
    return []


def _save_history(data: list):
    f = _members_history_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    # Хранить максимум 365 точек
    if len(data) > 365:
        data = data[-365:]
    f.write_text(json.dumps(data), encoding='utf-8')


# ── Трекинг подписчиков ───────────────────────────────────────────

def track_subscribers_once() -> dict:
    """Один запрос к VK, сохранить точку данных."""
    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    token = vk_cfg.get('user_token', '').strip()
    gid   = vk_cfg.get('group_id', '').strip()
    if not token or not gid:
        return {}

    try:
        vk = get_vk_api(token, vk_cfg.get('api_version', '5.131'))
        resp = vk_call_safe(
            vk.groups.getById,
            group_id=gid.lstrip('-'),
            fields='members_count',
        )
        group = resp[0] if isinstance(resp, list) and resp else {}
        members = group.get('members_count', 0)
        point = {
            'ts':      int(time.time()),
            'date':    datetime.now().strftime('%Y-%m-%d'),
            'members': members,
        }
        history = _load_history()
        # Не добавлять дубли за тот же час
        now_hour = datetime.now().strftime('%Y-%m-%d %H')
        existing_hours = set()
        for p in history:
            dt = datetime.fromtimestamp(p['ts']).strftime('%Y-%m-%d %H')
            existing_hours.add(dt)
        if now_hour not in existing_hours:
            history.append(point)
            _save_history(history)
        return point
    except Exception as e:
        app_state.add_log(f'Трекинг подписчиков: {e}', 'warning')
        return {}


def get_growth_stats() -> dict:
    """Статистика роста для дашборда."""
    history = _load_history()
    if not history:
        return {'members': 0, 'diff_today': 0, 'diff_week': 0, 'diff_month': 0,
                'to_1m': 0, 'days_to_1m': None, 'chart': [], 'growth_rate': 0}

    current = history[-1]['members']
    now = datetime.now()

    def members_n_days_ago(n):
        cutoff = (now - timedelta(days=n)).timestamp()
        past = [p for p in history if p['ts'] <= cutoff]
        return past[-1]['members'] if past else current

    today_start = now.replace(hour=0, minute=0, second=0).timestamp()
    today_past = [p for p in history if p['ts'] <= today_start]
    members_yesterday = today_past[-1]['members'] if today_past else current

    diff_today  = current - members_yesterday
    diff_week   = current - members_n_days_ago(7)
    diff_month  = current - members_n_days_ago(30)

    # Прогноз до 1M
    to_1m = max(0, 1_000_000 - current)
    days_to_1m = None
    if diff_week > 0:
        weekly_rate = diff_week / 7
        days_to_1m = round(to_1m / weekly_rate) if weekly_rate > 0 else None

    # График последних 30 дней (по одной точке в день)
    chart = []
    seen_dates = set()
    for p in sorted(history, key=lambda x: x['ts']):
        d = p['date']
        if d not in seen_dates:
            seen_dates.add(d)
            chart.append({'date': d, 'members': p['members']})
    chart = chart[-30:]

    return {
        'members':     current,
        'diff_today':  diff_today,
        'diff_week':   diff_week,
        'diff_month':  diff_month,
        'to_1m':       to_1m,
        'days_to_1m':  days_to_1m,
        'chart':       chart,
        'growth_rate': round(diff_week / 7, 1) if diff_week else 0,
    }


# ── Гивэвей ───────────────────────────────────────────────────────

def post_giveaway(vk_group, owner_id: str, prize: str = None, days_until: int = 7):
    """Опубликовать гивэвей-пост в канале."""
    template = random.choice(GIVEAWAY_TEMPLATES)
    if not prize:
        prize = random.choice(GIVEAWAY_PRIZES)
    date_str = (datetime.now() + timedelta(days=days_until)).strftime('%d.%m.%Y')
    text = template.format(prize=prize, date=date_str)

    try:
        result = vk_call_safe(vk_group.wall.post, owner_id=owner_id, message=text)
        post_id = result.get('post_id') if result else None
        app_state.add_log(f'Гивэвей: ✅ опубликован (пост {post_id})', 'info')
        return post_id
    except Exception as e:
        app_state.add_log(f'Гивэвей ошибка: {e}', 'error')
        return None


# ── Пин-менеджер ─────────────────────────────────────────────────

def update_pinned_post() -> bool:
    """Найти пост с максимальными лайками за 7 дней и закрепить его."""
    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    group_id   = vk_cfg.get('group_id', '').strip()
    api_ver    = vk_cfg.get('api_version', '5.131')

    if not user_token or not group_id:
        return False

    gid_num  = int(group_id.lstrip('-'))
    owner_id = f'-{gid_num}'
    week_ago = int((datetime.now() - timedelta(days=7)).timestamp())

    try:
        vk = get_vk_api(user_token, api_ver)
        resp = vk_call_safe(
            vk.wall.get,
            owner_id=owner_id,
            count=50,
            filter='owner',
        )
        posts = resp.get('items', []) if isinstance(resp, dict) else []

        # Фильтр: только посты за последние 7 дней
        recent = [p for p in posts if p.get('date', 0) >= week_ago and not p.get('is_pinned')]
        if not recent:
            app_state.add_log('Пин-менеджер: нет свежих постов за 7 дней', 'info')
            return False

        best = max(recent, key=lambda p: p.get('likes', {}).get('count', 0))
        best_id = best['id']
        likes   = best.get('likes', {}).get('count', 0)

        vk_call_safe(vk.wall.pin, owner_id=owner_id, post_id=best_id)
        app_state.add_log(
            f'Пин-менеджер: ✅ закреплён пост {best_id} ({likes} лайков)',
            'info'
        )
        return True

    except vk_api.exceptions.ApiError as e:
        app_state.add_log(f'Пин-менеджер VK {getattr(e,"code",0)}: {e}', 'error')
        return False
    except Exception as e:
        app_state.add_log(f'Пин-менеджер ошибка: {e}', 'error')
        return False


# ── Фоновый поток трекинга ────────────────────────────────────────

def subscriber_tracker_loop():
    """Каждый час фиксировать количество подписчиков."""
    while True:
        try:
            point = track_subscribers_once()
            if point.get('members'):
                stats = get_growth_stats()
                # Алерт если рост замедлился (меньше 10 в день при темпе >100)
                if stats['growth_rate'] > 100 and stats['diff_today'] < 10:
                    app_state.add_log(
                        f'Рост замедлился: сегодня +{stats["diff_today"]}, обычный темп +{stats["growth_rate"]}/день',
                        'warning'
                    )
        except Exception as e:
            app_state.add_log(f'subscriber_tracker_loop: {e}', 'warning')
        time.sleep(3600)
