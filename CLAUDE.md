# VK Post Reposting Bot

## Project rule

- Do not add UI elements, product features, behavior changes, or "nice-to-have" improvements without explicit user permission. If an improvement seems useful, ask first and wait for approval.
- Start new Codex sessions from `docs/AGENT_CONTEXT.md`; read broader project files only when the current task needs them.

**Статус:** 🟢 прод
**Язык:** Python 3.10+ / FastAPI, порт 8000
**Запуск:** `start.bat` или `python main.py`
**Гит:** `/c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/.git`

Скачивает посты из VK-сообществ, обрабатывает (антиплагиат, водяные знаки,
хэштеги) и ставит их в отложенную публикацию своей группы. Поддерживает
несколько профилей (каналов), мониторинг в реальном времени, автопилот.

## Документация

| Файл | Для чего |
|---|---|
| `docs/AGENT_CONTEXT.md` | Короткий контекст для Codex: читать первым, чтобы не перечитывать весь проект |
| `docs/PROJECT_DOCUMENTATION.md` | Полная техническая документация: все API роутеры, services, workers, тесты |
| `docs/РУКОВОДСТВО_ПОЛЬЗОВАТЕЛЯ.md` | Нетехническое руководство для владельца канала |
| `.claude/rules/bot-invariants.md` | Архитектурные инварианты для Python-кода (слои, AppState, логирование) |
| `.claude/commands/` | Слэш-команды: `/build`, `/state`, `/cleanup`, `/test-tokens`, `/start`, `/logs`, `/commit`, `/deploy` |

---

## Архитектура

```
vk-post-reposting-bot/
├── main.py            # FastAPI app, lifespan: запускает все фоновые циклы
├── config.py          # AppState синглтон, пути, логирование, конфиг
├── config.json        # Конфиг профилей (НЕ трогать руками во время работы бота)
├── vk/                # VK API: api.py (vk_call_safe, validate_vk_tokens),
│                       upload.py (загрузка фото/видео)
├── services/          # Бизнес-логика без HTTP: storage, autopilot,
│                       growth_autopilot, learning, tracker, content_library,
│                       smart_scheduler, ocr, phash, media_pipeline,
│                       photo_transform, video_transform, watermark, telegram
├── workers/           # Фоновые задачи (daemon-потоки): download, publish,
│                       monitor, media_autopilot, photos, videos, clips
├── api/               # FastAPI роутеры (тонкий слой, /api/* )
├── frontend/          # Vanilla JS SPA (frontend/js/*.js модули)
├── storage/{profile_id}/   # Изолированное состояние каждого профиля
├── logs/bot.log       # Основной лог
└── tests/             # pytest
```

Подробное описание каждого роутера/сервиса/воркера —
`docs/PROJECT_DOCUMENTATION.md`.

---

## AppState синглтон (config.py)

Всё состояние живёт в `app_state` (один экземпляр, создан в `main.py`):

```python
class AppState:
    active_profile_id: str   # текущий профиль (p1, p37fb1e, ...)
    profile: Dict            # конфиг активного профиля
    config: Dict             # весь config.json

    posts_dir: Path          # storage/{profile_id}/downloaded_posts/
    photos_dir: Path         # storage/{profile_id}/photos/
    stats_file: Path         # storage/{profile_id}/statistics.json
    offsets_file: Path       # storage/{profile_id}/download_offsets.json

    is_downloading: bool
    is_publishing: bool
    is_autopilot: bool
    is_monitoring: bool
    is_niche_scanning: bool

    download_progress: Dict  # {'current': N, 'total': M, 'source': ''}
    logs: List[Dict]         # для фронтенда
    monitor_log: List[Dict]
    autopilot_last_report: Dict

    add_log(msg, level)
    save_config()            # сохранить config.json на диск
```

**Профиль** (`config.json` → `profiles.{profile_id}`) содержит блоки:
`vk` (user_token, group_token, group_id), `sources`, `download_settings`,
`publishing_settings`, `processing` (watermark/ollama/antiplagiaat),
`monitoring`, `autopilot`. Полный пример — `docs/PROJECT_DOCUMENTATION.md`.

---

## Ключевые воркеры

- **`publish_worker`** (`workers/publish.py`) — читает `posts_dir`, синхронизирует
  время с `fetch_last_postponed_from_vk()` и `last_scheduled.txt`, применяет
  watermark/antiplagiaat/ollama, грузит фото через `user_token`, вызывает
  `wall.post(publish_date=...)`. После успеха удаляет JSON+фото и обновляет
  `last_scheduled.txt`. На ошибку 214 сдвигает время следующего поста.

- **`download_worker`** (`workers/download.py`) — для каждого источника
  `vk.wall.get(owner_id, count=100, offset=N)`, фильтрует по `photo_only` и
  `block_keywords`, скачивает фото в `photos/{cid}_{post_id}/`, сохраняет JSON
  с `_local_photos` и обновляет `download_offsets.json`.

- **`monitor_worker`** (`workers/monitor.py`) — раз в `check_interval_min`
  проверяет включённые источники; первые `max_per_cycle` постов публикует
  почти сразу, остальные — в обычную очередь. OCR-фильтр пропускает фото с
  текстом. `_watchdog_loop` в `main.py` перезапускает воркер при падении.

- **`media_loop_worker`** (`workers/media_autopilot.py`) — 4 независимых
  цикла автопилота: посты / фото / видео / клипы. Каждый: скачать →
  антиплагиат (`services/media_pipeline.py`) → опубликовать → пауза →
  повтор. Интервалы — `autopilot.intervals.{type}` (дефолт 180 мин).
  Кнопки на дашборде, API: `/api/autopilot/loop/{type}/start|stop`.

- **Антиплагиат** (`services/media_pipeline.py`) — единая точка для всех
  медиа: фото (Pillow: кроп, цвет, зеркало, blur-плашки, рамка, вотермарка,
  подмена EXIF) и видео/клипы (ffmpeg: кроп, вырез, лого, скорость, шум,
  фейды, квадрат/вертикаль с blur-плашками). В hard-режиме параметры
  рандомятся на каждый файл. Клипы всегда приводятся к 9:16.

---

## Известные грабли

1. **Tesseract не в PATH** — OCR упадёт. Решение: установить Tesseract или
   выключить `monitoring.ocr_filter`.
2. **Orphaned photos** — если бот упал между удалением JSON и папки с фото.
   Чистить через `/api/cleanup/junk` (см. `/cleanup`).
3. **VK 214** (слот занят) — воркер сам сдвигает `next_ts`. Если повторяется
   часто — очередь VK переполнена (лимит ~150 отложенных постов).
4. **Токен истёк (5/28)** — бот останавливается + Telegram-алерт. Обновить
   токен в Настройках UI, проверить через `/test-tokens`.
5. **config.json перезаписывается** при каждом сохранении настроек из UI —
   не редактировать руками во время работы бота.
6. **Старое хранилище** `storage/downloaded_posts/` (без profile_id) —
   легаси v1, бот его не читает, можно удалить.
7. **publish_delay_min > publish_delay_max** — код меняет местами
   автоматически, но лучше настроить правильно в конфиге.

---

## Что осталось сделать

- [ ] Дедупликация orphaned photo directories при запуске
- [ ] Retry при 214 с повтором того же поста (сейчас только сдвигает timestamp)
- [ ] Детальная статистика по источникам (views/likes за источник)

---

## Checkpoint (2026-06-13 19:05)

**Slot scheduler + media quality (план `docs/superpowers/plans/2026-06-13-slot-scheduler-and-media-quality.md`, 16/16 задач):**
- `services/slot_scheduler.py`: единый резерв слотов публикации для постов/
  фото/видео/клипов — `reserve_slot()`/`record_slot()`, `min_gap` между
  любыми типами, дневные лимиты (видео=1, клипы=2/день, хардкод). Хранится в
  `app_state.scheduled_slots_file`. Подключён во все 3 publish-воркера —
  больше нет коллизий слотов и спама постов с интервалом 10-30 мин
- pHash-дедуп (`services/phash.py`) включён для фото (был выключен по
  умолчанию) и расширен на видео/клипы (хэш кадров)
- Engagement-фильтр отключён хардкодом в коде (не в config.json) — забираются
  все посты источника, а не только "лучшие"
- `services/publish_log.py`: структурированный JSONL-лог каждой попытки
  публикации (`success|failed|duplicate|skipped`) в
  `storage/{profile}/publish_log.jsonl`, авторотация в `.gz` раз в сутки —
  вызывается из `media_loop_worker` на каждом проходе
- Видео-антиплагиат смягчён: crop 1-3% (было 4-8%), fade-вероятность 20%
  (было 50%), рамка 10% (было 30%), aspect_mode веса смещены к `original`
  (0.65/0.25/0.10) — меньше потери качества
- Фото-кроп по умолчанию 1-2.5% (было 2-5%) — `apply_random_crop`

**Полный набор тестов: 126 passed** (`pytest tests/ -q --ignore=tests/test_playwright_ui.py`)

**Следующий шаг:**
- Понаблюдать неделю за `publish_log.jsonl` — убедиться что слоты не
  коллизят и дневные лимиты видео/клипов соблюдаются
- Создать скилл `.claude/commands/` для авто-коммитов и авто-деплоя
  (запрошено пользователем, не сделано в этой сессии)

**Блокеры:**
- tests/test_playwright_ui.py: 2 теста падали и до изменений (среда)
