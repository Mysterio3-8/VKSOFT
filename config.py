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


SENSITIVE_CONFIG_KEYS = {
    'user_token',
    'group_token',
    'access_token',
    'token',
    'api_key',
    'google_api_key',
    'google_cx',
}

MOJIBAKE_MARKERS = ('Р', 'С', 'Ð', 'Ñ', 'вЂ', 'В«', 'В»', 'рџ')


class AppState:
    """Состояние приложения."""

    def __init__(self):
        self.config = self._load_config()
        self.is_downloading = False
        self.is_publishing = False
        self.is_monitoring = False
        self.is_autopilot = False
        self.is_niche_scanning = False
        self.niche_progress: Dict = {'current': 0, 'total': 0, 'keyword': ''}
        self.niche_results: List[Dict] = []
        self.is_downloading_photos = False
        self.is_publishing_photos  = False
        self.is_downloading_videos = False
        self.is_publishing_videos  = False
        self.is_downloading_clips  = False
        self.is_publishing_clips   = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._autopilot_thread: Optional[threading.Thread] = None
        self.autopilot_last_report: Dict = {}
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
        profiles = self.config.setdefault('profiles', {})
        if self.active_profile_id not in profiles:
            if profiles:
                self.active_profile_id = next(iter(profiles))
            else:
                profiles['p1'] = self.default_profile()
                self.active_profile_id = 'p1'
        return profiles.get(self.active_profile_id, {})

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
                'check_duplicates': False,
            },
            'publishing_settings': {
                'posts_to_publish': 50,
                'publish_delay_min': 7200,
                'publish_delay_max': 10800,
                'postponed_enabled': True,
                'publish_hours_enabled': True,
                'publish_hours_start': 8,
                'publish_hours_end': 22,
                'timezone': 'Europe/Moscow',
                'max_posts_per_day': 4,
                'smart_schedule_enabled': True,
            },
            'processing': {
                'add_hashtags': True,
                'hashtags': [],
                'photo_only': False,
                'allow_video': True,
            },
            'watermark': {
                'enabled': False,   # включить после настройки текста/лого в настройках
                'mode': 'text',
                'text': '@channel',
                'logo_path': '',
                'position': 'bottom_right',
                'font_size': 0,
                'opacity': 230,
                'color': [255, 255, 255],
                'logo_scale': 0.12,
            },
            'filters': {
                'enable_auto_filters': True,
                'ad_stopper_enabled': True,
                'ad_stop_keywords': [
                    'реклама', '#реклама', 'на правах рекламы', 'erid',
                    'купить', 'заказать', 'скидка', 'акция', 'промокод',
                    'цена', 'доставка', 'оплата', 'в наличии',
                    'пиши в лс', 'пишите в лс', 'перейти на сайт',
                    'whatsapp', 'ватсап', 'telegram', 'телеграм',
                    'казино', 'ставки', 'заработок',
                    'проверить цену', 'проверить наличие',
                ],
                'block_keywords': [],
                'block_hashtags': [],
                'min_content_length': 0,
            },
            'monitoring': {
                'enabled': False,   # включить после добавления источников мониторинга
                'check_interval_min': 120,
                'catch_up_days': 3,
                'max_per_cycle': 3,
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
                'transforms': {
                    'crop': True,
                    'color_shift': True,
                    'mirror': False,
                    'strip_metadata': True,
                },
            },
            'engagement': {
                'enabled': True,
                'min_ratio': 0.1,
                'min_likes': 0,
            },
            'peak_hours': {
                'enabled': True,
                'hours': [8, 10, 13, 17, 19, 21],
            },
            'autopilot': {
                'enabled': True,
                'dry_run': False,
                'live_enabled': True,
                'cycle_interval_min': 180,
                'target_queue_days': 5,
                'daily_posts_min': 4,
                'daily_posts_max': 8,
                'posts_per_source': 35,
                'max_sources_per_cycle': 5,
                'min_candidate_score': 30,
            },
            'token_manager': {
                'last_check': '',
                'last_error': '',
                'warn_before_hours': 24,
                'user_expires_at': 0,
                'group_expires_at': 0,
            },
            'storage_cleanup': {
                'after_publish_success': True,
                'clean_orphans_after_run': True,
                'keep_failed_posts': True,
                'background_enabled': True,
                'background_interval_hours': 12,
                'auto_clean_temp': True,
                'auto_clean_orphans': True,
            },
            'cross_post': {
                'enabled': False,
                'profile_ids': [],
            },
            'recycle': {
                'enabled': True,
                'min_days': 30,
                'min_likes': 50,
                'max_per_run': 5,
            },
            'phash': {
                'enabled': False,
                'threshold': 10,
            },
            'tracking': {
                'enabled': True,
                'alert_low_views': False,
            },
            'photos_settings': {
                'enabled': True,
                'photos_per_run': 50,
                'publish_delay_min': 7200,
                'publish_delay_max': 10800,
                'delay_min': 3,
                'delay_max': 6,
                'album_title': 'Фото',
                'create_wall_post': True,
            },
            'videos_settings': {
                'enabled': True,
                'autopilot': True,         # участвует ли видео в автопилоте
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
                'enabled': True,
                'autopilot': True,         # участвуют ли клипы в автопилоте
                'clips_per_run': 10,
                'publish_delay_min': 10800,
                'publish_delay_max': 21600,
                'delay_min': 3,
                'delay_max': 5,
                'max_duration_sec': 180,
                'quality': '720',
                'create_wall_post': True,
            },
            # Жёсткий антиплагиат для видео/клипов (ffmpeg). Пустые значения =
            # рандомизируются на каждый прогон, чтобы результат был разным.
            'video_transform': {
                'hard_mode': True,         # рандомные параметры каждый раз
                'crop_percent': 0.0,       # 0 = авто (0.04-0.08 в hard режиме)
                'color_shift': True,
                'speed': 0.0,              # 0 = авто (0.96-1.05)
                'rotate_deg': 0.0,         # 0 = авто (±1.2°)
                'noise': True,
                'noise_strength': 6,
                'cut_seconds_min': 2.0,    # вырезать случайные 2-4 сек
                'cut_seconds_max': 4.0,
                'strip_metadata': True,
                'set_metadata': True,
                'meta_title': '',
                'meta_artist': '',
                'meta_comment': '',
            },
            'stories': {
                'interval_hours': 6,
            },
            'polls': {
                'enabled': True,
                'frequency': 7,
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

    @staticmethod
    def _looks_mojibake(value: str) -> bool:
        return isinstance(value, str) and any(marker in value for marker in MOJIBAKE_MARKERS)

    @staticmethod
    def _repair_string(value: str) -> str:
        if not AppState._looks_mojibake(value):
            return value
        try:
            repaired = value.encode('cp1251').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value

        old_score = sum(value.count(marker) for marker in MOJIBAKE_MARKERS)
        new_score = sum(repaired.count(marker) for marker in MOJIBAKE_MARKERS)
        return repaired if new_score < old_score else value

    def _repair_human_text(self, value, key: str = ''):
        if isinstance(value, dict):
            return {
                k: (v if k in SENSITIVE_CONFIG_KEYS else self._repair_human_text(v, k))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self._repair_human_text(item, key) for item in value]
        if isinstance(value, str) and key not in SENSITIVE_CONFIG_KEYS:
            return self._repair_string(value)
        return value

    def _normalize_config(self, raw: Dict) -> Dict:
        if 'profiles' not in raw:
            raw = self._migrate_old_config(raw)

        profiles = {}
        for pid, prof in raw.get('profiles', {}).items():
            if not isinstance(prof, dict):
                continue
            merged = self._deep_merge(
                self.default_profile(pid, prof.get('name') or pid),
                prof
            )
            merged['id'] = pid
            merged.setdefault('vk', {})['api_version'] = '5.131'
            for legacy_external_model_key in ('ol' + 'lama', 'ge' + 'mini'):
                merged.pop(legacy_external_model_key, None)
            profiles[pid] = merged

        if not profiles:
            profiles['p1'] = self.default_profile()

        active = raw.get('active_profile')
        if active not in profiles:
            active = next(iter(profiles))

        return self._repair_human_text({
            'active_profile': active,
            'profiles': profiles,
        })

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
        if not CONFIG_FILE.exists():
            return self._normalize_config(self.default_config())
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            return self._normalize_config(raw)
        except Exception as e:
            logger.error(f'Config load error: {e}')
            return self._normalize_config(self.default_config())

    def save_config(self) -> bool:
        try:
            self.config = self._normalize_config(self.config)
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
        message = self._repair_string(str(message))
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
        message = self._repair_string(str(message))
        ts = datetime.now().strftime('%H:%M:%S')
        entry = {'timestamp': ts, 'message': message, 'level': level}
        with self._lock:
            self.monitor_log.insert(0, entry)
            if len(self.monitor_log) > 200:
                self.monitor_log.pop()
        self.add_log(f'[Мониторинг] {message}', level)


app_state = AppState()
