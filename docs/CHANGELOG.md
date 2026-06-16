# Changelog / История чекпоинтов

История завершённых задач. **Не нужна каждую сессию** — поднимать только при
вопросе «что менялось» или для контекста старого решения. Актуальный чекпоинт
и карта проекта — в `CLAUDE.md`.

---

## Checkpoint (2026-06-14) — медиа «по чуть-чуть» со всех каналов

**Запрос:** видеть в логах, с какого канала берётся медиа; брать всегда с
разных каналов понемногу, а не всё с одного.
- **Корень:** для постов распределение было (`download_all_worker`), а
  фото/видео/клипы качали полный per-run лимит с **каждого** источника →
  очередь публикации `sorted(...)[:count]` брала по имени файла `{cid}_id`,
  поэтому почти всё уходило с канала с наименьшим `community_id`.
- **Фикс:** общий хелпер `eligible_sources_in_season()` в `workers/download.py`
  (активные, не в стоп-листе, по сезону) + распределение лимита через
  `per_source_download_count` в `download_photos_worker`/`download_videos_worker`/
  `download_clips_worker`. `_download_photos_source`/`_download_videos_source`
  теперь возвращают `downloaded` (как `_download_source`), остаток
  перекидывается на следующие каналы.
- **Логи:** на каждый канал строка `Фото|Видео|Клипы: канал i/N «имя» — беру
  до N`, плюс существующая `[owner_id]: N скачано, M пропущено`.
- Тесты: **145 passed** (3 новых: распределение фото/видео + фильтр
  `eligible_sources_in_season`).

## Checkpoint (2026-06-14) — анти-теневой-бан по рекомендациям VK

**Запрос:** усилить бот по советам про теневой бан / органический рост VK.
Реализовано 5 правок (все с тестами, **142 passed**):

1. **Стоп-слова и запрещённые хэштеги в исходящих подписях**
   (`services/content_library.py`): в библиотеку добавлены `stop_words` и
   `forbidden_hashtags` (дефолт `[]`). `get_random_entry` пропускает подписи
   со стоп-словом; `compose_caption_with_meta` убирает запрещённые теги через
   `filter_forbidden_hashtags`. Это про НАШ исходящий контент — не путать с
   `filters.block_keywords/block_hashtags` (фильтр ВХОДЯЩИХ при скачивании).
2. **Разведение хэштегов между каналами** (`services/content_library.py`):
   общий журнал `storage/_shared/hashtag_usage.json`, `diversify_hashtags`
   подбирает набор тегов, не совпадающий с недавним (2 дня) набором другого
   канала — VK ловит рассылку одинаковых тегов как спам.
3. **Глобальный дневной лимит + дневное окно для медиа**
   (`services/slot_scheduler.py`): `publishing_settings.max_total_per_day`
   (0 = выкл) — потолок публикаций в день суммарно по всем типам;
   `apply_window_to_media` (выкл) — переносит слоты медиа-циклов в окно
   `publish_hours_start/end`, чтобы не постить ночью. **Оба выключены по
   умолчанию — поведение не меняется, пока не включишь в config.**
4. **Тренд охвата (ранний сигнал теневого бана)** (`services/tracker.py`
   `get_reach_trend`): сравнивает средний охват за 7 дней с предыдущими 7;
   `signal` = down/ok/insufficient. Выведено в `GET /growth/weekly_report`
   (`reach_trend`). Не алерт, просто цифра в отчёте.
5. **Клип-хук «манифест»** (`services/clip_assembler.py`): новое семейство
   оверлеев `manifest` (мини-манифест роста — «собрать миллион ради планеты»,
   призыв к лайку/подписке как рычаг охвата клипов).

**Сознательно НЕ делал** (объяснено пользователю): ручной сдвиг весов
подписей mission/cta для p1 — весами управляет learning-цикл по реальному
engagement, ручной override он перезапишет. Дневной лимит клипов не повышал
(сломал бы намеренные дефолты 1 видео / 2 клипа и их тесты).

**Ручное (вне зоны бота, делать в VK):** SEO названия/описания/обложка/меню
группы, взаимопиар, приглашения друзей, согласие на репост чужого контента.

## Checkpoint (2026-06-14) — меньше спама/хэштегов, крупнее логотип

**Запрос пользователя:** «слишком много постов, спамится, мало охватов;
поярче логотип и побольше; меньше хэштегов».
- **Хэштеги ≤3** (`services/content_library.py`): добавлена константа
  `MAX_HASHTAGS = 3`, в `compose_caption_with_meta` жёсткий потолок с
  приоритетом ручные теги канала → библиотека → конкуренты. Было до 7
  конкурентских + библиотечные + ручные. Применяется ко всем каналам.
  Тест `test_compose_caption_caps_total_tags_and_prefers_manual`.
- **Логотип** (config.json, только p1 «Дыхание Мира» — единственный канал с
  `watermark.mode=logo`): `opacity` 180→255, `logo_scale` 0.12→**0.22**.
  У p424cfd «Природа» и «Pretty Girls» водяной знак выключен (режим текст).
- **Частота** (config.json, **все 3 канала** p1/p37fb1e/p424cfd):
  `max_posts_per_day` 4→3, `publish_delay_min/max` →14400/21600 (пауза 4–6 ч).
- Правки config.json делались при **остановленном** боте (грабли #5).
- Тесты: **131 passed** (`pytest tests/ -q --ignore=tests/test_playwright_ui.py`).

**Диагноз спама (не чинили — пользователь регулирует в настройках):**
`max_posts_per_day` — лимит **на каждый тип отдельно**, не общий
([slot_scheduler.py:102-113](services/slot_scheduler.py#L102) считает
посты/фото/видео/клипы раздельными счётчиками; посты идут через
`record_slot` + smart_scheduler, остальные — через `reserve_slot`). При всех 4
включённых циклах выходит до 9 публикаций/день (посты 3 + фото 3 + видео 1 +
клипы 2). Фото тоже идут в стену (`create_wall_post`). Возможный настоящий
фикс (отложен): единый общий дневной лимит в slot_scheduler. В UI крутятся:
`max_posts_per_day` (Настройки), per-run счётчики Скачать/Опубликовать на
карточках автопилота. **НЕ в UI:** `videos_settings.daily_limit` (1) и
`clips_settings.daily_limit` (2) — только в config.json.

**Открытое:**
- Если PNG-логотип сам тёмный — opacity 255 его не осветлит, нужна подсветка
  пикселей в коде (`ImageEnhance.Brightness`), пока не делал.

## Checkpoint (2026-06-14) — фикс ложной ошибки «Backend не отвечает»

**Симптом:** тост `Backend не отвечает: Cannot set properties of null (setting
'textContent')`.
- Корень: `refreshAll()` (`frontend/js/core.js`) в одном try/catch оборачивает
  и загрузку данных, и рендер DOM → любая ошибка рендера (запись `.textContent`
  на отсутствующий элемент) маскируется под «бэкенд не отвечает».
- Незащищённые записи `$('id').textContent = ...` в `frontend/js/dashboard.js`
  (renderProfileSwitcher, loadDashboard, renderDashboardGrowth) и `switchTab`
  падали, если элемента нет, и роняли весь refresh.
- Фикс: добавлены null-safe хелперы `setText(id, value)` / `setHtml(id, value)`
  в core.js (по образцу `setValue`/`setChecked`); все записи текста/HTML в
  dashboard-пути и `switchTab` переведены на них + guard на `classList`/`style`.
- Проверено в браузере (Playwright): дашборд рендерится, все вкладки
  переключаются, `refreshAll` OK, 0 тостов/ошибок в консоли.

## Checkpoint (2026-06-14) — автопилот и мониторинг: один проход вместо цикла

**Запрос пользователя:** бот запускают на 10-20 минут, бесконечные циклы с
интервалом не нужны.
- `workers/media_autopilot.py` `media_loop_worker`: убран `while`-цикл и сон
  по интервалу → один проход (скачать→опубликовать) и поток завершается сам.
  Удалён неиспользуемый `import time`.
- `workers/monitor.py` `monitor_worker`: убран `while`-цикл и ожидание
  `check_interval_min` → одна проверка источников и стоп.
- Watchdog не трогал — `finally` ставит `is_monitoring=False` до смерти
  потока, ложного перезапуска нет.
- Работа постов сохраняется: один проход забивает отложку VK, дальше VK
  публикует сам, бот держать включённым не нужно.
- Поля «Интервал» убраны из UI автопилота (`frontend/index.html`: 4 блока,
  сетка `grid-3`→`grid-2`; `frontend/js/autopilot.js`: чтение/запись
  `apInterval-*`, фаза `sleeping`, `next_run`; `frontend/style.css`:
  `.ap-status-dot.sleeping`). Бэкенд: удалены `loop_interval_min` и
  `interval_min` из `loops_status` — понятие «интервал» убрано полностью.
- Тесты: **130 passed** (`pytest tests/ -q --ignore=tests/test_playwright_ui.py`),
  `node --check` по autopilot.js — OK.

## Checkpoint (2026-06-14 12:15) — стабилизация видео-логов

**Убраны warning/error из лога видео-воркера (запрос пользователя):**
- Корень: источники с внешними embed-видео (Coub/Vimeo) — yt-dlp падал
  (`KeyError('params')` / HTTP 401). Это недоступный контент, не баг.
- `workers/videos.py`: добавлен `_is_external_video()` — видео с
  `files.external` без `mp4_*` пропускаются до вызова yt-dlp (в обоих путях:
  `_download_videos_source` и `download_top_competitor_videos`).
- VK API 204 (нет доступа к видео источника) понижен с `warning` до `info`.
- `yt-dlp` обновлён до 2026.6.9 (requirements bump). Сам KeyError апстрим не
  чинит — фикс именно в отсечении внешних видео.
- Алерт «Низкий охват» удалён навсегда по просьбе пользователя: вырезан
  блок в `services/tracker.py` (run_check) и ключ `alert_low_views` из
  шаблона профиля в `config.py`. Сам трекинг охватов (`tracking.enabled`)
  работает. Остаточный ключ `alert_low_views` в существующих профилях
  config.json инертен (никто не читает).
- Тесты: 129 passed (1 пре-существующий фейл `test_phash_video.py` — env,
  падает и на baseline).

## Checkpoint (2026-06-14 12:00) — редизайн фронтенда + прогресс-бары автопилота

**План `docs/superpowers/plans/2026-06-13-design-overhaul-and-autopilot-progress.md`,
11/11 задач + 1 фикс, смержено в `main`:**
- Новая светлая терракотовая палитра (Anthropic-light) — CSS-токены
  (`--accent: #d97757`, `--bg: #faf8f6` и т.д.) применены на всех страницах
  (дашборд, каналы, настройки, библиотека, все каналы, логи, ниши), старые
  фиолетовые цвета заменены
- 4 карточки автопилота (Посты/Фото/Видео/Клипы) на дашборде — новый
  компонент `.ap-cycle*`: статус-точка (работает/спит/остановлен),
  статус-текст с фазой, прогресс-бар с заливкой/% /лейблом "X из Y"
- `_set_progress(media_type, *, phase, current, total, label='')` в
  `workers/media_autopilot.py` пишет прогресс в
  `app_state.media_loop_state[type]['progress']`; вызывается из
  `download.py`, `photos.py`, `publish.py`, `videos.py` на каждом шаге
  скачивания/публикации для всех 4 типов медиа. Сброс в idle (`total=0`) в
  начале каждого прохода **и при ошибке прохода** (фикс после финального
  review — иначе бар "застывал" с надписью "Скачивание" при статусе "ждёт")
- `frontend/js/autopilot.js`: `apRefreshLoops()` читает `st.progress` и
  обновляет `#apProgressFill/Label/Pct-{type}` + `#apStatusDot/Text-{type}`
  через новый `formatApStatus()`
- Все существующие id/обработчики (`apLoopBtn-*`, `apInterval-*` и т.д.)
  не тронуты — старый функционал кнопок/настроек работает как прежде
- Удалён мёртвый файл `frontend/_mockup_autopilot.html`
- **130 passed**, проверено в браузере (Playwright). Финальный code-review:
  APPROVED WITH MINOR NOTES (0 critical/high).

## Checkpoint (2026-06-14 11:45) — slot scheduler + media quality

**План `docs/superpowers/plans/2026-06-13-slot-scheduler-and-media-quality.md`,
16/16 задач:**
- `services/slot_scheduler.py`: единый резерв слотов публикации для постов/
  фото/видео/клипов — `reserve_slot()`/`record_slot()`, `min_gap` между
  любыми типами, дневные лимиты видео/клипов настраиваются через
  `videos_settings.daily_limit` / `clips_settings.daily_limit` в config.json
  (дефолты 1 и 2). Хранится в `app_state.scheduled_slots_file`. Подключён во
  все 3 publish-воркера — больше нет коллизий слотов и спама постов с
  интервалом 10-30 мин
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
- **126 passed**
