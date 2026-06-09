# VK Post Reposting Bot — Полное описание проекта

**Статус:** 🟢 прод  
**Язык:** Python 3.10+  
**Framework:** FastAPI  
**Порт:** 8000  
**Запуск:** `start.bat` или `python main.py`  
**Гит:** `/c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/.git`

---

## Быстрые команды

```bash
# Запуск
python main.py
start.bat

# Тесты
pytest tests/ -v

# Проверка токенов
curl http://localhost:8000/api/tests/vk_tokens

# Очистка orphaned photos
curl -X POST http://localhost:8000/api/cleanup/orphaned_photos

# Логи
tail -f logs/bot.log
```

---

## Архитектура

### Слои проекта

```
vk-post-reposting-bot/
├── main.py                    # FastAPI app, lifespan, инициализация воркеров
├── config.py                  # AppState синглтон, пути, логирование
├── config.json                # Конфиг профилей (НЕ трогай руками)
├── requirements.txt           # pip зависимости
├── start.bat / stop.bat       # Windows управление процессом
│
├── vk/                        # VK API слой
│   ├── api.py                 # get_vk_api(), vk_call_safe(), fetch_last_postponed_from_vk()
│   └── upload.py              # download_photos_for_post(), upload_photo_from_file()
│
├── services/                  # Бизнес-логика (без HTTP)
│   ├── storage.py             # read/write состояния (last_scheduled, offsets, stats)
│   ├── autopilot.py           # Safe organic-growth autopilot
│   ├── growth_autopilot.py    # Growth Autopilot: скоринг, dry-run, цикл
│   ├── learning.py            # Обучение на engagement данных
│   ├── tracker.py             # Трекинг views/likes после публикации
│   ├── competitor.py          # Анализ конкурентов
│   ├── content_library.py     # Библиотека текстов и ниши
│   ├── niche_analyzer.py      # Поиск и ранжирование ниш VK
│   ├── smart_scheduler.py     # Умное расписание публикаций
│   ├── slot_finder.py         # Поиск пустых слотов в очереди
│   ├── engagement.py          # Проверка engagement постов
│   ├── ocr.py                 # photo_has_text() через pytesseract
│   ├── phash.py               # Перцептивное хэширование (дедупликация)
│   ├── photo_transform.py     # Трансформации фото (антиплагиат)
│   ├── video_transform.py     # ffmpeg-обработка видео/клипов
│   ├── watermark.py           # Водяные знаки
│   ├── google_image.py        # Запасной источник картинок
│   ├── polls.py               # Генерация опросов
│   ├── telegram.py            # send_telegram(), send_critical_alert()
│   └── cleanup_storage.py     # Фоновая очистка storage
│
├── workers/                   # Фоновые задачи
│   ├── download.py            # download_worker(), download_all_worker()
│   ├── publish.py             # publish_worker() — публикация в VK
│   ├── monitor.py             # monitor_worker() + _watchdog_loop()
│   ├── external_publish.py    # Публикация медиа из папки
│   ├── growth_tasks.py        # track_subscribers_once(), subscriber_tracker_loop()
│   ├── photos.py              # Скачивание/публикация фото
│   ├── videos.py              # Скачивание/публикация видео
│   ├── clips.py               # Скачивание/публикация клипов
│   └── stories.py             # Публикация stories
│
├── api/                       # FastAPI роутеры (тонкий слой — только роутинг)
│   ├── growth.py              # /api/growth/* (включает бывший growth_extra)
│   ├── growth_autopilot.py    # /api/growth-autopilot/*
│   ├── autopilot.py           # /api/autopilot/*
│   └── ...                    # остальные роутеры
│
├── frontend/                  # Vanilla JS SPA
│   ├── index.html             # Главная страница
│   ├── style.css              # Все стили
│   └── js/                    # JS модули (разбит из script.js)
│       ├── core.js            # state, api(), post(), notify(), switchTab()
│       ├── dashboard.js       # loadDashboard(), profiles, allStats
│       ├── channels.js        # renderProfiles(), renderSources(), download*()
│       ├── settings.js        # renderSettings(), tokens, media, watermark
│       ├── autopilot.js       # autopilot, growth autopilot, logs, monitor, library
│       └── init.js            # DOMContentLoaded, интервалы опроса
│
├── storage/
│   └── {profile_id}/          # Изолированный storage для каждого профиля
│       ├── downloaded_posts/  # JSON-файлы скачанных постов
│       ├── photos/            # {community_id}_{post_id}/*.jpg (локальные фото)
│       ├── download_offsets.json
│       ├── statistics.json
│       ├── daily_log.json
│       ├── post_tracker.json  # Ежечасная аналитика (views, likes, reach)
│       ├── monitor_last_seen.json
│       ├── monitor_published.json
│       ├── source_stats.json  # Статистика по источникам
│       ├── members_cache.json # Кеш членов сообщества для мониторинга
│       ├── members_history.json
│       └── seen_photos.json   # pHash для дедупликации
│
├── logs/
│   ├── bot.log                # Основной лог (app-wide)
│   ├── monitor.log            # Лог мониторинга (если используется)
│   └── (другие логи)
│
├── tests/                     # pytest тесты
├── docs/                      # Документация
└── .git/                      # Git репозиторий
```

---

## AppState синглтон (config.py)

Всё состояние бота живёт в `app_state` (создаётся один раз в `main.py`):

```python
class AppState:
    # ── Профилизация ────────────────────────
    active_profile_id: str          # текущий ID профиля (p1, p37fb1e, etc.)
    profile: Dict                   # словарь конфига активного профиля
    config: Dict                    # весь config.json
    
    # ── Пути ─────────────────────────────────
    posts_dir: Path                 # storage/{profile_id}/downloaded_posts/
    photos_dir: Path                # storage/{profile_id}/photos/
    stats_file: Path                # storage/{profile_id}/statistics.json
    offsets_file: Path              # storage/{profile_id}/download_offsets.json
    
    # ── Флаги воркеров ──────────────────────
    is_downloading: bool            # скачивание постов
    is_publishing: bool             # публикация постов
    is_autopilot: bool              # цикл autopilot
    is_monitoring: bool             # мониторинг новостей
    is_niche_scanning: bool         # сканирование ниши
    
    # ── Прогресс ─────────────────────────────
    download_progress: Dict         # {'current': N, 'total': M, 'source': ''}
    niche_progress: Dict            # {'current': N, 'total': M, 'keyword': ''}
    
    # ── Логирование ──────────────────────────
    logs: List[Dict]                # последние логи для фронтенда
    monitor_log: List[Dict]         # логи мониторинга
    autopilot_last_report: Dict     # результаты последнего цикла autopilot
    
    # ── Методы ───────────────────────────────
    add_log(msg, level)             # добавить лог в список + файл
    _load_config()                  # загрузить config.json
    save_config()                   # сохранить config.json на диск
```

### Профиль (структура в config.json)

```json
{
  "vk": {
    "user_token": "",               # личный токен пользователя (для photos.getWallUploadServer)
    "group_token": "",              # токен группы (для wall.post)
    "group_id": "",                 # ID целевой группы (где публиковать)
    "api_version": "5.131"
  },
  "sources": [
    {"community_id": "33440105", "enabled": true, "name": "Source Name"}
  ],
  "download_settings": {
    "posts_to_download": 100,       # сколько постов за раз
    "delay_min": 1,
    "delay_max": 3,
    "photo_only": true,
    "block_keywords": ["реклама", "спам"]
  },
  "publishing_settings": {
    "postponed_enabled": true,
    "publish_delay_min": 3600,
    "publish_delay_max": 7200,
    "add_hashtags": true,
    "hashtags": ["#nature", "#photo"]
  },
  "processing": {
    "watermark": {"enabled": false, "logo_path": ""},
    "ollama": {"enabled": false, "model": "llama3.2:3b"},
    "antiplagiaat": {"enabled": false, "clear_text": true, "max_photos": 5}
  },
  "monitoring": {
    "enabled": false,
    "check_interval_min": 120,
    "max_per_cycle": 5
  }
}
```

---

## Ключевые воркеры

### publish_worker (workers/publish.py)

Главный воркер публикации, запускается снизу в `main.py`:

```
Логика:
1. Читает JSON-файлы из posts_dir (отсортированы по имени)
2. fetch_last_postponed_from_vk() → берёт макс timestamp отложенных постов в VK
3. Сравнивает с last_scheduled.txt → выбирает макс время
4. Для каждого поста:
   - Применяет watermark, ollama rewrite, antiplagiaat фильтры
   - upload_photo_from_file() → загружает фото в VK
   - wall.post() с publish_date (отложенная публикация)
   - DELETE JSON + папка с фото после успеха
   - UPDATE last_scheduled.txt
5. На 214 (time slot occupied): сдвигает next_ts на случайный интервал

Важно:
- user_token используется для photos.getWallUploadServer (НЕ group_token)
- Юзер должен быть редактором группы
- Максимум ~150 отложенных постов в VK (лимит платформы)
```

### download_worker (workers/download.py)

Скачивает посты из VK сообществ:

```
Логика:
1. Для каждого источника (community_id):
   - vk.wall.get(owner_id, count=100, offset=N)
   - Фильтрует: photo_only, block_keywords
2. download_photos_for_post() → скачивает фото в photos/{cid}_{post_id}/
3. Сохраняет JSON с _local_photos (абсолютные пути)
4. Сохраняет offset в download_offsets.json (для продолжения)

Сохранённый JSON:
{
  "post_id": 12345,
  "text": "...",
  "photos": [...],
  "_local_photos": ["/abs/path/to/photo1.jpg", ...],
  "source_cid": "33440105"
}
```

### monitor_worker (workers/monitor.py)

Мониторинг новостей в реальном времени:

```
Логика:
1. Каждые check_interval_min минут
2. Проверяет только включённые источники
3. Первые max_per_cycle постов → публикует сразу (через temp JSON)
4. Остальные → в очередь (обычный JSON в posts_dir)
5. OCR-фильтр: пропускает фото с текстом (AI-gen)
6. Хранит:
   - monitor_last_seen.json → последний ID проверенного поста
   - monitor_published.json → до 5000 ID опубликованных постов

Watchdog поток (_watchdog_loop в main.py):
- Перезапускает monitor_worker при падении
- Проверяет каждые 30 секунд
```

### autopilot_worker (workers/autopilot.py)

Цикл: скачивание → фильтрация → публикация в одном потоке:

```
Логика (цикл):
1. download_worker() → скачивает N постов
2. publish_worker() → публиковвает готовые посты
3. Чекает config.autopilot.cycle_interval_min
4. Повторяет
5. Отправляет отчёт на Telegram после цикла

Состояние: autopilot_last_report (для UI)
```

---

## Хранилище состояния

| Файл | Место | Назначение |
|------|-------|-----------|
| `config.json` | корень проекта | Все конфиги профилей, активный профиль |
| `downloaded_posts/*.json` | `storage/{pid}/` | Скачанные посты, ожидающие публикации |
| `photos/{cid}_{pid}/*.jpg` | `storage/{pid}/` | Локальные фото из скачанных постов |
| `last_scheduled.txt` | `storage/{pid}/` | Timestamp последнего опубликованного поста + дата |
| `download_offsets.json` | `storage/{pid}/` | Сохранённые offset-ы для продолжения скачивания |
| `statistics.json` | `storage/{pid}/` | Глобальные счётчики (`published`, `failed`, `total_reach`) |
| `daily_log.json` | `storage/{pid}/` | По дням: `{"YYYY-MM-DD": {"published": N, "failed": M}}` |
| `post_tracker.json` | `storage/{pid}/` | Ежечасная аналитика (views, likes, comments за каждый час) |
| `monitor_last_seen.json` | `storage/{pid}/` | Последняя проверка мониторинга (`{"cid": unix_ts}`) |
| `monitor_published.json` | `storage/{pid}/` | Опубликованные через мониторинг (List[str], до 5000) |
| `source_stats.json` | `storage/{pid}/` | Статистика по источникам (views, likes за источником) |
| `bot.log` | `logs/` | Основной лог (app-wide) |

---

## VK API токены

- **user_token**: личный токен пользователя (для `photos.getWallUploadServer`, `wall.get`)
- **group_token**: токен группы (для `wall.post`)
- **Требование:** пользователь **ДОЛЖЕН** быть редактором/администратором целевой группы

Проверка: `GET /api/tests/vk_tokens` или кнопка "Проверить токены" в UI.

---

## Зависимости

```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-multipart==0.0.6
python-dotenv==1.0.0
vk-api==11.9.9
requests==2.31.0
aiofiles==23.2.1
pydantic==2.5.0
pydantic-settings==2.1.0
Pillow==10.1.0
pytesseract==0.3.10
ImageHash==4.3.1
yt-dlp>=2024.1.0
```

### Требования к системе

- Python 3.10+
- Tesseract OCR (если используется `ocr_filter: true`). Скачать: https://github.com/UB-Mannheim/tesseract/wiki
- Ollama (если используется `ollama.enabled: true`). Скачать: https://ollama.ai

---

## Соглашения по коду

### Файлы в слое `services/`

Чистая бизнес-логика, **без** привязки к HTTP:

```python
# ✅ ПРАВИЛЬНО
def read_statistics(profile_id: str) -> dict:
    file_path = STORAGE_DIR / profile_id / 'statistics.json'
    return json.loads(file_path.read_text())

# ❌ НЕПРАВИЛЬНО
@router.get('/stats')
def get_stats():
    return FileResponse(...)
```

### Файлы в слое `api/`

**Только** HTTP роутинг, вызовы `services/`:

```python
@router.get('/stats')
async def get_stats():
    stats = read_statistics(app_state.active_profile_id)
    return {'data': stats}
```

### Файлы в слое `workers/`

**Только** асинхронные фоновые задачи, ни HTTP ни синхронный код:

```python
async def publish_worker():
    while True:
        posts = await load_posts()
        for post in posts:
            await publish_one(post)
        await asyncio.sleep(interval)
```

### Profile-specific paths

При работе с `posts_dir`, `photos_dir` — **всегда** используй properties из `AppState`:

```python
# ✅ ПРАВИЛЬНО (автоматически учитывает active_profile_id)
posts = list(app_state.posts_dir.glob('*.json'))

# ❌ НЕПРАВИЛЬНО (хардкодированный путь)
posts = list((STORAGE_DIR / 'downloaded_posts').glob('*.json'))
```

### Error handling

Оборачивай вызовы VK API в `try/except`, используй `vk_call_safe()`:

```python
# В vk/api.py
def vk_call_safe(method: str, params: dict, max_retries=3):
    # Автоматический retry на ошибки 6, 9 (rate limit)
    # На ошибки 5, 28 (токен) → Telegram alert + исключение
    pass
```

---

## Известные грабли

1. **Tesseract не найден** → OCR упадёт. Решение: добавить в PATH или отключить `ocr_filter`.

2. **Orphaned photos** → если бот упал между удалением JSON и удалением папки с фото. Очистка:
   ```bash
   curl -X POST http://localhost:8000/api/cleanup/orphaned_photos
   ```

3. **VK лимит 214** → время для публикации занято. Воркер автоматически сдвигает timestamp. Если очередь переполнена (>150), посты будут fail.

4. **Токен истёк (ошибка 5, 28)** → бот останавливается + Telegram алерт (если настроен).

5. **config.json перезаписывается** при сохранении из UI → не редактируй вручную во время работы бота.

6. **Старое хранилище** → `storage/downloaded_posts/` (без profile_id). Это наследие от v1. Удали вручную если не нужно.

7. **pHash кеш (seen_photos.json)** → может вырасти. Автоматическая очистка старых записей в `cleanup_storage.py`.

8. **publish_delay_min > publish_delay_max** → код меняет местами автоматически, но лучше настрой в конфиге.

---

## Обработка видео/клипов (антиплагиат через ffmpeg)

**Модуль:** `services/video_transform.py`. Требует **ffmpeg + ffprobe в PATH**.

Применяется в `publish_videos_worker` (workers/videos.py) перед заливкой видео,
если включён `antiplagiaat.enabled` ИЛИ `watermark` с `mode=logo`. Один проход
ffmpeg делает разом:
- вырезание случайных 2-4 сек из середины (`cut_seconds_min/max`) — сильнее всего ломает VK-хэш
- кроп краёв + zoom обратно (`crop_percent`)
- наложение PNG-лого через scale2ref+overlay (общий `watermark.logo_path` с фото)
- eq: яркость/контраст/насыщенность + лёгкий поворот + шум
- изменение скорости видео+аудио синхронно (`speed`)
- очистка метаданных оригинала + подмена своими (`set_metadata`, `meta_*`)

Настройки в профиле — блок `video_transform`. `hard_mode: true` = параметры
рандомизируются на каждый прогон (два запуска дают разный результат). Значение
`0` в crop_percent/speed/rotate_deg = «авто» (рандом в hard-режиме).

**Видео/клипы в автопилоте:** `run_media_autopilot()` в workers/download.py
вызывается после фото-этапа. Включается флагами `videos_settings.autopilot` и
`clips_settings.autopilot`. Клипы заливаются как Reels (`is_reels=1`).

Грабли: лого масштабируется через `scale2ref` (обычный `scale=main_w*...` падает
с "Expressions with scale2ref variables not valid"). Вырез не применяется к видео
короче 12 сек. Перекодировка libx264 veryfast crf23 — медленно по диску/CPU.

## Что осталось сделать

- [ ] Дедупликация orphaned photo directories при запуске
- [ ] Retry при 214 с повтором того же поста (сейчас только сдвигает timestamp)
- [ ] API лимит на количество одновременных скачиваний (>5 постов)
- [ ] Детальная статистика по источникам (views/likes за источник)
- [ ] Интеграция с Google Search Console для SEO метрик

---

## Checkpoint (2026-06-09 11:12)

**Сделано:**
- Рефакторинг: удалены мусорные файлы (findings.md, progress.md, task_plan.md, update.md, CHANGES_SUMMARY.md, CLAUDE.md.backup, _build_clean_config.py, SETUP_COMPLETE.txt, README_USER.txt, build.bat, build.sh, setup_aeza.sh, server.log, docs/superpowers/)
- `frontend/script.js` (1210 строк) разбит на 5 модулей в `frontend/js/`: core.js, dashboard.js, channels.js, settings.js, autopilot.js, init.js
- `api/growth_extra.py` объединён в `api/growth.py` (удалён дубль), main.py обновлён
- CLAUDE.md обновлён под реальную структуру

**Активно:**
- Нет незавершённого

**Следующий шаг:**
- Запустить `start.bat`, проверить что UI грузится (frontend/js/* подключены)
- Опциональный рефакторинг: разбить большие services/ файлы (growth_autopilot.py 960 строк)

**Блокеры:**
- Нет
