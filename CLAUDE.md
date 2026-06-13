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
| `.claude/commands/` | Слэш-команды: `/build`, `/state`, `/cleanup`, `/test-tokens`, `/start`, `/logs` |

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

## Checkpoint (2026-06-13 17:36)

**Сделано (по отчёту «closed-loop optimizer»):**
- Библиотека: 500 подписей в 5 семействах (Q/E/M/C/R по 100, id Q001..R100),
  веса по форматам (`FORMAT_CATEGORY_WEIGHTS`: фото 30/25/15/15/15,
  клип cta35/q25/r20/e15/m5), cooldown 14 дней на caption_id
  (`caption_usage.json`)
- Трекер: снимки метрик 1ч/6ч/24ч/72ч (`snapshots`, loop каждые 15 мин),
  `media_type` у поста, velocity = views_1h/views_24h, нормированный score
  к медиане формата (`compute_post_score`, пороги: ≥1.5 promote, <0.8 kill)
- `services/source_quality.py`: white/stop-листы источников по median score
  (white ≥1.2, stop <0.7 при 10+ постах, кулдаун 21 день); стоп-лист
  применяется в циклах скачивания постов/фото/видео/клипов
- Learning: веса семейств обучаются отдельно на фото и клипы
  (ER = likes + 4×comments + 8×reposts, по отчёту)
- API: `/growth/caption_stats` (по форматам), `/growth/post_scores`,
  `/growth/source_quality`, `/growth/source_quality_recalc`

**Clip assembler v1 (`services/clip_assembler.py`) — сделан и проверен живым ffmpeg:**
- Hook-оверлей на клипы: 4 семейства (curiosity/escape/scale/rating),
  drawtext с автопереносом, CTA последние 1.5с у ~25% клипов. Автоматически
  в publish-цикле клипов (выкл: `clips_settings.overlay_enabled=false`).
  Семейство выбирает UCB-бандит по статистике трекера (после 12 клипов)
- Slideshow-клипы из фото: 9:16 1080×1920, zoompan, фейды. Звук: треки из
  `storage/music/`, а если их нет — аудиодорожка случайного скачанного
  клипа/видео (донор). Собираются АВТОМАТИЧЕСКИ в цикле автопилота клипов
  (`slideshow_auto`, по 2 за проход при ≥6 фото в очереди). Формат `slideshow_clip`
- Шрифт: C:/Windows/Fonts (arialbd и др.), `clips_settings.overlay_font`

**Полная автономия (всё из отчёта работает само):**
- `services/bandit.py` — батчевый UCB: выбор семейства подписей
  (после 20 применений на формат, epsilon 0.2) и hook-оверлеев
- `services/seasonality.py` — сезонные веса source_bucket (таблица отчёта);
  источники сортируются по сезону во всех циклах скачивания. Разметка:
  `"bucket": "sea|mountain|forest|snow|waterfall"` у источника в config.json
  (без метки — вес 1.0)
- repeat_winners включён по умолчанию (сам ждёт, пока появятся победители)
- overlay_family трекается; API: `/growth/boost_candidates` (score ≥ 2.0,
  кандидаты на платный буст), `/growth/weekly_report` (winners/losers,
  семейства, оверлеи, источники)

**Следующий шаг:**
- Через неделю: `/api/growth/weekly_report` — проверить что снимки,
  score и бандиты копят данные
- Опционально: разметить источники по bucket, сократить очередь VK до 10-14 дней

**Блокеры:**
- tests/test_playwright_ui.py: 2 теста падали и до изменений (среда)
