# -*- coding: utf-8 -*-

import time

from services.content_library import (
    CATEGORY_WEIGHTS,
    CTA_ENTRIES,
    DEFAULT_POLLS,
    ENGAGEMENT_ENTRIES,
    FORMAT_CATEGORY_WEIGHTS,
    MAX_HASHTAGS,
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
            "emoji_mode": False,
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


def test_compose_caption_caps_total_tags_and_prefers_manual(monkeypatch):
    monkeypatch.setattr(
        "services.content_library.load_library",
        lambda profile_id=None: {"enabled": False},
    )

    text = compose_caption(
        "",
        add_tags=True,
        profile_tags=["#альфа", "#бета"],
        add_profile_tags=True,
        extra_tags=["#к1", "#к2", "#к3", "#к4", "#к5"],
    )

    tags = [w for w in text.split() if w.startswith("#")]
    assert len(tags) == MAX_HASHTAGS
    assert "#альфа" in tags
    assert "#бета" in tags


def test_filter_forbidden_hashtags_removes_banned_case_insensitive():
    from services.content_library import filter_forbidden_hashtags

    out = filter_forbidden_hashtags(['#Море', '#лес', '#город'], ['море', '#ГОРОД'])

    assert out == ['#лес']


def test_caption_has_stop_word_detects_substring_case_insensitive():
    from services.content_library import caption_has_stop_word

    assert caption_has_stop_word('Купить СЕЙЧАС!', ['купить'])
    assert not caption_has_stop_word('Красивый вид', ['купить'])
    assert not caption_has_stop_word('любой текст', [])


def test_diversify_keeps_base_when_no_other_channel(monkeypatch):
    import services.content_library as cl

    monkeypatch.setattr(cl, '_load_shared_hashtags', lambda: {})
    monkeypatch.setattr(cl, '_save_shared_hashtags', lambda data: None)

    chosen = cl.diversify_hashtags(['#a', '#b', '#c', '#d'], 'me')

    assert chosen == ['#a', '#b', '#c']


def test_diversify_avoids_other_channel_recent_set(monkeypatch):
    import services.content_library as cl

    store = {'other': {'tags': ['#a', '#b', '#c'], 'ts': time.time()}}
    monkeypatch.setattr(cl, '_load_shared_hashtags', lambda: dict(store))
    saved = {}
    monkeypatch.setattr(cl, '_save_shared_hashtags', lambda data: saved.update(data))

    chosen = cl.diversify_hashtags(['#a', '#b', '#c', '#d'], 'me')

    assert frozenset(t.lower() for t in chosen) != frozenset({'#a', '#b', '#c'})
    assert len(chosen) == MAX_HASHTAGS
    assert 'me' in saved


def test_compose_caption_drops_forbidden_hashtag(monkeypatch):
    monkeypatch.setattr(
        'services.content_library.load_library',
        lambda profile_id=None: {'enabled': False, 'forbidden_hashtags': ['#бета']},
    )
    monkeypatch.setattr(
        'services.content_library.diversify_hashtags',
        lambda ordered, profile_id, **kw: ordered[:MAX_HASHTAGS],
    )

    text = compose_caption(
        '',
        add_tags=True,
        profile_tags=['#альфа', '#бета', '#гамма'],
        add_profile_tags=True,
    )

    tags = [w for w in text.split() if w.startswith('#')]
    assert '#бета' not in tags
    assert '#альфа' in tags


def test_emoji_mode_on_by_default():
    lib = _normalize_library({})
    assert lib['emoji_mode'] is True


def test_compose_emoji_mode_uses_emojis_not_text(monkeypatch):
    import services.content_library as cl

    monkeypatch.setattr(
        cl, 'load_library',
        lambda profile_id=None: {
            'emoji_mode': True, 'enabled': True, 'cta_enabled': False,
            'entries': [{'text': 'Хотели бы здесь оказаться?', 'tags': '', 'category': 'question'}],
        },
    )
    monkeypatch.setattr(cl, 'diversify_hashtags', lambda ordered, profile_id, **kw: ordered[:MAX_HASHTAGS])

    text, meta = cl.compose_caption_with_meta(
        '', add_tags=True, profile_tags=['#природа', '#красота'], add_profile_tags=True,
    )

    assert any(e in text for e in cl.EMOJI_POOL)
    assert 'Хотели бы' not in text
    assert meta == {}
    tags = [w for w in text.split() if w.startswith('#')]
    assert tags  # рандомные хэштеги присутствуют


def test_compose_emoji_mode_subscribe_cta_when_enabled(monkeypatch):
    import services.content_library as cl

    monkeypatch.setattr(
        cl, 'load_library',
        lambda profile_id=None: {'emoji_mode': True, 'cta_enabled': True},
    )
    monkeypatch.setattr(cl.random, 'random', lambda: 0.0)  # форсим показ призыва

    text, _ = cl.compose_caption_with_meta('', add_tags=False, add_profile_tags=False)
    assert any(cta in text for cta in cl.SUBSCRIBE_CTAS)


def test_compose_emoji_mode_no_cta_when_disabled(monkeypatch):
    import services.content_library as cl

    monkeypatch.setattr(
        cl, 'load_library',
        lambda profile_id=None: {'emoji_mode': True, 'cta_enabled': False},
    )
    monkeypatch.setattr(cl.random, 'random', lambda: 0.0)

    text, _ = cl.compose_caption_with_meta('', add_tags=False, add_profile_tags=False)
    assert not any(cta in text for cta in cl.SUBSCRIBE_CTAS)


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
