# VK Post Reposting Bot - полная документация проекта

Дата обновления: 2026-06-07

## 1. Что это

VK Post Reposting Bot - локальное FastAPI-приложение с веб-интерфейсом для скачивания постов из VK-сообществ, обработки фото/видео, постановки постов в отложенную публикацию VK, мониторинга источников, ведения очередей, статистики и роста каналов.

Основной сценарий:

1. Пользователь настраивает VK user token, group token и group id.
2. Добавляет источники VK.
3. Скачивает посты в локальную очередь.
4. Бот обрабатывает контент: фильтры, подписи, антидубли, антиплагиат, водяной знак.
5. Публикует очередь в VK, обычно как отложенные посты.
6. После успешной публикации очищает JSON поста и связанные фото.

## 2. Запуск

Команды из корня проекта:

```powershell
python main.py
```

или:

```powershell
.\start.bat
```

После запуска интерфейс доступен по адресу:

```text
http://localhost:8000
```

Проверка живости:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Остановка штатным скриптом:

```powershell
.\stop.bat
```

## 3. Быстрые проверки

```powershell
pytest -q
python -m compileall -q main.py config.py api services workers vk
```

Проверка VK токенов:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/vk/validate
```

Playwright UI-smoke:

```powershell
pytest -q tests/test_playwright_ui.py
```

## 4. Важные правила безопасности

- `config.json` хранит реальные токены. Не публиковать файл в открытые репозитории.
- В документации и логах нельзя печатать полные токены.
- Реальная публикация меняет состояние VK-группы: появляются отложенные посты.
- Очистка очередей удаляет локальные JSON/медиа из `storage/{profile_id}`.
- Перед массовым запуском публикации проверить поле количества на дашборде.

## 5. Архитектура

Проект разделен на слои:

- `main.py` - FastAPI-приложение, статические страницы, подключение роутеров, фоновые циклы.
- `config.py` - глобальный `app_state`, загрузка/сохранение конфигурации, активный профиль, пути, логи, статистика.
- `api/` - HTTP API для UI. Здесь не должно быть тяжелой бизнес-логики.
- `workers/` - фоновые операции: скачивание, публикация, мониторинг, медиа, stories.
- `services/` - чистая бизнес-логика: storage, scheduler, антиплагиат, библиотека подписей, engagement, cleanup.
- `vk/` - низкоуровневый слой VK API и загрузки фото.
- `frontend/` - vanilla HTML/CSS/JS интерфейс.
- `tests/` - pytest и Playwright smoke.
- `storage/` - рабочие очереди и состояние профилей.
- `logs/` - runtime-логи.

## 6. Профили и storage

Конфигурация мультипрофильная:

```text
config.json
active_profile = p1 / p37fb1e / ...
profiles.{profile_id}
```

Для каждого профиля создается отдельное хранилище:

```text
storage/{profile_id}/downloaded_posts/
storage/{profile_id}/photos/
storage/{profile_id}/downloaded_photos/
storage/{profile_id}/downloaded_videos/
storage/{profile_id}/downloaded_clips/
storage/{profile_id}/statistics.json
storage/{profile_id}/daily_log.json
storage/{profile_id}/last_scheduled.txt
storage/{profile_id}/post_tracker.json
storage/{profile_id}/published_posts.json
storage/{profile_id}/source_stats.json
storage/{profile_id}/members_history.json
storage/{profile_id}/phash_cache.json
```

Главное правило: код должен брать пути через `app_state.posts_dir`, `app_state.photos_dir`, `app_state.stats_file` и другие свойства `AppState`, а не хардкодить `storage/...`.

## 7. Основные файлы

| Файл | Назначение |
|---|---|
| `main.py` | Создает FastAPI app, подключает CORS, static, роутеры, страницы `/`, `/niche`, `/growth-autopilot`, health-check. В lifespan запускает watchdog, tracker, cleanup и subscriber tracker. |
| `config.py` | `AppState`: конфиг, активный профиль, пути, логи, статистика, daily counters, нормализация старых конфигов и repair mojibake. |
| `config.json` | Реальные профили, токены, источники, настройки загрузки/публикации/обработки. Секретный runtime-файл. |
| `config_template.json` | Шаблон конфига без реальных данных. |
| `requirements.txt` | Python-зависимости. |
| `start.bat` / `stop.bat` | Запуск/остановка на Windows. |
| `build.sh` / `build.bat` | Сборочные/деплойные скрипты. |
| `README_USER.txt` | Короткая пользовательская инструкция. |
| `docs/PROJECT_DOCUMENTATION.md` | Этот подробный документ. |
| `task_plan.md`, `findings.md`, `progress.md` | Рабочие файлы текущей сессии тестирования и исправлений. |

## 8. Frontend

| Файл | Назначение |
|---|---|
| `frontend/index.html` | Основной dashboard: дашборд, очередь и публикация, каналы, настройки, медиа, библиотека, мониторинг, статистика всех каналов, логи. |
| `frontend/script.js` | Все UI-функции: загрузка данных, табы, настройки, профили, источники, публикация, мониторинг, медиа, библиотека, логи, cleanup, growth autopilot. |
| `frontend/style.css` | Светлая рабочая UI-тема, sidebar, карточки, формы, кнопки, таблицы, responsive layout. |
| `frontend/niche.html` | Отдельная страница анализа ниш. |
| `frontend/growth-autopilot.html` | Отдельная страница growth autopilot, частично заменена виджетом на dashboard. |

Важные UI-функции в `frontend/script.js`:

- `api(path, opts)` - общий fetch к `/api`.
- `post(path, data, okText)` и `del(path, okText)` - POST/DELETE с toast и refresh.
- `notify()` / `showToast()` - всплывающие уведомления.
- `switchTab()` / `renderActiveTab()` - навигация.
- `loadProfiles()`, `renderProfileSwitcher()`, `createProfile()`, `updateProfile()`, `switchProfile()`, `deleteProfile()` - профили.
- `loadConfig()`, `renderSettings()`, `collectSettings()`, `saveSettings()`, `validateVk()` - настройки.
- `renderSources()`, `addSource()`, `removeSource()`, `downloadOne()`, `downloadAllSources()` - источники и загрузка.
- `publishQueue()` - запускает публикацию указанного количества постов из dashboard.
- `loadDownloadProgress()` - прогресс загрузки/публикации.
- `loadDashboard()`, `renderDashboardGrowth()` - dashboard и growth cards.
- `loadMediaStatus()`, `saveMediaSettings()` - фото/видео/клипы.
- `loadLibrary()`, `saveLibrarySettings()`, `addLibraryEntry()`, `addLibraryPoll()` - библиотека подписей.
- `loadMonitor()`, `saveMonitorSettings()`, `addMonitorSource()` - мониторинг новостей.
- `loadLogs()`, `setLogFilter()`, `clearLogs()` - логи.
- `loadCleanupStatus()` - статус storage и кнопки очистки.
- `gaRunPlan()`, `gaStartCycle()`, `gaAnalyze()`, `gaApplyRecommendation()` - growth autopilot.

## 9. API роутеры

Все роутеры подключаются с префиксом `/api`.

### `api/config.py`

- `GET /api/config/get` - вернуть активный профильный конфиг.
- `POST /api/config/save` - сохранить настройки активного профиля.
- `POST /api/config/upload_logo` - загрузить PNG-логотип для watermark.

### `api/profiles.py`

- `GET /api/profiles` - список профилей с active/pending.
- `POST /api/profiles/create` - создать профиль.
- `POST /api/profiles/switch` - переключить активный профиль.
- `POST /api/profiles/update` - обновить имя/group id.
- `DELETE /api/profiles/{pid}` - удалить профиль.

### `api/sources.py`

- `POST /api/sources/add` - добавить источник VK.
- `POST /api/sources/remove` - удалить источник.

### `api/download.py`

- `POST /api/download/start` - скачать из одного источника.
- `POST /api/download/start_all` - скачать из всех включенных источников.
- `POST /api/download/start_and_publish` - скачать и затем публиковать.
- `POST /api/download/pause` - остановить загрузку.
- `GET /api/download/progress` - текущий прогресс загрузки/публикации.
- `GET /api/posts/downloaded` - список скачанных постов.

### `api/publish.py`

- `POST /api/publish/start` - публикация очереди. Принимает `count`.
- `POST /api/publish/pause` - остановить публикацию.
- `GET /api/posts/pending` - очередь постов.
- `GET /api/publish/last_scheduled` - локальная дата последнего отложенного поста.
- `POST /api/publish/last_scheduled` - сохранить локальную дату.
- `POST /api/publish/last_scheduled_from_vk` - синхронизировать дату с VK.
- `POST /api/publish/fill_slots` - найти пустые слоты в отложке.
- `POST /api/publish/fill_slots_apply` - заполнить найденные слоты.
- `POST /api/publish/check_engagement` - обновить engagement-модель по опубликованным постам.

### `api/dashboard.py`

- `GET /api/dashboard` - базовые метрики.
- `GET /api/dashboard/growth` - dashboard + growth/subscribers/tracker/autopilot.

### `api/media.py`

- Фото: `/media/photos/download/start`, `/stop`, `/publish/start`, `/publish/stop`, `/status`.
- Видео: `/media/videos/download/start`, `/stop`, `/publish/start`, `/publish/stop`, `/status`.
- Клипы: `/media/clips/download/start`, `/stop`, `/publish/start`, `/publish/stop`, `/status`.
- `GET /api/media/status` - общий статус медиа.

### `api/monitor.py`

- `GET /api/monitor/status` - состояние мониторинга.
- `POST /api/monitor/start` / `stop` - управление мониторингом.
- `GET /api/monitor/log` - лог мониторинга.
- `POST /api/monitor/sources/add/remove/toggle` - источники мониторинга.
- `POST /api/monitor/settings` - настройки мониторинга.

### `api/library.py`

- `GET /api/library` - загрузить библиотеку.
- `POST /api/library/save` - сохранить флаги библиотеки.
- `GET /api/library/niches` - список нишевых пресетов.
- `POST /api/library/apply_niche` - применить пресет.
- `POST /api/library/reset` - сбросить библиотеку.
- `POST /api/library/entry/add`, `DELETE /api/library/entry/{idx}` - заготовки.
- `POST /api/library/poll/add`, `DELETE /api/library/poll/{idx}` - опросы.

### Growth API

- `api/growth.py`: поиск источников, source stats, tracker, recycle, pHash, suspicious check.
- `api/growth_extra.py`: подписчики, stories, giveaway, pinned post.
- `api/growth_autopilot.py`: status, run, dry-run, cycle start/status, analyze, apply recommendation.
- `api/autopilot.py`: старый autopilot status/defaults/run/start/stop.

### Остальные API

- `api/cleanup.py` - storage status, cleanup posts/junk/media/all.
- `api/logs.py` - получить/очистить логи.
- `api/statistics.py` - статистика активного и всех профилей.
- `api/tests.py` - `/api/vk/validate`.
- `api/tokens.py` - masked token status, parse, validate.
- `api/niche_analyzer.py` - scan/results/add-source.
- `api/external_publish.py` - публикация внешней папки.

## 10. Worker-слой

### `workers/download.py`

Главные функции:

- `download_batch_size()` - размер VK scan batch.
- `download_scan_limit()` - ограничение глубины скана.
- `select_photos_for_download()` - сколько фото скачать для поста.
- `_download_source()` - скачать посты из одного VK community.
- `download_worker()` - поток загрузки одного источника.
- `download_all_worker()` - загрузить все включенные источники.
- `download_then_publish_worker()` - загрузка + публикация.
- `run_media_autopilot()` - дополнительно запускает фото/видео/клипы.
- `post_passes_filters()` - фильтры постов.

### `workers/publish.py`

Главные функции:

- `_upload_local_photos_with_fallback()` - загрузка выбранных фото и резервного фото, если выбранное не прошло VK upload.
- `publish_worker(count)` - основная публикация очереди.
- `adjust_to_publish_window()` - сдвиг времени в рабочее окно.
- `adjust_to_peak_hours()` - сдвиг в пиковые часы.
- `_cross_post()` - кросс-постинг в другие профили.

Публикация делает:

1. Проверяет user token, group token, group id.
2. Берет первые `count` JSON из `app_state.posts_dir`.
3. Выбирает дату публикации из `last_scheduled.txt`, VK sync или текущего времени.
4. Применяет smart schedule / growth schedule.
5. Очищает или собирает подпись через `compose_caption()`.
6. Делает анти-плагиат фото, watermark, upload фото.
7. Вызывает `vk.wall.post`.
8. Записывает tracker/engagement.
9. Удаляет JSON и медиа только после успешного поста.

### `workers/monitor.py`

- `_monitor_cycle()` - один цикл проверки источников.
- `_monitor_process_post()` - обработка найденного поста.
- `monitor_worker()` - долгий цикл мониторинга.
- `_watchdog_loop()` - перезапускает мониторинг при падении.

### Медиа воркеры

- `workers/photos.py` - альбомные фото: download/publish/queue_count.
- `workers/videos.py` - видео: download, upload, publish, clips mode.
- `workers/clips.py` - legacy wrapper для клипов.
- `workers/stories.py` - фото/видео stories.
- `workers/external_publish.py` - публикация файлов из внешней папки.
- `workers/growth_tasks.py` - подписчики, giveaway, pinned post.

## 11. Services

| Файл | Основные функции |
|---|---|
| `services/storage.py` | `read_offsets`, `save_offset`, `clear_offset`, `read_last_scheduled`, `write_last_scheduled`, monitor state helpers. |
| `services/cleanup_storage.py` | Безопасное удаление: `storage_status`, `cleanup_post_artifacts`, `cleanup_downloaded_posts`, `cleanup_junk`, `cleanup_media_queues`, `cleanup_loop`. |
| `services/content_library.py` | Универсальные подписи/CTA/опросы: `load_library`, `save_library`, `apply_niche_preset`, `dedupe_hashtags`, `compose_caption`, `get_random_caption`. |
| `services/photo_transform.py` | Фото-антиплагиат: crop, color shift, mirror, strip metadata. |
| `services/video_transform.py` | FFmpeg-антиплагиат видео: crop, speed, noise, rotate, cut segment, metadata, logo. |
| `services/watermark.py` | Text/logo watermark для фото. |
| `services/phash.py` | Perceptual hash cache, duplicate check. |
| `services/ocr.py` | OCR-фильтр фото через Tesseract. |
| `services/polls.py` | Создание VK poll attachment. |
| `services/smart_scheduler.py` | Умное расписание с timezone, heatmap и min-gap. |
| `services/slot_finder.py` | Получение занятых слотов VK, поиск пустых слотов, заполнение очередью. |
| `services/engagement.py` | Учет опубликованных постов, сбор views/likes/reposts, построение engagement model. |
| `services/tracker.py` | Tracker published posts, heatmap по часам, summary, periodic check. |
| `services/growth_autopilot.py` | Scoring, dedup, dry-run, cycle, learned 24h schedule, рекомендации. |
| `services/autopilot.py` | Старый autopilot report/defaults/live once. |
| `services/niche_analyzer.py` | Поиск и оценка нишевых VK-сообществ. |
| `services/google_image.py` | Получение картинки через Google Custom Search. |

## 12. VK layer

### `vk/api.py`

- `get_vk_api()` - создать VK API client.
- `vk_call_safe()` - retry на rate/network ошибки.
- `validate_vk_tokens()` - проверка user/group токенов.
- `fetch_last_postponed_from_vk()` - найти последний отложенный пост.
- `get_best_photo_url()` - выбрать лучшую ссылку фото.
- `post_passes_filters()` / `post_matches_ad_stopper()` - фильтры рекламы.
- `normalize_owner_id()` - привести VK owner id.

### `vk/upload.py`

- `download_photos_for_post()` - скачать фото исходного поста в storage.
- `upload_photo_from_file()` - загрузить локальное фото на стену VK.

После обновления 2026-06-07 `upload_photo_from_file()`:

- ретраит пустой/не-JSON ответ upload-сервера VK;
- логирует HTTP status и начало body;
- возвращает `None`, если фото не принято после 3 попыток.

## 13. Тесты

| Тест | Что проверяет |
|---|---|
| `tests/conftest.py` | Добавляет корень проекта в `sys.path` для точечных pytest-запусков. |
| `test_content_library.py` | Универсальные подписи, dedupe hashtag, caption compose, reset old entries. |
| `test_dashboard_growth.py` | Dashboard payload с growth-данными. |
| `test_download_worker.py` | Batch/scan limits и выбор фото. |
| `test_growth_autopilot.py` | Scoring, dedup, schedule preview, heatmap, learned 24h schedule. |
| `test_photo_transform.py` | Crop/color/mirror/metadata transforms. |
| `test_playwright_ui.py` | Запуск локального сервера, Playwright UI tabs, action controls, download menu, console errors. |
| `test_post_filters.py` | Рекламный стоппер и ручные block keywords. |
| `test_publish_import.py` | `workers.publish` импортируется и не содержит syntax error. |
| `test_publish_upload_resilience.py` | Retry non-JSON VK upload и fallback на другое фото. |
| `test_video_transform.py` | FFmpeg chain, cut segments, metadata, logo, missing file behavior. |

## 14. Реальный тест 2026-06-07

Было выполнено:

- `pytest -q` - 50 passed.
- `python -m compileall -q main.py config.py api services workers vk` - passed.
- Playwright UI smoke - passed.
- VK token validate - `user_ok=true`, `group_ok=true`.
- Реальная публикация через UI:
  - post `4097` успешно поставлен в VK, слот `16.06 06:33`.
  - post `4098` успешно поставлен в VK, слот `16.06 06:43`.

Найденная ошибка:

- один пост не загрузил фото из-за пустого/не-JSON ответа VK upload server.

Исправление:

- retry и диагностика в `vk/upload.py`;
- fallback на другое локальное фото в `workers/publish.py`;
- regression-тесты в `tests/test_publish_upload_resilience.py`.

## 15. Частые проблемы

| Симптом | Где смотреть | Что делать |
|---|---|---|
| `User Token не задан` / `Group Token не задан` | `config.json`, UI Settings, `/api/vk/validate` | Заполнить токены. |
| `VK API ошибка 5/28` | `logs/bot.log`, UI Logs | Обновить токены. |
| `VK API 214` | `workers/publish.py`, логи публикации | Время занято, бот сдвигает slot. |
| Фото не загрузилось | `vk/upload.py`, `logs/bot.log` | Проверить сеть/VK upload; теперь есть retry/fallback. |
| OCR падает | `services/ocr.py` | Установить Tesseract или выключить OCR-фильтр. |
| FFmpeg ошибка | `services/video_transform.py`, logs | Проверить `ffmpeg`/`ffprobe` в PATH и параметры transform. |
| Очередь не уменьшается | `storage/{profile}/downloaded_posts`, UI Logs | Посты не проходят upload/VK API; смотреть последние ошибки. |
| UI не обновляет прогресс | `/api/download/progress`, `frontend/script.js` | Проверить сервер и console errors. |

## 16. Что было улучшено 2026-06-07

- Исправлен syntax error в `workers/publish.py` из-за smart quotes.
- Добавлен тест импорта publish worker.
- Добавлен `tests/conftest.py`.
- Уточнен тест библиотеки подписей и нейтрализованы специфичные captions.
- На dashboard добавлены кнопки загрузки/публикации, поле количества, stop-кнопки и прогресс.
- Добавлены вкладки мониторинга и статистики всех каналов.
- Исправлен `showToast` alias.
- Улучшены светлые стили all-stats.
- Добавлены Playwright UI smoke-тесты.
- Добавлена устойчивость VK photo upload к пустым/не-JSON ответам.
- Добавлен fallback на резервное фото при публикации.


## 2026-06-07 Update: Slots, Anti-Plagiarism, Duplicate Filters

### Slot publishing now uses the normal publish pipeline

`services/slot_finder.py::fill_slots_with_queue()` no longer uploads `_local_photos` directly. For every slot it now reuses helpers from `workers/publish.py`:

- `_compose_publish_text()` clears original source text when `antiplagiaat.clear_text=true` and composes the final caption/hashtags.
- `_prepare_local_photos_for_publish()` applies anti-plagiarism photo selection: remove one photo, limit max photos, shuffle order, run `services/photo_transform.py`, then apply watermark if enabled.
- `_upload_local_photos_with_fallback()` uploads selected photos and tries another local photo when VK upload fails or returns an invalid response.

Result: manual slot filling and normal queue publishing now behave the same way. Slots should not repost raw source text/photos anymore.

### Broken queue files no longer block slot filling

If a slot candidate JSON disappeared, has missing local photos, or all photos fail upload, the slot worker skips that item and tries the next queue post for the same slot. Broken JSON files are moved to:

```text
storage/<profile_id>/failed_posts/
```

This prevents repeated `[Слоты]` errors on the same missing `downloaded_posts/*.json` or `photos/*/photo_*.jpg` path.

### Duplicate checks are disabled before anti-plagiarism

The bot now treats downloaded posts as publish candidates even if pHash or old queue checks would call them duplicates. Active and default settings were changed to:

```json
{
  "download_settings": { "check_duplicates": false },
  "phash": { "enabled": false }
}
```

`workers/download.py` also ignores pHash duplicate skipping at runtime. This is intentional: anti-plagiarism changes the final post before publishing, so dropping candidates during download can make the cycle scan forever without filling the queue.

### Regression tests added

- `tests/test_slot_finder_publish.py` checks that slot filling clears original text, transforms selected photos, and uploads the anti-plagiarism result.
- `tests/test_download_worker.py::test_download_saves_phash_duplicate_when_antiplagiarism_will_rewrite_photo` checks that a pHash duplicate is still saved into the queue.

Verification after this update:

```text
pytest -q -> 54 passed, 1 warning
python -m compileall -q main.py config.py api services workers vk -> passed
```