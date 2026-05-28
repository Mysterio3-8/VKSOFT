#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Конфигурация и состояние приложения."""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / 'frontend'
LOGS_DIR = BASE_DIR / 'logs'
STORAGE_DIR = BASE_DIR / 'storage'
CONFIG_FILE = BASE_DIR / 'config.json'

for _d in [LOGS_DIR, STORAGE_DIR]:
    _d.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / 'bot.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


class AppState:
    """Состояние приложения."""

    def __init__(self):
        self.config = self._load_config()
        self.is_downloading = False
        self.is_publishing = False
        self.is_monitoring = False
        self.is_downloading_photos = False
        self.is_publishing_photos  = False
        self.is_downloading_videos = False
        self.is_publishing_videos  = False
        self.is_downloading_clips  = False
        self.is_publishing_clips   = False
        self._monitor_thread: Optional[threading.Thread] = None
        self.monitor_last_check: Optional[str] = None
        self.monitor_next_check: Optional[str] = None
        self.monitor_log: List[Dict] = []
        self.download_progress: Dict = {'current': 0, 'total': 0, 'source': ''}
        self.logs: List[Dict] = []
        self._lock = threading.Lock()

    # ── profile helpers ──────────────────────────────────────

    @property
    def active_profile_id(self) -> str:
        return self.config.get('active_profile', 'p1')

    @active_profile_id.setter
    def active_profile_id(self, pid: str):
        self.config['active_profile'] = pid

    @property
    def profile(self) -> Dict:
        """Return active profile config dict."""
        return self.config['profiles'].get(self.active_profile_id, {})

    @property
    def posts_dir(self) -> Path:
        p = STORAGE_DIR / self.active_profile_id / 'downloaded_posts'
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def photos_dir(self) -> Path:
        p = STORAGE_DIR / self.active_profile_id / 'photos'
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def stats_file(self) -> Path:
        return STORAGE_DIR / self.active_profile_id / 'statistics.json'

    @property
    def last_scheduled_file(self) -> Path:
        return STORAGE_DIR / self.active_profile_id / 'last_scheduled.txt'

    @property
    def offsets_file(self) -> Path:
        return STORAGE_DIR / self.active_profile_id / 'download_offsets.json'

    @property
    def monitor_last_seen_file(self) -> Path:
        """Хранит { community_id: last_seen_ts } для мониторинга."""
        return STORAGE_DIR / self.active_profile_id / 'monitor_last_seen.json'

    @property
    def monitor_published_file(self) -> Path:
        """Хранит список ID уже опубликованных через мониторинг постов."""
        return STORAGE_DIR / self.active_profile_id / 'monitor_published.json'

    @property
    def daily_log_file(self) -> Path:
        return STORAGE_DIR / self.active_profile_id / 'daily_log.json'

    @property
    def photos_queue_dir(self) -> Path:
        p = STORAGE_DIR / self.active_profile_id / 'downloaded_photos'
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def photo_files_dir(self) -> Path:
        p = STORAGE_DIR / self.active_profile_id / 'photo_files'
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def videos_queue_dir(self) -> Path:
        p = STORAGE_DIR / self.active_profile_id / 'downloaded_videos'
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def video_files_dir(self) -> Path:
        p = STORAGE_DIR / self.active_profile_id / 'video_files'
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def clips_queue_dir(self) -> Path:
        p = STORAGE_DIR / self.active_profile_id / 'downloaded_clips'
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def clip_files_dir(self) -> Path:
        p = STORAGE_DIR / self.active_profile_id / 'clip_files'
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ── config ───────────────────────────────────────────────

    @staticmethod
    def default_profile(pid: str = 'p1', name: str = 'Мой канал') -> Dict:
        return {
            'id': pid,
            'name': name,
            'color': '#7c3aed',
            'vk': {
                'user_token': '',
                'group_token': '',
                'group_id': '',
                'api_version': '5.131',
            },
            'sources': [],
            'download_settings': {
                'posts_to_download': 100,
                'delay_min': 2,
                'delay_max': 5,
                'check_duplicates': True,
            },
            'publishing_settings': {
                'posts_to_publish': 50,
                'publish_delay_min': 7200,
                'publish_delay_max': 10800,
                'postponed_enabled': True,
                'publish_hours_enabled': True,
                'publish_hours_start': 8,
                'publish_hours_end': 22,
            },
            'processing': {
                'add_hashtags': False,
                'hashtags': [],
                'photo_only': False,
                'allow_video': False,
            },
            'ollama': {
                'enabled': False,
                'url': 'http://localhost:11434',
                'model': 'llama3.2:3b',
                'target_words_min': 50,
                'target_words_max': 80,
            },
            'filters': {
                'enable_auto_filters': False,
                'block_keywords': [],
                'block_hashtags': [],
                'min_content_length': 0,
            },
            'monitoring': {
                'enabled': False,
                'check_interval_min': 180,
                'catch_up_days': 3,
                'max_per_cycle': 2,
                'sources': [],
                'min_views': 0,
                'ocr_filter': False,
                'google_image': False,
                'google_api_key': '',
                'google_cx': '',
            },
            'antiplagiaat': {
                'enabled': True,
                'clear_text': True,
                'max_photos': 4,
                'remove_photo': 'random',
            },
            'engagement': {
                'enabled': False,
                'min_ratio': 0.5,   # % лайков от просмотров
                'min_likes': 0,
            },
            'peak_hours': {
                'enabled': True,
                'hours': [8, 10, 13, 17, 19, 21],
            },
            'cross_post': {
                'enabled': False,
                'profile_ids': [],
            },
            'recycle': {
                'enabled': False,
                'min_days': 30,
                'min_likes': 50,
                'max_per_run': 5,
            },
            'phash': {
                'enabled': True,
                'threshold': 10,
            },
            'tracking': {
                'enabled': True,
                'alert_low_views': False,
            },
            'photos_settings': {
                'enabled': False,
                'photos_per_run': 50,
                'publish_delay_min': 7200,
                'publish_delay_max': 10800,
                'delay_min': 3,
                'delay_max': 6,
                'album_title': 'Фото',
                'create_wall_post': True,
            },
            'videos_settings': {
                'enabled': False,
                'videos_per_run': 10,
                'publish_delay_min': 10800,
                'publish_delay_max': 21600,
                'delay_min': 3,
                'delay_max': 6,
                'quality': '720',
                'create_wall_post': True,
                'max_filesize_mb': 500,
            },
            'clips_settings': {
                'enabled': False,
                'clips_per_run': 10,
                'publish_delay_min': 10800,
                'publish_delay_max': 21600,
                'delay_min': 3,
                'delay_max': 5,
                'max_duration_sec': 180,
                'quality': '720',
                'create_wall_post': True,
            },
            'stories': {
                'interval_hours': 6,
            },
            'polls': {
                'enabled': False,
                'frequency': 5,
                'is_anonymous': True,
                'multiple': False,
                'questions': [
                    {
                        'question': 'Где бы вы хотели оказаться прямо сейчас?',
                        'answers': ['В горах', 'У моря', 'В лесу', 'В городе'],
                    },
                    {
                        'question': 'Какое время суток лучше для прогулки?',
                        'answers': ['Утро', 'День', 'Вечер', 'Ночь'],
                    },
                    {
                        'question': 'Что важнее в путешествии?',
                        'answers': ['Природа', 'Архитектура', 'Еда', 'Новые люди'],
                    },
                ],
            },
        }

    @staticmethod
    def default_config() -> Dict:
        p = AppState.default_profile()
        return {'active_profile': 'p1', 'profiles': {'p1': p}}

    def _deep_merge(self, base: Dict, updates: Dict) -> Dict:
        result = base.copy()
        for k, v in updates.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    def _migrate_old_config(self, old: Dict) -> Dict:
        """Convert flat (pre-profile) config.json to new schema."""
        pid = 'p1'
        prof = self._deep_merge(self.default_profile(pid), old)
        prof['id'] = pid
        prof['name'] = old.get('name', 'Мой канал')
        prof['color'] = old.get('color', '#7c3aed')
        for k in ('active_profile', 'profiles'):
            prof.pop(k, None)
        return {'active_profile': pid, 'profiles': {pid: prof}}

    def _load_config(self) -> Dict:
        default = self.default_config()
        if not CONFIG_FILE.exists():
            return default
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            if 'profiles' not in raw:
                raw = self._migrate_old_config(raw)
            return self._deep_merge(default, raw)
        except Exception as e:
            logger.error(f'Config load error: {e}')
            return default

    def save_config(self) -> bool:
        try:
            CONFIG_FILE.write_text(
                json.dumps(self.config, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            return True
        except Exception as e:
            logger.error(f'Config save error: {e}')
            return False

    # ── stats ─────────────────────────────────────────────────

    def load_stats(self) -> Dict:
        try:
            if self.stats_file.exists():
                return json.loads(self.stats_file.read_text())
        except Exception:
            pass
        return {'published': 0, 'failed': 0}

    def save_stats(self, stats: Dict):
        try:
            self.stats_file.write_text(json.dumps(stats))
        except Exception as e:
            logger.error(f'Stats save error: {e}')

    # ── daily log ─────────────────────────────────────────────

    def load_daily_log(self) -> Dict:
        try:
            if self.daily_log_file.exists():
                return json.loads(self.daily_log_file.read_text(encoding='utf-8'))
        except Exception:
            pass
        return {}

    def bump_daily_stat(self, key: str, amount: int = 1):
        """Увеличить счётчик сегодняшнего дня."""
        today = datetime.now().strftime('%Y-%m-%d')
        try:
            log = self.load_daily_log()
            if today not in log:
                log[today] = {'published': 0, 'errors': 0}
            log[today][key] = log[today].get(key, 0) + amount
            if len(log) > 60:
                for old in sorted(log.keys())[:-60]:
                    del log[old]
            self.daily_log_file.parent.mkdir(parents=True, exist_ok=True)
            self.daily_log_file.write_text(json.dumps(log), encoding='utf-8')
        except Exception as e:
            logger.warning(f'bump_daily_stat: {e}')

    # ── logs ──────────────────────────────────────────────────

    def add_log(self, message: str, level: str = 'info'):
        ts = datetime.now().strftime('%H:%M:%S')
        with self._lock:
            self.logs.insert(0, {'timestamp': ts, 'message': message, 'level': level})
            if len(self.logs) > 300:
                self.logs.pop()
        safe_level = level if level in ('debug', 'info', 'warning', 'error') else 'info'
        getattr(logger, safe_level, logger.info)(message)
        if level in ('error', 'critical'):
            self.bump_daily_stat('errors')

    def add_monitor_log(self, message: str, level: str = 'info'):
        """Лог мониторинга."""
        ts = datetime.now().strftime('%H:%M:%S')
        entry = {'timestamp': ts, 'message': message, 'level': level}
        with self._lock:
            self.monitor_log.insert(0, entry)
            if len(self.monitor_log) > 200:
                self.monitor_log.pop()
        self.add_log(f'[Мониторинг] {message}', level)


app_state = AppState()
