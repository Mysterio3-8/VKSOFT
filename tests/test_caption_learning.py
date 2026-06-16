# -*- coding: utf-8 -*-
"""Цикл «опубликовать → измерить → масштабировать»: подписи, score, повторы."""

from services.content_library import CATEGORY_WEIGHTS, compose_caption_with_meta
from services.learning import MIN_CAPTION_POSTS, compute_caption_weights
from services.tracker import (
    build_caption_stats,
    build_format_baselines,
    caption_engagement_score,
    compute_post_score,
    post_velocity,
)
from workers.repeat_winners import pick_winner

DAY = 86400


def _post(views=100, likes=10, comments=0, reposts=0, category='question', **extra):
    post = {
        'post_id': extra.pop('post_id', 1),
        'checked': True,
        'views': views,
        'likes': likes,
        'comments': comments,
        'reposts': reposts,
        'caption_category': category,
        'published_at': extra.pop('published_at', 0),
    }
    post.update(extra)
    return post


# ── tracker: engagement и caption stats ──────────────────────────

def test_caption_engagement_score_uses_report_formula():
    # лайки×1 + комменты×4 + репосты×8
    assert caption_engagement_score({'likes': 1, 'comments': 1, 'reposts': 1}) == 13


def test_build_caption_stats_aggregates_per_category():
    data = [
        _post(views=100, likes=10, category='question'),
        _post(views=200, likes=10, comments=2, category='question'),
        _post(views=100, likes=5, category='engagement'),
        _post(views=100, likes=99, category='question', checked=False),   # не проверен
        _post(views=0, likes=99, category='engagement'),                   # нет охвата
        {'post_id': 9, 'checked': True, 'views': 50, 'likes': 1},          # без подписи
    ]

    stats = build_caption_stats(data)

    assert set(stats) == {'question', 'engagement'}
    assert stats['question']['posts'] == 2
    # ER: (10/100 + (10+8)/200) / 2 = 0.095
    assert stats['question']['avg_er'] == 0.095


def test_build_caption_stats_filters_by_media_type():
    data = [
        _post(category='question', media_type='photo'),
        _post(category='question', media_type='clip'),
        _post(category='cta', media_type='clip'),
    ]

    clip_stats = build_caption_stats(data, media_type='clip')

    assert clip_stats['question']['posts'] == 1
    assert clip_stats['cta']['posts'] == 1


# ── tracker: снимки и нормированный score ─────────────────────────

def test_post_velocity_from_snapshots():
    post = {'snapshots': {'1': {'views': 50}, '24': {'views': 200}}}
    assert post_velocity(post) == 0.25
    assert post_velocity({'snapshots': {'1': {'views': 50}}}) is None


def test_compute_post_score_is_relative_to_format_median():
    # Два фото с одинаковым ER и просмотрами → оба score 1.0; клип с
    # огромными views не получает преимущества над своей же медианой.
    photos = [
        _post(post_id=1, views=100, likes=10, media_type='photo'),
        _post(post_id=2, views=100, likes=10, media_type='photo'),
    ]
    clips = [
        _post(post_id=3, views=10000, likes=100, media_type='clip'),
        _post(post_id=4, views=10000, likes=100, media_type='clip'),
    ]
    data = photos + clips
    baselines = build_format_baselines(data)

    assert compute_post_score(photos[0], baselines) == 1.0
    assert compute_post_score(clips[0], baselines) == 1.0


def test_compute_post_score_rewards_winner_within_format():
    data = [
        _post(post_id=1, views=100, likes=10, media_type='photo'),
        _post(post_id=2, views=100, likes=10, media_type='photo'),
        _post(post_id=3, views=300, likes=90, media_type='photo'),
    ]
    baselines = build_format_baselines(data)

    scores = {p['post_id']: compute_post_score(p, baselines) for p in data}

    assert scores[3] > 1.5  # promote-порог из отчёта
    assert scores[1] < scores[3]


# ── learning: веса семейств ───────────────────────────────────────

def _stats(er_by_category: dict, posts=MIN_CAPTION_POSTS):
    return {
        c: {'posts': posts, 'avg_er': er_by_category.get(c, 0.05)}
        for c in CATEGORY_WEIGHTS
    }


def test_compute_caption_weights_rewards_winning_category():
    weights = compute_caption_weights(_stats({'question': 0.25}))

    assert sum(weights.values()) == 100
    assert max(weights, key=weights.get) == 'question'
    # Проигравшие семейства не умирают — floor оставляет их в тесте
    assert all(w >= 10 for w in weights.values())


def test_compute_caption_weights_needs_enough_posts_per_category():
    stats = _stats({'question': 0.1})
    stats['mission']['posts'] = MIN_CAPTION_POSTS - 1

    assert compute_caption_weights(stats) is None


def test_compute_caption_weights_no_signal_when_er_zero():
    stats = {c: {'posts': MIN_CAPTION_POSTS, 'avg_er': 0.0} for c in CATEGORY_WEIGHTS}
    assert compute_caption_weights(stats) is None


# ── content_library: meta ─────────────────────────────────────────

def test_compose_caption_with_meta_returns_chosen_entry(monkeypatch):
    monkeypatch.setattr(
        "services.content_library.load_library",
        lambda profile_id=None: {
            "enabled": True,
            "emoji_mode": False,
            "cta_enabled": False,
            "entries": [{
                "id": "M005",
                "category": "mission",
                "text": "Дыхание мира — это красота, которую нельзя потерять.",
                "tags": "#дыханиемира",
            }],
        },
    )
    monkeypatch.setattr("services.content_library._record_usage", lambda entry: None)

    text, meta = compose_caption_with_meta("", add_tags=True)

    assert "Дыхание мира" in text
    assert meta == {
        'caption_category': 'mission',
        'caption_text': 'Дыхание мира — это красота, которую нельзя потерять.',
        'caption_id': 'M005',
    }


def test_compose_caption_with_meta_empty_when_library_disabled(monkeypatch):
    monkeypatch.setattr(
        "services.content_library.load_library",
        lambda profile_id=None: {"enabled": False, "emoji_mode": False},
    )

    text, meta = compose_caption_with_meta("Исходный текст", add_tags=False)

    assert text == "Исходный текст"
    assert meta == {}


# ── repeat winners: candidate selection ───────────────────────────

def test_pick_winner_prefers_engagement_over_views():
    now = 100 * DAY
    data = [
        _post(post_id=1, views=1000, likes=5, published_at=now - 40 * DAY),
        _post(post_id=2, views=500, likes=5, comments=10, reposts=5, published_at=now - 40 * DAY),
    ]

    winner = pick_winner(data, now, min_views=200, cooldown_days=30)

    assert winner['post_id'] == 2


def test_pick_winner_respects_cooldown_and_min_views():
    now = 100 * DAY
    data = [
        _post(post_id=1, views=1000, published_at=now - 10 * DAY),                       # слишком свежий
        _post(post_id=2, views=50, published_at=now - 40 * DAY),                         # мало охвата
        _post(post_id=3, views=1000, published_at=now - 40 * DAY,
              republished_at=now - 5 * DAY),                                             # недавно повторён
    ]

    assert pick_winner(data, now, min_views=200, cooldown_days=30) is None


def test_pick_winner_skips_missing_and_unchecked():
    now = 100 * DAY
    data = [
        _post(post_id=1, views=1000, published_at=now - 40 * DAY, missing=True),
        _post(post_id=2, views=1000, published_at=now - 40 * DAY, checked=False),
    ]

    assert pick_winner(data, now, min_views=200, cooldown_days=30) is None
