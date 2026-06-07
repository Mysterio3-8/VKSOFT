# -*- coding: utf-8 -*-

from services.content_library import (
    DEFAULT_POLLS,
    UNIVERSAL_ENTRIES,
    _normalize_library,
    compose_caption,
    dedupe_hashtags,
)


def test_universal_entries_avoid_seasonal_and_object_specific_words():
    banned = (
        "зима", "зимой", "снег", "лето", "летом", "осень", "весна",
        "море", "горы", "лес", "город", "девушка", "девушки", "утро",
        "вечер", "ночь",
    )

    texts = " ".join(f"{item['text']} {item['tags']}" for item in UNIVERSAL_ENTRIES).lower()

    assert UNIVERSAL_ENTRIES
    assert not any(word in texts for word in banned)


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


def test_normalize_library_replaces_old_specific_entries_and_polls():
    lib = _normalize_library({
        "enabled": True,
        "universal_mode": True,
        "entries": [{"text": "Зима в кадре.", "tags": "#зима"}],
        "polls": [{"question": "Любишь зиму?", "answers": ["Да", "Нет"]}],
    })

    assert lib["entries"] == UNIVERSAL_ENTRIES
    assert lib["polls"] == DEFAULT_POLLS
