# -*- coding: utf-8 -*-
"""Структурированный журнал публикаций.

Каждая попытка публикации (успех/ошибка/дубликат) пишется одной строкой
JSON в storage/{profile_id}/publish_log.jsonl. Файлы старше суток
сжимаются в publish_log-YYYY-MM-DD.jsonl.gz, чтобы не разрастаться.
"""

import gzip
import json
import time
from datetime import datetime
from typing import Optional

from config import app_state, logger


def log_publish_event(
    media_type: str,
    status: str,
    post_id: Optional[int] = None,
    publish_date: Optional[int] = None,
    source_id: str = '',
    extra: Optional[dict] = None,
) -> None:
    """Записать одно событие публикации.

    status: 'success' | 'failed' | 'duplicate' | 'skipped'
    """
    entry = {
        'ts': int(time.time()),
        'media_type': media_type,
        'status': status,
        'post_id': post_id,
        'publish_date': publish_date,
        'source_id': source_id,
        'extra': extra or {},
    }
    log_file = app_state.publish_log_file
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.warning(f'log_publish_event: {e}')


def read_recent_events(limit: int = 50) -> list[dict]:
    """Последние N событий, новейшие первыми."""
    log_file = app_state.publish_log_file
    if not log_file.exists():
        return []
    try:
        lines = log_file.read_text(encoding='utf-8').strip().splitlines()
        events = [json.loads(line) for line in lines if line.strip()]
        return list(reversed(events))[:limit]
    except Exception as e:
        logger.warning(f'read_recent_events: {e}')
        return []


def rotate_old_logs() -> None:
    """Сжать publish_log.jsonl в .gz, если файл не менялся >24ч.

    Вызывается из media_loop_worker раз в проход — не критично к точному
    расписанию, главное чтобы файл не рос бесконечно.
    """
    log_file = app_state.publish_log_file
    if not log_file.exists():
        return
    age_sec = time.time() - log_file.stat().st_mtime
    if age_sec < 86400:
        return
    mtime_date = datetime.fromtimestamp(log_file.stat().st_mtime).strftime('%Y-%m-%d')
    gz_path = log_file.with_name(f'{log_file.stem}-{mtime_date}.jsonl.gz')
    try:
        with open(log_file, 'rb') as src, gzip.open(gz_path, 'wb') as dst:
            dst.write(src.read())
        log_file.unlink()
    except Exception as e:
        logger.warning(f'rotate_old_logs: {e}')
