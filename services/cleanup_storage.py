# -*- coding: utf-8 -*-
"""Safe cleanup helpers for downloaded queue files."""

import shutil
import time
from pathlib import Path
from typing import Dict, Iterable

from config import STORAGE_DIR, app_state


def is_storage_busy() -> bool:
    return (
        app_state.is_downloading or app_state.is_publishing
        or app_state.is_monitoring
        or app_state.is_downloading_photos or app_state.is_publishing_photos
        or app_state.is_downloading_videos or app_state.is_publishing_videos
        or app_state.is_downloading_clips or app_state.is_publishing_clips
    )


def _safe_base() -> Path:
    return (STORAGE_DIR / app_state.active_profile_id).resolve()


def _inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base)
        return True
    except Exception:
        return False


def _safe_unlink(path: Path, base: Path) -> bool:
    if not _inside(path, base) or not path.is_file():
        return False
    path.unlink(missing_ok=True)
    return True


def _safe_rmtree(path: Path, base: Path) -> int:
    if not _inside(path, base) or not path.is_dir():
        return 0
    files = sum(1 for p in path.rglob('*') if p.is_file())
    shutil.rmtree(path, ignore_errors=True)
    return files


def _size_mb(paths: Iterable[Path]) -> float:
    total = 0
    for path in paths:
        try:
            if path.is_file():
                total += path.stat().st_size
            elif path.is_dir():
                total += sum(p.stat().st_size for p in path.rglob('*') if p.is_file())
        except Exception:
            pass
    return round(total / (1024 * 1024), 2)


def _queue_stems() -> set:
    return {p.stem for p in app_state.posts_dir.glob('*.json')}


def _post_dirs() -> list:
    if not app_state.photos_dir.exists():
        return []
    return [p for p in app_state.photos_dir.iterdir() if p.is_dir()]


def storage_status() -> Dict:
    base = _safe_base()
    posts = list(app_state.posts_dir.glob('*.json'))
    post_dirs = _post_dirs()
    stems = {p.stem for p in posts}
    orphan_dirs = [d for d in post_dirs if d.name not in stems]

    media_dirs = [
        app_state.photos_queue_dir,
        app_state.photo_files_dir,
        app_state.videos_queue_dir,
        app_state.video_files_dir,
        app_state.clips_queue_dir,
        app_state.clip_files_dir,
    ]
    media_files = []
    for d in media_dirs:
        if d.exists():
            media_files.extend([p for p in d.rglob('*') if p.is_file()])

    temp_files = [p for p in base.rglob('*') if p.is_file() and p.suffix.lower() in ('.part', '.tmp')]

    return {
        'status': 'ok',
        'profile': app_state.active_profile_id,
        'downloaded_posts': len(posts),
        'photo_dirs': len(post_dirs),
        'orphan_photo_dirs': len(orphan_dirs),
        'media_files': len(media_files),
        'temp_files': len(temp_files),
        'storage_mb': _size_mb([base]) if base.exists() else 0,
        'posts_mb': _size_mb(posts + post_dirs),
        'media_mb': _size_mb(media_dirs),
        'temp_mb': _size_mb(temp_files),
    }


def cleanup_post_artifacts(post_file: Path, post_data: Dict = None) -> Dict:
    """Delete one published post JSON and its downloaded photo files."""
    base = _safe_base()
    post_file = Path(post_file)
    post_data = post_data or {}
    deleted_json = 0
    deleted_files = 0
    deleted_dirs = 0

    photo_dirs = set()
    for raw_path in post_data.get('_local_photos', []) or []:
        p = Path(raw_path)
        if p.is_file() and _inside(p, base):
            if _safe_unlink(p, base):
                deleted_files += 1
            parent = p.parent
            if _inside(parent, base):
                photo_dirs.add(parent)

    stem_dir = app_state.photos_dir / post_file.stem
    if stem_dir.exists():
        photo_dirs.add(stem_dir)

    for d in sorted(photo_dirs, key=lambda p: len(p.parts), reverse=True):
        if d.exists():
            count = _safe_rmtree(d, base)
            if count:
                deleted_files += count
                deleted_dirs += 1

    if post_file.exists() and _safe_unlink(post_file, base):
        deleted_json = 1

    return {
        'deleted_json': deleted_json,
        'deleted_files': deleted_files,
        'deleted_dirs': deleted_dirs,
    }


def cleanup_downloaded_posts(older_than_days: int = 0) -> Dict:
    """Delete downloaded post JSON files and matching photo directories."""
    base = _safe_base()
    cutoff = time.time() - max(0, int(older_than_days)) * 86400
    posts = list(app_state.posts_dir.glob('*.json'))
    deleted_posts = 0
    deleted_photos = 0
    deleted_dirs = 0

    for post_file in posts:
        try:
            if older_than_days > 0 and post_file.stat().st_mtime > cutoff:
                continue
            stem = post_file.stem
            if _safe_unlink(post_file, base):
                deleted_posts += 1
            photo_dir = app_state.photos_dir / stem
            count = _safe_rmtree(photo_dir, base)
            if count:
                deleted_photos += count
                deleted_dirs += 1
        except Exception as e:
            app_state.add_log(f'Очистка поста {post_file.name}: {e}', 'warning')

    return {
        'deleted_posts': deleted_posts,
        'deleted_photo_dirs': deleted_dirs,
        'deleted_photos': deleted_photos,
    }


def cleanup_junk() -> Dict:
    """Delete orphaned post photo directories and temporary partial files."""
    base = _safe_base()
    stems = _queue_stems()
    orphan_dirs = [d for d in _post_dirs() if d.name not in stems]
    deleted_orphan_dirs = 0
    deleted_orphan_files = 0
    for d in orphan_dirs:
        count = _safe_rmtree(d, base)
        if count:
            deleted_orphan_dirs += 1
            deleted_orphan_files += count

    temp_files = [p for p in base.rglob('*') if p.is_file() and p.suffix.lower() in ('.part', '.tmp')]
    deleted_temp = 0
    for f in temp_files:
        try:
            if _safe_unlink(f, base):
                deleted_temp += 1
        except Exception as e:
            app_state.add_log(f'Очистка временного файла {f.name}: {e}', 'warning')

    return {
        'deleted_orphan_dirs': deleted_orphan_dirs,
        'deleted_orphan_files': deleted_orphan_files,
        'deleted_temp_files': deleted_temp,
    }


def cleanup_media_queues() -> Dict:
    """Delete downloaded photo/video/clip queues for the active profile."""
    base = _safe_base()
    dirs = [
        app_state.photos_queue_dir,
        app_state.photo_files_dir,
        app_state.videos_queue_dir,
        app_state.video_files_dir,
        app_state.clips_queue_dir,
        app_state.clip_files_dir,
    ]
    deleted_files = 0
    for d in dirs:
        if not d.exists() or not _inside(d, base):
            continue
        for path in list(d.rglob('*')):
            if path.is_file() and _safe_unlink(path, base):
                deleted_files += 1
        for path in sorted([p for p in d.rglob('*') if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
            try:
                if _inside(path, base):
                    path.rmdir()
            except OSError:
                pass
    return {'deleted_media_files': deleted_files}


def background_cleanup_once() -> Dict:
    """Automatic cleanup that never deletes pending post queues."""
    cfg = app_state.profile.get('storage_cleanup', {})
    if not cfg.get('background_enabled', True):
        return {'skipped': 'disabled'}
    if is_storage_busy():
        return {'skipped': 'busy'}

    result = {}
    if cfg.get('auto_clean_orphans', True) or cfg.get('auto_clean_temp', True):
        junk = cleanup_junk()
        result.update(junk)
    return result


def cleanup_loop():
    """Background storage cleanup. Runs only when the bot is idle."""
    while True:
        try:
            cfg = app_state.profile.get('storage_cleanup', {})
            interval_hours = max(1, int(cfg.get('background_interval_hours', 12) or 12))
            time.sleep(interval_hours * 3600)
            result = background_cleanup_once()
            if result.get('skipped'):
                continue
            removed = sum(int(v or 0) for v in result.values())
            if removed:
                app_state.add_log(f'Фоновая автоочистка: удалено {removed} остаточных файлов/папок', 'info')
        except Exception as e:
            app_state.add_log(f'Фоновая автоочистка: {e}', 'warning')
            time.sleep(3600)
