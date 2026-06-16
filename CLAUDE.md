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
| `docs/CHANGELOG.md` | История завершённых задач/чекпоинтов — поднимать только при вопросе «что менялось» |
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

- **`monitor_worker`** (`workers/monitor.py`) — **один проход** по
  включённым источникам и стоп (повтора по интервалу нет — бот запускают на
  короткое время). Первые `max_per_cycle` постов публикует почти сразу,
  остальные — в обычную очередь. OCR-фильтр пропускает фото с текстом.
  `_watchdog_loop` в `main.py` не перезапускает: `finally` ставит
  `is_monitoring=False` до завершения потока, watchdog видит штатный стоп.

- **`media_loop_worker`** (`workers/media_autopilot.py`) — автопилот по 4
  типам медиа (посты / фото / видео / клипы). На нажатие Старт делает **один
  проход**: скачать → антиплагиат (`services/media_pipeline.py`) →
  опубликовать → стоп. Повтора по интервалу нет. `autopilot.intervals.{type}`
  больше не управляет таймингом (остаётся только в выдаче `loops_status`).
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
8. **Внешние embed-видео нельзя скачать.** Некоторые источники (напр.
   `-78684694`) репостят видео с Coub/Vimeo/YouTube. В VK API `video.get`
   у них `files = {'external': ...}` без `mp4_*`. yt-dlp на них падает
   (Coub → `KeyError('params')`, Vimeo → HTTP 401). `_is_external_video()`
   в `workers/videos.py` отсекает их до скачивания — это не ошибка, а
   недоступный контент. Если источник целиком из внешних видео, видео-
   автопилот по нему скачает 0 — это норма.

---

## Что осталось сделать

- [ ] Дедупликация orphaned photo directories при запуске
- [ ] Retry при 214 с повтором того же поста (сейчас только сдвигает timestamp)
- [ ] Детальная статистика по источникам (views/likes за источник)

---

## Checkpoint (2026-06-16 13:56)

**Запрос:** убрать «тупые» текстовые подписи; вместо текста — рандомные смайлы
(сердечки и т.п.) + рандомные хэштеги; иногда призыв «подпишись/лайк/поделись».
Лимиты 3/1/2/1 — это дефолты, меняются в настройках.

**Реализация** (`services/content_library.py`): новый **emoji_mode** (дефолт
True, в `_default_lib`/`_normalize_library` — применяется и к существующим
библиотекам без ключа). В `compose_caption_with_meta` при emoji_mode:
- подпись = `random_emojis()` (1–3 смайла из `EMOJI_POOL`) + хэштеги;
- призыв `random_subscribe_cta()` из `SUBSCRIBE_CTAS` добавляется при
  `cta_enabled` с шансом `SUBSCRIBE_CTA_CHANCE` (0.35);
- хэштеги выбираются рандомно (`random.shuffle(manual_tags)`), пайплайн
  dedupe→forbidden→diversify не тронут (потолок `MAX_HASHTAGS`=3);
- `meta={}` — семейства подписей (question/mission/...) в этом режиме не
  обучаются (текстовые шаблоны не используются). Текстовый путь остался для
  `emoji_mode=False`.

Применяется ко ВСЕМ типам (посты/фото/видео/клипы), т.к. все идут через
`compose_caption_with_meta`. У p1 было `enabled/cta_enabled=True` — теперь
вместо текстов идут смайлы + хэштеги + иногда призыв подписаться.

**Тесты: 157 passed.** Новое: emoji-режим в `tests/test_content_library.py`;
legacy текстовый путь в `test_content_library.py`/`test_caption_learning.py`
помечен `emoji_mode=False`.

## Checkpoint (2026-06-16 13:56)

**Запрос:** клипы/видео/фото спамятся без отложки; на клипах/видео чужой текст;
тише звук; убрать жёсткий кроп и фейд; маленькие стартовые лимиты (3 поста /
1 фото / 2 клипа / 1 видео) с разносом по суткам (день+ночь); больше
статистики, чтобы понимать когда постить больше/меньше (только статистика,
лимиты вручную — выбор пользователя).

1. **Фото-спам — баг исправлен** (`workers/photos.py`): `publish_photos_worker`
   резервировал слот через `reserve_slot` только для ПЕРВОГО фото, дальше время
   накручивалось вручную (`next_ts += random`) в обход дневного лимита и реестра
   слотов → пачка фото за один день. Теперь `reserve_slot('photos', ...)` на
   КАЖДОЕ фото (как у видео/клипов). Убран мёртвый импорт
   `read_last_scheduled/write_last_scheduled`.
2. **Фото — свой дневной лимит** (`services/slot_scheduler.py`): раньше фото
   делили `max_posts_per_day` с постами. Добавлен `photos_settings.daily_limit`
   (дефолт 1, `_DEFAULT_PHOTOS_DAILY_LIMIT`). Посты остаются на
   `max_posts_per_day`. Итог: посты 3 / фото 1 / клипы 2 / видео 1.
3. **Объём за прогон = дневному лимиту** (config, все 3 профиля):
   `photos_publish_per_run`→1, `videos_publish_per_run`→1, `clips_publish_per_run`→2
   + `photos_settings.daily_limit`=1. Меньше заливается за прогон — нет пачки
   медиа в группе сразу (клипы остаются `is_reels=1` по выбору пользователя).
4. **Свой текст на клипах/видео** (`workers/videos.py`): `_upload_video`
   получал `title`/`description` ИСХОДНИКА — на клипе оставался чужой текст.
   Теперь подпись `compose_caption_with_meta` готовится ДО заливки и идёт и в
   `description` видео/клипа, и в запись на стене; title = первая строка нашей
   подписи (fallback «Клип»/«Видео»).
5. **Тише звук** (`services/video_transform.py`): `transform_video` принимает
   `volume_factor` (дефолт из `video_transform.volume_factor`, **0.7 = −30%**),
   добавляет `volume=` в аудио-цепочку. Применяется к видео и клипам.
6. **Убран кроп краёв и фейды** (`services/video_transform.py`): `crop_percent`
   жёстко 0 (раньше config 0.0 = «авто/рандом» 0.3–1% — грабля!), `do_fade`
   всегда False, из ротации формата убран `square_crop` (резал контент);
   остались `original`/`square_blur` (плашки, без обрезки), клипы — `vertical_blur`.
7. **Статистика по типам медиа** (`services/tracker.py`): `get_reach_trend`
   принимает `media_type`; новый `get_reach_trend_by_type` — тренд охвата по
   posts/photo/video/clip + рекомендация объёма (`reduce`/`hold`/`increase`/
   `insufficient`) на основе общего тренда. Выведено в `GET /growth/weekly_report`
   (`reach_trend_by_type`). Лимиты НЕ меняются автоматически — подсказка для
   ручной настройки.

**Сутки 24ч:** `publish_hours_enabled=false`, `apply_window_to_media=false` —
окно не режет, медиа разносятся по суткам через delays + `min_gap`.

**Тесты: 153 passed** (`pytest tests/ -q --ignore=tests/test_playwright_ui.py`).
Новое/обновлено: `tests/test_slot_scheduler.py` (лимит фото), `tests/test_tracker_reach.py`
(тренд по типам), `tests/test_video_transform.py` (crop=0, fade off, volume).

**Грабля:** config.json редактировался вручную — делать при **остановленном**
боте (грабля #5), иначе UI-сохранение перезапишет.

---

> Более ранние чекпоинты (2026-06-14 и старше) — в `docs/CHANGELOG.md`.
> Каждую сессию не нужны, поднимать по запросу.
