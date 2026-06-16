# -*- coding: utf-8 -*-
"""Жёсткий антиплагиат для видео/клипов через ffmpeg.

Цель — чтобы VK-алгоритмы не сматчили видео с оригиналом, и чтобы разница
была заметна глазу. Один проход ffmpeg применяет все эффекты разом:

  - вырезание случайных 2-4 секунд из середины (сильнее всего ломает хэш)
  - кроп краёв + zoom обратно (меняет геометрию кадра)
  - наложение PNG-логотипа в выбранном углу
  - коррекция яркости/контраста/насыщенности + лёгкий поворот/шум
  - изменение скорости видео и аудио синхронно
  - очистка метаданных оригинала + подмена своими

ffmpeg должен быть в PATH. Если недоступен — возвращаем False, видео заливается
как есть.
"""

import random
import shutil
import subprocess
from pathlib import Path

from config import logger

# Угол → выражение позиции для overlay. {m} = отступ от края.
_OVERLAY_POSITIONS = {
    'bottom_right': 'main_w-overlay_w-{m}:main_h-overlay_h-{m}',
    'bottom_left':  '{m}:main_h-overlay_h-{m}',
    'top_right':    'main_w-overlay_w-{m}:{m}',
    'top_left':     '{m}:{m}',
    'center':       '(main_w-overlay_w)/2:(main_h-overlay_h)/2',
}

_FFMPEG_TIMEOUT_SEC = 1200


def ffmpeg_available() -> bool:
    return shutil.which('ffmpeg') is not None


def _probe_duration(path: Path) -> float:
    """Длительность видео в секундах через ffprobe. 0.0 если не удалось."""
    if not shutil.which('ffprobe'):
        return 0.0
    try:
        out = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60,
        )
        return float(out.stdout.decode().strip() or 0.0)
    except Exception:
        return 0.0


def _probe_dims(path: Path) -> tuple[int, int]:
    """Ширина и высота первого видеопотока. (0, 0) если не удалось."""
    if not shutil.which('ffprobe'):
        return 0, 0
    try:
        out = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60,
        )
        w_str, h_str = out.stdout.decode().strip().splitlines()[0].split('x')[:2]
        return int(w_str), int(h_str)
    except Exception:
        return 0, 0


def apply_finishing(
    video_path: str | Path,
    *,
    aspect_mode: str = 'original',
    blur_strength: int = 20,
    frame_px: int = 0,
    frame_color: str = 'black',
    fade: bool = False,
    fade_duration: float = 0.6,
) -> bool:
    """Второй проход ffmpeg: формат кадра, рамка, фейды. Обрабатывает на месте.

    aspect_mode: original | square_crop | square_blur | vertical_blur (9:16).
    blur-режимы кладут видео на размытую копию самого себя (плашки по бокам).
    """
    path = Path(video_path)
    need_aspect = aspect_mode in ('square_crop', 'square_blur', 'vertical_blur')
    if not (need_aspect or frame_px > 0 or fade):
        return False
    if not path.exists() or not ffmpeg_available():
        return False

    w, h = _probe_dims(path)
    duration = _probe_duration(path)
    if w <= 0 or h <= 0:
        return False

    tail: list[str] = []
    if frame_px > 0:
        tail.append(f'pad=iw+{2 * frame_px}:ih+{2 * frame_px}:{frame_px}:{frame_px}:color={frame_color}')
    if fade and duration > fade_duration * 3:
        fd = fade_duration
        tail.append(f'fade=t=in:st=0:d={fd:.2f},fade=t=out:st={duration - fd:.2f}:d={fd:.2f}')
    tail.append('scale=trunc(iw/2)*2:trunc(ih/2)*2')
    tail_chain = ','.join(tail)

    if aspect_mode in ('square_blur', 'vertical_blur'):
        if aspect_mode == 'square_blur':
            side = max(w, h) // 2 * 2
            canvas_w = canvas_h = side
        else:
            canvas_h = max(h, int(w * 16 / 9)) // 2 * 2
            canvas_w = int(canvas_h * 9 / 16) // 2 * 2
        if canvas_w <= w + 4 and canvas_h <= h + 4 and not (frame_px > 0 or fade):
            return False  # уже нужный формат
        filter_complex = (
            f'[0:v]split[fg][bgsrc];'
            f'[bgsrc]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,'
            f'crop={canvas_w}:{canvas_h},boxblur={blur_strength}[bg];'
            f'[bg][fg]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2,{tail_chain}[vout]'
        )
    elif aspect_mode == 'square_crop':
        side = min(w, h) // 2 * 2
        filter_complex = f'[0:v]crop={side}:{side},{tail_chain}[vout]'
    else:
        filter_complex = f'[0:v]{tail_chain}[vout]'

    if fade and duration > fade_duration * 3:
        fd = fade_duration
        a_chain = f'afade=t=in:st=0:d={fd:.2f},afade=t=out:st={duration - fd:.2f}:d={fd:.2f}'
    else:
        a_chain = 'anull'
    filter_complex += f';[0:a]{a_chain}[aout]'

    out_path = path.with_name(f'{path.stem}_f.mp4')
    cmd = [
        'ffmpeg', '-y', '-i', str(path),
        '-filter_complex', filter_complex,
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        '-movflags', '+faststart', str(out_path),
    ]
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=_FFMPEG_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f'video_transform finishing: ffmpeg таймаут на {path.name}')
        out_path.unlink(missing_ok=True)
        return False
    except Exception as e:
        logger.warning(f'video_transform finishing: {e}')
        out_path.unlink(missing_ok=True)
        return False

    if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        err = result.stderr.decode('utf-8', 'ignore')[-400:] if result.stderr else ''
        logger.warning(f'video_transform finishing: ffmpeg код {result.returncode} {path.name}: {err}')
        out_path.unlink(missing_ok=True)
        return False

    out_path.replace(path)
    return True


def _build_video_chain(t: dict) -> str:
    """Видеофильтры (без overlay) одной строкой через запятую."""
    filters: list[str] = []

    crop_pct = float(t.get('crop_percent', 0.0))
    if crop_pct > 0:
        keep = max(0.5, 1.0 - crop_pct * 2)
        filters.append(f'crop=iw*{keep:.4f}:ih*{keep:.4f}')

    rotate = float(t.get('rotate_deg', 0.0))
    if abs(rotate) > 0.001:
        rad = rotate * 3.14159265 / 180.0
        filters.append(f'rotate={rad:.5f}:fillcolor=black:bilinear=1')

    if t.get('color_shift'):
        b = float(t.get('brightness', 0.03))
        c = float(t.get('contrast', 1.04))
        s = float(t.get('saturation', 1.05))
        filters.append(f'eq=brightness={b}:contrast={c}:saturation={s}')

    if t.get('noise'):
        strength = int(t.get('noise_strength', 8))
        filters.append(f'noise=alls={strength}:allf=t')

    speed = float(t.get('speed', 1.0))
    if abs(speed - 1.0) > 0.001:
        filters.append(f'setpts={1.0 / speed:.5f}*PTS')

    # Финальное выравнивание к чётным размерам — требование libx264.
    filters.append('scale=trunc(iw/2)*2:trunc(ih/2)*2')
    return ','.join(filters)


def _build_cut_segment(t: dict, duration: float) -> str | None:
    """select-фильтр, вырезающий случайный фрагмент из середины.

    Возвращает выражение для select или None, если резать нечего.
    """
    cut_min = float(t.get('cut_seconds_min', 0))
    cut_max = float(t.get('cut_seconds_max', 0))
    if cut_max <= 0 or duration < 12:
        return None

    cut_len = random.uniform(cut_min, cut_max)
    cut_len = min(cut_len, duration * 0.25)  # не вырезать больше четверти
    # Старт фрагмента — в средней трети, чтобы не трогать начало/конец.
    start = random.uniform(duration * 0.3, duration * 0.6)
    end = start + cut_len
    # Оставляем всё, КРОМЕ [start, end].
    return f'not(between(t,{start:.2f},{end:.2f}))'


def transform_video(
    video_path: str | Path,
    transforms: dict,
    *,
    logo_path: str | Path | None = None,
    logo_position: str = 'bottom_right',
    logo_scale: float = 0.18,
    logo_margin: int = 24,
    metadata: dict | None = None,
    volume_factor: float = 1.0,
) -> bool:
    """Обработать видео ffmpeg на месте. True при успехе.

    volume_factor < 1.0 приглушает звук (1.0 = без изменения).
    """
    path = Path(video_path)
    if not path.exists():
        return False
    if not ffmpeg_available():
        logger.warning('video_transform: ffmpeg не найден в PATH — видео без обработки')
        return False

    logo = Path(logo_path) if logo_path else None
    has_logo = bool(logo and logo.exists())

    duration = _probe_duration(path)
    cut_expr = _build_cut_segment(transforms, duration)
    video_chain = _build_video_chain(transforms)

    # Цепочка для [0:v]: select (вырез) → фильтры → setpts для непрерывности.
    v_parts: list[str] = []
    if cut_expr:
        v_parts.append(f"select='{cut_expr}'")
        v_parts.append('setpts=N/FRAME_RATE/TB')
    if video_chain:
        v_parts.append(video_chain)
    v_chain = ','.join(v_parts) if v_parts else 'null'

    # Аудио: тот же вырез + темп.
    a_parts: list[str] = []
    if cut_expr:
        a_parts.append(f"aselect='{cut_expr}'")
        a_parts.append('asetpts=N/SR/TB')
    speed = float(transforms.get('speed', 1.0))
    if abs(speed - 1.0) > 0.001:
        a_parts.append(f'atempo={speed:.4f}')
    if abs(volume_factor - 1.0) > 0.001:
        a_parts.append(f'volume={volume_factor:.3f}')
    a_chain = ','.join(a_parts) if a_parts else 'anull'

    # Сборка filter_complex. Лого масштабируется относительно ширины видео
    # через scale2ref: [logo][ref] scale2ref=w=ref_w*scale.
    if has_logo:
        pos = _OVERLAY_POSITIONS.get(logo_position, _OVERLAY_POSITIONS['bottom_right']).format(m=logo_margin)
        filter_complex = (
            f'[0:v]{v_chain}[base];'
            f'[1:v][base]scale2ref=w=iw*{logo_scale:.4f}:h=ow/mdar[wm][base2];'
            f'[base2][wm]overlay={pos}[vout];'
            f'[0:a]{a_chain}[aout]'
        )
    else:
        filter_complex = f'[0:v]{v_chain}[vout];[0:a]{a_chain}[aout]'

    out_path = path.with_name(f'{path.stem}_t.mp4')
    cmd: list[str] = ['ffmpeg', '-y', '-i', str(path)]
    if has_logo:
        cmd += ['-i', str(logo)]
    cmd += [
        '-filter_complex', filter_complex,
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        '-map_metadata', '-1',
    ]
    if metadata:
        for key, value in metadata.items():
            if value:
                cmd += ['-metadata', f'{key}={value}']
    cmd += ['-movflags', '+faststart', str(out_path)]

    try:
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=_FFMPEG_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f'video_transform: ffmpeg таймаут на {path.name}')
        out_path.unlink(missing_ok=True)
        return False
    except Exception as e:
        logger.warning(f'video_transform: {e}')
        out_path.unlink(missing_ok=True)
        return False

    if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        err = result.stderr.decode('utf-8', 'ignore')[-400:] if result.stderr else ''
        logger.warning(f'video_transform: ffmpeg код {result.returncode} {path.name}: {err}')
        out_path.unlink(missing_ok=True)
        return False

    out_path.replace(path)
    return True


def transform_from_profile(video_path: str | Path, profile: dict, *,
                           title: str = '', is_clip: bool = False) -> bool:
    """Применить обработку видео согласно настройкам профиля.

    Включается, если включён antiplagiaat ИЛИ watermark-логотип. Лого берётся
    из profile['watermark']['logo_path'] (общий с фото).
    """
    ap_cfg = profile.get('antiplagiaat', {})
    wm_cfg = profile.get('watermark', {})
    vt_cfg = profile.get('video_transform', {})

    ap_on = ap_cfg.get('enabled', False)
    wm_on = (wm_cfg.get('enabled', False)
             and wm_cfg.get('mode') == 'logo'
             and bool(wm_cfg.get('logo_path')))

    if not (ap_on or wm_on):
        return False

    # Жёсткий режим (по умолчанию при включённом антиплагиате): рандомные
    # параметры на каждый прогон, чтобы два запуска давали разный результат.
    # Значение 0 в конфиге = "авто" (рандомизировать).
    hard = bool(vt_cfg.get('hard_mode', ap_on))

    def _auto(key: str, lo: float, hi: float, fallback: float) -> float:
        val = float(vt_cfg.get(key, 0.0) or 0.0)
        if val != 0.0:
            return val
        return random.uniform(lo, hi) if hard else fallback

    transforms = {
        # Кроп краёв отключён по требованию: контент не обрезаем.
        'crop_percent': 0.0,
        'color_shift': bool(vt_cfg.get('color_shift', ap_on)),
        'brightness': random.uniform(-0.04, 0.06),
        'contrast': random.uniform(1.02, 1.08),
        'saturation': random.uniform(1.02, 1.10),
        'speed': _auto('speed', 0.96, 1.05, 1.02) if ap_on else 1.0,
        'rotate_deg': _auto('rotate_deg', -1.2, 1.2, 0.0) if (ap_on and hard) else 0.0,
        'noise': bool(vt_cfg.get('noise', hard)),
        'noise_strength': int(vt_cfg.get('noise_strength', 6)),
        'cut_seconds_min': float(vt_cfg.get('cut_seconds_min', 2.0)) if ap_on else 0.0,
        'cut_seconds_max': float(vt_cfg.get('cut_seconds_max', 4.0)) if ap_on else 0.0,
        'strip_metadata': bool(vt_cfg.get('strip_metadata', True)),
    }

    metadata = None
    if vt_cfg.get('set_metadata', True):
        metadata = {
            'title': title or vt_cfg.get('meta_title', ''),
            'artist': vt_cfg.get('meta_artist', wm_cfg.get('text', '')),
            'comment': vt_cfg.get('meta_comment', ''),
        }

    logo_path = wm_cfg.get('logo_path', '') if wm_on else None

    # Звук тише оригинала (по требованию). Дефолт 0.7 = −30%.
    volume_factor = float(vt_cfg.get('volume_factor', 0.7) or 1.0)

    result = transform_video(
        video_path,
        transforms,
        logo_path=logo_path,
        logo_position=wm_cfg.get('position', 'bottom_right'),
        logo_scale=float(wm_cfg.get('logo_scale', 0.18)),
        logo_margin=int(wm_cfg.get('logo_margin', 24)),
        metadata=metadata,
        volume_factor=volume_factor,
    )

    # Финишный проход: формат кадра, рамка, фейды. В hard-режиме параметры
    # рандомятся на каждое видео; явные значения в конфиге их перебивают.
    if ap_on:
        aspect_mode = vt_cfg.get('aspect_mode') or ''
        if aspect_mode in ('', 'auto'):
            if is_clip:
                # Клипы — всегда вертикаль 9:16, blur-плашки если исходник шире
                aspect_mode = 'vertical_blur'
            else:
                # square_crop убран — он режет контент. Оставляем original или
                # blur-плашки (контент не обрезается).
                aspect_mode = random.choices(
                    ['original', 'square_blur'],
                    weights=[0.75, 0.25],
                )[0]

        # Фейды отключены по требованию (раньше срабатывали случайно).
        do_fade = False

        frame_px = int(vt_cfg.get('frame_px', 0) or 0)
        if frame_px == 0 and hard and random.random() < 0.1:
            frame_px = random.randint(6, 14)

        fin = apply_finishing(
            video_path,
            aspect_mode=aspect_mode,
            blur_strength=random.randint(15, 25),
            frame_px=frame_px,
            frame_color=random.choice(['black', 'white']),
            fade=do_fade,
            fade_duration=random.uniform(0.3, 0.5),
        )
        result = result or fin

    return result
