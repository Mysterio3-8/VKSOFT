# -*- coding: utf-8 -*-
"""Clip assembler v1 (по growth-отчёту).

Две задачи:
1. Hook-текст поверх клипа (drawtext): 3-8 слов крупно в верхней трети,
   опционально CTA-оверлей в последние 1.5 сек у ~25% клипов.
2. Slideshow-клип из фото: 9:16 1080×1920, zoompan 10-14 сек, фейды,
   опциональная музыка из локальной папки.

Спецификация из отчёта: H.264+AAC, 25 fps, hard cut, текст вне крайних
зон интерфейса, intro не используется.
"""

import json
import random
import subprocess
import time
import uuid
from pathlib import Path

from config import STORAGE_DIR, app_state, logger
from services.video_transform import _probe_dims, _probe_duration, ffmpeg_available

_FFMPEG_TIMEOUT_SEC = 1200

# Семейства hook-оверлеев: curiosity / escape / scale / rating / manifest.
# manifest — мини-манифест роста («собрать миллион ради планеты»): прямой
# призыв к лайку/подписке как рычагу охвата клипов.
# Ограничение длины — overlay ≤ 42 символов, 3-8 слов.
OVERLAY_FAMILIES = {
    'curiosity': [
        'Это место реально существует',
        'Хочется исчезнуть сюда',
        'Один кадр — и хочется уехать',
        'Такие места не показывают в новостях',
        'Кажется, это другая планета',
    ],
    'escape': [
        'Город подождёт',
        'Здесь бы выдохнуть',
        'Тишина выглядит так',
        'Побег от всего — сюда',
        'Здесь забываешь про дедлайны',
    ],
    'scale': [
        'Планета умеет удивлять',
        'Мир больше, чем дедлайны',
        'Красота без комментариев',
        'Земля всё ещё удивляет',
        'Дыхание мира 🌍',
    ],
    'rating': [
        'Сколько из 10?',
        'Десятка или нет?',
        'Оцените этот вид',
        'Ваша оценка этому месту?',
        'От 1 до 10 — сколько?',
    ],
    'manifest': [
        'Соберём миллион ради планеты',
        'Докажем, что нас много',
        'Один лайк — видео улетит дальше',
        'Подпишись, если планета важна',
        'Нас должно стать миллион',
    ],
}

CTA_OVERLAYS = [
    'Сохрани себе',
    'Отправь тому, кто устал',
    'Подпишись на такие места',
    'Подпишись — дальше красивее',
    'Сохрани, чтобы не потерять',
]

CTA_OVERLAY_CHANCE = 0.25   # отчёт: CTA-оверлей у 20-30% клипов
HOOK_MAX_LINE_CHARS = 18    # перенос на 2 строки, чтобы текст был крупным

_FONT_CANDIDATES = [
    'C:/Windows/Fonts/arialbd.ttf',
    'C:/Windows/Fonts/calibrib.ttf',
    'C:/Windows/Fonts/segoeuib.ttf',
    'C:/Windows/Fonts/arial.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
]


OVERLAY_UCB_MIN_TRIALS = 12  # бандит по оверлеям включается после 12 клипов
OVERLAY_UCB_EPSILON = 0.25


def pick_overlay() -> tuple[str, str]:
    """Семейство hook-оверлея: UCB по статистике трекера, до данных — random."""
    family = ''
    if random.random() > OVERLAY_UCB_EPSILON:
        try:
            from services.bandit import stats_to_arms, ucb_choose
            from services.tracker import get_overlay_stats
            arms = stats_to_arms(get_overlay_stats(), names=list(OVERLAY_FAMILIES))
            if sum(a['trials'] for a in arms) >= OVERLAY_UCB_MIN_TRIALS:
                family = ucb_choose(arms) or ''
        except Exception:
            family = ''
    if family not in OVERLAY_FAMILIES:
        family = random.choice(list(OVERLAY_FAMILIES))
    return family, random.choice(OVERLAY_FAMILIES[family])


def find_font(profile: dict | None = None) -> str | None:
    cfg_font = ((profile or {}).get('clips_settings') or {}).get('overlay_font', '')
    candidates = ([cfg_font] if cfg_font else []) + _FONT_CANDIDATES
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def wrap_hook(text: str, max_chars: int = HOOK_MAX_LINE_CHARS) -> str:
    """Перенести hook на 2 строки около середины, если он длинный."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    words = text.split()
    best, best_diff = text, len(text)
    for i in range(1, len(words)):
        first = ' '.join(words[:i])
        second = ' '.join(words[i:])
        diff = abs(len(first) - len(second))
        if diff < best_diff:
            best, best_diff = f'{first}\n{second}', diff
    return best


def drawtext_escape(text: str) -> str:
    """Экранировать текст для drawtext внутри кавычек фильтра."""
    return (
        text.replace('\\', '\\\\')
        .replace("'", '’')   # одинарная кавычка внутри '...' нерешаема — типографская
        .replace(':', '\\:')
        .replace('%', '\\%')
    )


def _font_for_filter(font_path: str) -> str:
    # Windows-путь в фильтре: прямые слэши, двоеточие диска экранируется
    return font_path.replace('\\', '/').replace(':', '\\:')


def add_text_overlay(
    video_path: str | Path,
    hook_text: str,
    cta_text: str = '',
    font_path: str | None = None,
) -> bool:
    """Нанести hook (и опционально CTA в конце) на видео. Обрабатывает на месте."""
    path = Path(video_path)
    if not path.exists() or not ffmpeg_available():
        return False
    font = font_path or find_font()
    if not font:
        logger.warning('clip_assembler: шрифт для drawtext не найден')
        return False

    w, h = _probe_dims(path)
    duration = _probe_duration(path)
    if w <= 0 or h <= 0:
        return False

    font_f = _font_for_filter(font)
    hook = drawtext_escape(wrap_hook(hook_text))
    # Hook: верхняя треть (safe zone), крупный, белый с чёрной обводкой
    hook_size = max(36, int(w * 0.072))
    filters = [
        f"drawtext=fontfile='{font_f}':text='{hook}'"
        f":fontsize={hook_size}:fontcolor=white:borderw={max(3, hook_size // 14)}"
        f":bordercolor=black@0.85:line_spacing=12"
        f":x=(w-text_w)/2:y=h*0.16"
    ]
    if cta_text and duration > 4:
        cta = drawtext_escape(cta_text)
        cta_size = max(28, int(w * 0.05))
        cta_start = max(0.0, duration - 1.5)
        filters.append(
            f"drawtext=fontfile='{font_f}':text='{cta}'"
            f":fontsize={cta_size}:fontcolor=white:borderw={max(2, cta_size // 14)}"
            f":bordercolor=black@0.85"
            f":x=(w-text_w)/2:y=h*0.78:enable='gte(t,{cta_start:.2f})'"
        )

    out_path = path.with_name(f'{path.stem}_o.mp4')
    cmd = [
        'ffmpeg', '-y', '-i', str(path),
        '-vf', ','.join(filters),
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-map', '0:v', '-map', '0:a?', '-c:a', 'copy',
        '-movflags', '+faststart', str(out_path),
    ]
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=_FFMPEG_TIMEOUT_SEC,
        )
    except Exception as e:
        logger.warning(f'clip_assembler overlay: {e}')
        out_path.unlink(missing_ok=True)
        return False

    if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        err = result.stderr.decode('utf-8', 'ignore')[-400:] if result.stderr else ''
        logger.warning(f'clip_assembler overlay: ffmpeg код {result.returncode}: {err}')
        out_path.unlink(missing_ok=True)
        return False

    out_path.replace(path)
    return True


def apply_overlay_from_profile(video_path: str | Path, profile: dict) -> str:
    """Hook-оверлей по настройкам профиля. Возвращает семейство или ''."""
    cfg = profile.get('clips_settings', {})
    if not cfg.get('overlay_enabled', False):
        return ''
    font = find_font(profile)
    if not font:
        return ''
    family, hook = pick_overlay()
    cta = random.choice(CTA_OVERLAYS) if random.random() < CTA_OVERLAY_CHANCE else ''
    ok = add_text_overlay(video_path, hook, cta, font_path=font)
    return family if ok else ''


# ── Slideshow из фото ─────────────────────────────────────────────


_AUDIO_EXTS = ('.mp3', '.m4a', '.aac', '.wav', '.ogg')
_VIDEO_EXTS = ('.mp4', '.mov', '.mkv', '.webm')


def _has_audio(path: Path) -> bool:
    import shutil as _shutil
    if not _shutil.which('ffprobe'):
        return False
    try:
        out = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30,
        )
        return 'audio' in out.stdout.decode('utf-8', 'ignore')
    except Exception:
        return False


def pick_from_dirs(dirs: list, exts: tuple) -> list[Path]:
    """Все файлы с нужными расширениями из существующих папок."""
    files: list[Path] = []
    for d in dirs:
        d = Path(d)
        if d.is_dir():
            files.extend(p for p in d.iterdir() if p.suffix.lower() in exts)
    return files


def pick_music(profile: dict | None = None) -> Path | None:
    """Источник звука для slideshow.

    Приоритет: треки из clips_settings.music_dir / storage/music. Если их нет —
    аудиодорожка случайного скачанного клипа/видео (тот же источник, что и сами
    репосты, поэтому отдельные треки необязательны).
    """
    cfg_dir = ((profile or {}).get('clips_settings') or {}).get('music_dir', '')
    music_dirs = ([Path(cfg_dir)] if cfg_dir else []) + [STORAGE_DIR / 'music']
    tracks = pick_from_dirs(music_dirs, _AUDIO_EXTS)
    if tracks:
        return random.choice(tracks)

    donors = pick_from_dirs(
        [app_state.clip_files_dir, app_state.video_files_dir], _VIDEO_EXTS
    )
    random.shuffle(donors)
    for donor in donors[:10]:
        if _has_audio(donor):
            return donor
    return None


def make_slideshow_clip(
    photo_paths: list,
    out_path: str | Path,
    duration: float = 12.0,
    music_path: str | Path | None = None,
) -> bool:
    """Собрать 9:16 клип 1080×1920 из 1-3 фото с zoompan и фейдами."""
    photos = [Path(p) for p in photo_paths if p and Path(p).exists()][:3]
    if not photos or not ffmpeg_available():
        return False
    out = Path(out_path)
    duration = max(6.0, min(float(duration), 25.0))

    fps = 25
    seg = duration / len(photos)
    frames = max(1, int(seg * fps))

    cmd: list[str] = ['ffmpeg', '-y']
    for photo in photos:
        cmd += ['-i', str(photo)]

    music = Path(music_path) if music_path else None
    has_music = bool(music and music.exists())
    if has_music:
        cmd += ['-i', str(music)]

    parts = []
    for i in range(len(photos)):
        # Кадр заполняет 9:16 (центр-кроп), затем медленный zoom-in.
        # Большой промежуточный scale убирает дрожание zoompan.
        parts.append(
            f'[{i}:v]scale=2700:4800:force_original_aspect_ratio=increase,'
            f'crop=2700:4800,'
            f"zoompan=z='min(zoom+{0.10 / frames:.6f},1.12)'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f':d={frames}:s=1080x1920:fps={fps},setsar=1[v{i}]'
        )
    concat_in = ''.join(f'[v{i}]' for i in range(len(photos)))
    fade_out_start = duration - 0.6
    parts.append(
        f'{concat_in}concat=n={len(photos)}:v=1:a=0,'
        f'fade=t=in:st=0:d=0.4,fade=t=out:st={fade_out_start:.2f}:d=0.6,'
        f'format=yuv420p[vout]'
    )
    if has_music:
        a_idx = len(photos)
        parts.append(
            f'[{a_idx}:a]atrim=0:{duration:.2f},'
            f'afade=t=in:st=0:d=0.5,afade=t=out:st={max(0.0, duration - 1.0):.2f}:d=1.0[aout]'
        )

    cmd += ['-filter_complex', ';'.join(parts), '-map', '[vout]']
    if has_music:
        cmd += ['-map', '[aout]', '-c:a', 'aac', '-b:a', '160k']
    else:
        cmd += ['-an']
    cmd += [
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
        '-t', f'{duration:.2f}', '-movflags', '+faststart', str(out),
    ]

    try:
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=_FFMPEG_TIMEOUT_SEC,
        )
    except Exception as e:
        logger.warning(f'clip_assembler slideshow: {e}')
        out.unlink(missing_ok=True)
        return False

    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        err = result.stderr.decode('utf-8', 'ignore')[-400:] if result.stderr else ''
        logger.warning(f'clip_assembler slideshow: ffmpeg код {result.returncode}: {err}')
        out.unlink(missing_ok=True)
        return False
    return True


def assemble_slideshow_from_photo_queue(photo_count: int = 3, duration: float = 12.0) -> dict:
    """Собрать slideshow-клип из очереди фото и положить в очередь клипов.

    Использованные фото убираются из фото-очереди (они уходят как клип).
    """
    queue = sorted(app_state.photos_queue_dir.glob('*.json'))
    picked: list[tuple[Path, dict]] = []
    for meta_file in queue:
        if len(picked) >= max(1, photo_count):
            break
        try:
            meta = json.loads(meta_file.read_text(encoding='utf-8'))
        except Exception:
            continue
        photo = Path(meta.get('_local_file', ''))
        if photo.exists():
            picked.append((meta_file, meta))

    if not picked:
        return {'status': 'error', 'message': 'В очереди фото нет файлов для slideshow'}

    photos = [Path(meta['_local_file']) for _, meta in picked]
    clip_name = f'slideshow_{int(time.time())}_{uuid.uuid4().hex[:6]}'
    out_path = app_state.clip_files_dir / f'{clip_name}.mp4'

    if not make_slideshow_clip(photos, out_path, duration, music_path=pick_music(app_state.profile)):
        return {'status': 'error', 'message': 'ffmpeg не собрал slideshow (см. логи)'}

    # Hook-оверлей сразу при сборке — дальше клип идёт обычным конвейером
    family = apply_overlay_from_profile(out_path, app_state.profile)

    clip_meta = {
        '_local_file': str(out_path),
        'title': 'Дыхание Мира',
        'description': '',
        'media_kind': 'slideshow_clip',
        'overlay_family': family,
        'source_cid': str(picked[0][1].get('owner_id', '')),
    }
    meta_path = app_state.clips_queue_dir / f'{clip_name}.json'
    meta_path.write_text(json.dumps(clip_meta, ensure_ascii=False, indent=2), encoding='utf-8')

    # Фото ушли в клип — убираем их из фото-очереди
    for meta_file, meta in picked:
        Path(meta.get('_local_file', '')).unlink(missing_ok=True)
        meta_file.unlink(missing_ok=True)

    app_state.add_log(
        f'Slideshow-клип собран из {len(photos)} фото → {out_path.name}'
        + (f' (hook: {family})' if family else ''),
        'info',
    )
    return {
        'status': 'ok',
        'clip': str(out_path),
        'photos_used': len(photos),
        'overlay_family': family,
    }
