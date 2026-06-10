# VK Post Reposting Bot

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
│                       smart_scheduler, ocr, phash, photo_transform,
│                       video_transform, watermark, telegram, cleanup_storage
├── workers/           # Фоновые asyncio-задачи: download, publish, monitor,
│                       autopilot, photos, videos, clips, stories
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

- **`autopilot_worker`** (`workers/autopilot.py`) — цикл:
  скачать → опубликовать → подождать `cycle_interval_min` → повторить.
  Отчёт после цикла уходит в Telegram (если настроен).

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

## Checkpoint (2026-06-10)

**Сделано:**
- Реорганизация `.claude/`: удалены `.claude/README.md` и `.claude/AUTOUPDATE.md`
  (дублировали друг друга и CLAUDE.md), CLAUDE.md сокращён с 491 до ~200 строк
  по глобальному лимиту, добавлен `paths:` в `bot-invariants.md`
- Переписаны `/build`, `/state`, `/cleanup`, `/test-tokens` под реальные
  эндпоинты и функции (старые версии ссылались на несуществующие файлы/роуты)
- Удалены `.env.example` (мёртвый, ничего не читает env), `CLAUDE.md.backup`,
  `__pycache__`, `.pytest_cache`
- Создано `docs/РУКОВОДСТВО_ПОЛЬЗОВАТЕЛЯ.md` — нетехнический гайд для владельца

**Активно:**
- Нет незавершённого

**Следующий шаг:**
- При следующих изменениях кода — держать этот файл под 200 строк, новые
  детали выносить в `docs/PROJECT_DOCUMENTATION.md` или `.claude/rules/`

**Блокеры:**
- Нет
