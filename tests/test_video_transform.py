# -*- coding: utf-8 -*-
"""Тесты антиплагиат-обработки видео (services/video_transform.py)."""

import shutil
import subprocess

import pytest

from services.video_transform import (
    ffmpeg_available,
    _build_cut_segment,
    _build_video_chain,
    transform_video,
    transform_from_profile,
    _probe_duration,
)

ffmpeg_missing = not ffmpeg_available()
skip_no_ffmpeg = pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg не установлен")


def _make_video(path, seconds=15, size='640x480'):
    subprocess.run(
        ['ffmpeg', '-y', '-f', 'lavfi', '-i', f'testsrc=duration={seconds}:size={size}:rate=25',
         '-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}',
         '-c:v', 'libx264', '-c:a', 'aac', '-pix_fmt', 'yuv420p', str(path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _make_logo(path):
    subprocess.run(
        ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=red:size=200x80:duration=1',
         '-frames:v', '1', str(path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# ── Чистые функции (без ffmpeg) ──────────────────────────────────

def test_cut_segment_skipped_for_short_video():
    expr = _build_cut_segment({'cut_seconds_min': 2, 'cut_seconds_max': 4}, duration=8.0)
    assert expr is None


def test_cut_segment_built_for_long_video():
    expr = _build_cut_segment({'cut_seconds_min': 2, 'cut_seconds_max': 4}, duration=30.0)
    assert expr is not None
    assert 'between' in expr


def test_cut_segment_disabled_when_zero():
    expr = _build_cut_segment({'cut_seconds_min': 0, 'cut_seconds_max': 0}, duration=30.0)
    assert expr is None


def test_video_chain_includes_crop_and_eq():
    chain = _build_video_chain({'crop_percent': 0.05, 'color_shift': True})
    assert 'crop=' in chain
    assert 'eq=' in chain
    assert 'scale=trunc' in chain


def test_video_chain_empty_transforms_still_aligns():
    chain = _build_video_chain({})
    assert 'scale=trunc' in chain


# ── Интеграция с ffmpeg ──────────────────────────────────────────

@skip_no_ffmpeg
def test_transform_cuts_seconds(tmp_path):
    src = tmp_path / 'v.mp4'
    _make_video(src, seconds=15)
    before = _probe_duration(src)
    ok = transform_video(
        src,
        {'cut_seconds_min': 2, 'cut_seconds_max': 4, 'speed': 1.0},
    )
    after = _probe_duration(src)
    assert ok
    assert after < before - 1.5  # вырезано минимум ~2 сек


@skip_no_ffmpeg
def test_transform_applies_logo_and_metadata(tmp_path):
    src = tmp_path / 'v.mp4'
    logo = tmp_path / 'logo.png'
    _make_video(src, seconds=15)
    _make_logo(logo)
    ok = transform_video(
        src,
        {'crop_percent': 0.05, 'color_shift': True, 'speed': 1.02},
        logo_path=logo,
        logo_scale=0.2,
        metadata={'title': 'MyChannel', 'artist': '@mygroup'},
    )
    assert ok
    tags = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format_tags=title,artist',
         '-of', 'default=noprint_wrappers=1', str(src)],
        stdout=subprocess.PIPE,
    ).stdout.decode()
    assert 'MyChannel' in tags
    assert '@mygroup' in tags


@skip_no_ffmpeg
def test_transform_from_profile_disabled_when_no_antiplagiat(tmp_path):
    src = tmp_path / 'v.mp4'
    _make_video(src, seconds=15)
    profile = {'antiplagiaat': {'enabled': False}, 'watermark': {'enabled': False}}
    assert transform_from_profile(src, profile) is False


@skip_no_ffmpeg
def test_transform_from_profile_runs_with_antiplagiat(tmp_path):
    src = tmp_path / 'v.mp4'
    _make_video(src, seconds=15)
    before = _probe_duration(src)
    profile = {
        'antiplagiaat': {'enabled': True},
        'watermark': {'enabled': False},
        'video_transform': {'hard_mode': True, 'cut_seconds_min': 2, 'cut_seconds_max': 4},
    }
    ok = transform_from_profile(src, profile, title='Test')
    after = _probe_duration(src)
    assert ok
    assert after < before  # хоть что-то изменилось по длительности


def test_transform_missing_file_returns_false(tmp_path):
    assert transform_video(tmp_path / 'nope.mp4', {'crop_percent': 0.05}) is False


def test_auto_crop_percent_range_is_softer(monkeypatch, tmp_path):
    """User feedback: crop was too aggressive and degraded quality —
    reduce the auto-random crop range from 4-8% to 1-3%."""
    import random
    from services import video_transform

    src = tmp_path / 'v.mp4'
    src.write_bytes(b'fake')

    profile = {
        'antiplagiaat': {'enabled': True},
        'video_transform': {'hard_mode': True, 'crop_percent': 0.0},
        'watermark': {},
    }

    captured = {}

    def fake_transform_video(video_path, transforms, **kwargs):
        captured['crop_percent'] = transforms['crop_percent']
        return True

    monkeypatch.setattr(video_transform, 'transform_video', fake_transform_video)
    monkeypatch.setattr(video_transform, 'apply_finishing', lambda *a, **k: False)

    random.seed(1)
    for _ in range(50):
        video_transform.transform_from_profile(src, profile, is_clip=False)
        assert 0.01 <= captured['crop_percent'] <= 0.03


def test_fade_probability_reduced(monkeypatch, tmp_path):
    """User feedback: fade was too aggressive (appeared too often).
    Reduce random fade probability from 50% to 20%."""
    import random
    from services import video_transform

    src = tmp_path / 'v.mp4'
    src.write_bytes(b'fake')

    profile = {
        'antiplagiaat': {'enabled': True},
        'video_transform': {'hard_mode': True},
        'watermark': {},
    }

    captured_fades = []

    def fake_transform_video(video_path, transforms, **kwargs):
        return True

    def fake_apply_finishing(video_path, **kwargs):
        captured_fades.append(kwargs['fade'])
        return False

    monkeypatch.setattr(video_transform, 'transform_video', fake_transform_video)
    monkeypatch.setattr(video_transform, 'apply_finishing', fake_apply_finishing)

    random.seed(42)
    for _ in range(200):
        video_transform.transform_from_profile(src, profile, is_clip=False)

    fade_rate = sum(captured_fades) / len(captured_fades)
    assert fade_rate < 0.3, f"fade rate {fade_rate} too high, expected ~0.2"
