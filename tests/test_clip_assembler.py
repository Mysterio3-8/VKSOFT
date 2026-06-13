# -*- coding: utf-8 -*-
"""Clip assembler: hook-оверлеи и подготовка текста для drawtext."""

from services.clip_assembler import (
    CTA_OVERLAYS,
    OVERLAY_FAMILIES,
    drawtext_escape,
    pick_overlay,
    wrap_hook,
)


def test_overlay_families_match_report_spec():
    assert set(OVERLAY_FAMILIES) == {'curiosity', 'escape', 'scale', 'rating'}
    for family, hooks in OVERLAY_FAMILIES.items():
        assert hooks, family
        for hook in hooks:
            # Отчёт: hook 3-8 слов, overlay ≤ 42 символов
            assert len(hook) <= 42, hook
            assert 1 <= len(hook.split()) <= 8, hook
    assert all(len(c) <= 42 for c in CTA_OVERLAYS)


def test_pick_overlay_returns_family_and_its_text():
    family, text = pick_overlay()
    assert family in OVERLAY_FAMILIES
    assert text in OVERLAY_FAMILIES[family]


def test_wrap_hook_short_text_unchanged():
    assert wrap_hook('Город подождёт') == 'Город подождёт'


def test_wrap_hook_splits_long_text_near_middle():
    wrapped = wrap_hook('Такие места не показывают в новостях')
    lines = wrapped.split('\n')
    assert len(lines) == 2
    # Перенос близко к середине — ни одна строка не «обрублена»
    assert all(lines)
    assert abs(len(lines[0]) - len(lines[1])) <= 10


def test_drawtext_escape_protects_filter_chars():
    escaped = drawtext_escape("Оценка: 10% — л'учшее")
    assert '\\:' in escaped
    assert '\\%' in escaped
    assert "'" not in escaped.replace("\\'", '')  # одинарных кавычек не осталось


def test_pick_from_dirs_filters_by_extension(tmp_path):
    from services.clip_assembler import pick_from_dirs

    (tmp_path / 'track.mp3').write_bytes(b'x')
    (tmp_path / 'clip.mp4').write_bytes(b'x')
    (tmp_path / 'readme.txt').write_bytes(b'x')

    audio = pick_from_dirs([tmp_path, tmp_path / 'absent'], ('.mp3',))
    video = pick_from_dirs([tmp_path], ('.mp4', '.mov'))

    assert [p.name for p in audio] == ['track.mp3']
    assert [p.name for p in video] == ['clip.mp4']
