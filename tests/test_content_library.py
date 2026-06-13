# -*- coding: utf-8 -*-

import time

from services.content_library import (
    CATEGORY_WEIGHTS,
    CTA_ENTRIES,
    DEFAULT_POLLS,
    ENGAGEMENT_ENTRIES,
    FORMAT_CATEGORY_WEIGHTS,
    MISSION_ENTRIES,
    QUESTION_ENTRIES,
    RATING_ENTRIES,
    UNIVERSAL_ENTRIES,
    _filter_cooldown,
    _normalize_library,
    compose_caption,
    dedupe_hashtags,
    get_random_entry,
)


def test_each_family_has_100_unique_ids():
    families = {
        'Q': QUESTION_ENTRIES,
        'E': ENGAGEMENT_ENTRIES,
        'M': MISSION_ENTRIES,
        'C': CTA_ENTRIES,
        'R': RATING_ENTRIES,
    }
    for prefix, entries in families.items():
        assert len(entries) == 100
        ids = [e['id'] for e in entries]
        assert len(set(ids)) == 100
        assert all(i.startswith(prefix) for i in ids)
        assert all(e['text'].strip() for e in entries)


def test_universal_entries_combine_all_categories():
    assert len(UNIVERSAL_ENTRIES) == 500
    categories = {entry['category'] for entry in UNIVERSAL_ENTRIES}
    assert categories == set(CATEGORY_WEIGHTS)


def test_mission_statements_avoid_seasonal_and_object_specific_claims():
    # Миссия — утверждения о кадре, не должны называть конкретные
    # объекты/сезоны (бот не видит содержимое медиа). Вопросы/промпты/CTA —
    # обращение к зрителю, им можно («Море или горы?»).
    banned = (
        "зима", "зимой", "снег", "лето", "летом", "осень", "весна",
        "море", "горы", "девушка", "девушки", "утро", "вечер", "ночь",
    )
    texts = " ".join(f"{item['text']} {item['tags']}" for item in MISSION_ENTRIES).lower()
    offenders = [word for word in banned if word in texts]
    assert offenders == []


def test_format_weights_differ_for_photo_and_clip():
    photo = FORMAT_CATEGORY_WEIGHTS['photo']
    clip = FORMAT_CATEGORY_WEIGHTS['clip']
    assert sum(photo.values()) == 100
    assert sum(clip.values()) == 100
    # У клипов CTA — главное семейство, у фото — вопросы
    assert max(clip, key=clip.get) == 'cta'
    assert max(photo, key=photo.get) == 'question'


def test_get_random_entry_uses_format_weights(monkeypatch):
    entries = [
        {'category': c, 'text': f'{c} текст', 'tags': ''}
        for c in CATEGORY_WEIGHTS
    ]
    monkeypatch.setattr(
        "services.content_library.load_library",
        lambda profile_id=None: {
            "entries": entries,
            "category_weights": {fmt: dict(w) for fmt, w in FORMAT_CATEGORY_WEIGHTS.items()},
        },
    )

    captured = {}

    def fake_choices(categories, weights, k):
        captured['weights'] = dict(zip(categories, weights))
        return ['cta']

    monkeypatch.setattr("services.content_library.random.choices", fake_choices)

    entry = get_random_entry(media_format='clip')

    assert entry['category'] == 'cta'
    assert captured['weights'] == FORMAT_CATEGORY_WEIGHTS['clip']


def test_filter_cooldown_excludes_recently_used(monkeypatch):
    now = time.time()
    monkeypatch.setattr(
        "services.content_library._load_usage",
        lambda: {'Q001': now - 86400, 'Q002': now - 20 * 86400},
    )
    entries = [
        {'id': 'Q001', 'text': 'вчера использована'},
        {'id': 'Q002', 'text': '20 дней назад'},
        {'id': 'Q003', 'text': 'никогда'},
    ]

    fresh = _filter_cooldown(entries, cooldown_days=14)

    assert [e['id'] for e in fresh] == ['Q002', 'Q003']


def test_filter_cooldown_falls_back_when_everything_recent(monkeypatch):
    now = time.time()
    monkeypatch.setattr(
        "services.content_library._load_usage",
        lambda: {'Q001': now, 'Q002': now},
    )
    entries = [{'id': 'Q001', 'text': 'а'}, {'id': 'Q002', 'text': 'б'}]

    assert _filter_cooldown(entries, cooldown_days=14) == entries


def test_dedupe_hashtags_keeps_only_one_copy_case_insensitive():
    result = dedupe_hashtags("#Кадр #настроение", ["#кадр", "эстетика", "#Настроение"])

    assert result == "#Кадр #настроение #эстетика"


def test_compose_caption_adds_universal_and_profile_tags_once(monkeypatch):
    monkeypatch.setattr(
        "services.content_library.load_library",
        lambda profile_id=None: {
            "enabled": True,
            "cta_enabled": False,
            "universal_mode": True,
            "entries": [{"text": "Зима в кадре.", "tags": "#зима"}],
        },
    )
    monkeypatch.setattr(
        "services.content_library.random.choice",
        lambda entries: {"text": "Просто красиво.", "tags": "#красота #кадр"},
    )

    text = compose_caption(
        "",
        add_tags=True,
        profile_tags=["#кадр", "настроение"],
        add_profile_tags=True,
    )

    assert text.count("#кадр") == 1
    assert "#настроение" in text
    assert "Зима" not in text


def test_normalize_library_replaces_old_entries_and_migrates_weights():
    lib = _normalize_library({
        "enabled": True,
        "universal_mode": True,
        "entries": [{"text": "Зима в кадре.", "tags": "#зима"}],
        "polls": [{"question": "Любишь зиму?", "answers": ["Да", "Нет"]}],
        # Легаси-формат весов (плоский словарь) → заменяется дефолтами по форматам
        "category_weights": {"question": 50, "emotion": 30, "mission": 20},
    })

    assert lib["entries"] == UNIVERSAL_ENTRIES
    assert lib["polls"] == DEFAULT_POLLS
    assert lib["category_weights"] == FORMAT_CATEGORY_WEIGHTS
    assert lib["caption_cooldown_days"] == 14
