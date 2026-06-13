# Редизайн дизайн-системы + прогресс-бары циклов автопилота

**Дата:** 2026-06-13
**Статус:** approved

## Цель

1. Полный визуальный редизайн фронтенда (`frontend/`) на новую светлую терракотовую
   палитру (стиль Anthropic light) — затрагивает ВСЕ страницы/таб (Дашборд, Каналы,
   Настройки, Библиотека, Все каналы, Логи), а не только карточки автопилота.
2. На карточках 4 циклов автопилота (посты/фото/видео/клипы) — прогресс-бар,
   отражающий % обработки текущего прохода (1 обработанный элемент = 1/total %).

## Ограничения (не нарушать)

- Существующая HTML-структура, id элементов, `onclick`-обработчики и DOM-контракты,
  на которые ссылается `frontend/js/*.js` (особенно `autopilot.js`), должны остаться
  рабочими. Редизайн — это в первую очередь смена CSS-токенов и стилизации
  компонентов, НЕ удаление/переименование существующих элементов.
- Скрытый legacy-блок (`display:none`, id вида `gaCandidateCount`, `dashGaChannel` и т.п.
  в `index.html`) — не трогать.
- Без новых внешних зависимостей (веб-шрифтов и т.п.) — шрифт остаётся системным
  стеком (`-apple-system, 'Segoe UI', Roboto, sans-serif`), без подключения Inter.

## 1. Новая цветовая палитра (CSS-токены)

Заменить блок `:root` в `frontend/style.css` (строки 3-31):

```css
:root {
  --bg:            #faf8f6;
  --surface:       #ffffff;
  --sidebar-bg:    #211c18;
  --sidebar-hover: #2b251f;
  --sidebar-active:#352c24;
  --border:        #ece6e0;
  --border-dark:   #ddd4cb;
  --accent:        #d97757;
  --accent-hover:  #c2654a;
  --accent-light:  #fbe9e2;
  --text:          #1f1b18;
  --text-2:        #4a423b;
  --text-muted:    #8a7e74;
  --text-faint:    #b7aca1;
  --success:       #5a8a6b;
  --success-bg:    #e3f0e7;
  --warning:       #c08a3e;
  --warning-bg:    #faf0dc;
  --error:         #c1574a;
  --error-bg:      #fae6e2;
  --info:          #6c8cab;
  --info-bg:       #e7eef5;
  --radius:        10px;
  --radius-sm:     7px;
  --shadow:        0 1px 2px rgba(40,30,20,.04), 0 1px 3px rgba(40,30,20,.05);
  --shadow-md:     0 4px 10px rgba(40,30,20,.06), 0 2px 4px rgba(40,30,20,.05);
  --font:          -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
}
```

Поскольку большинство компонентов используют переменные, смена `:root` автоматически
перекрасит большую часть UI. Дополнительно нужно перевести на токены хардкод-цвета,
которые ссылались на старую фиолетовую палитру напрямую:

| Файл:строка | Текущее значение | Заменить на |
|---|---|---|
| `style.css:169` `.chart-bar.has-errors` | `background: #fca5a5` | `var(--error)` |
| `style.css:187` `.stat-card-errors.has-errors` | `border-color: #fca5a5; background: #fff5f5` | `border-color: var(--error); background: var(--error-bg)` |
| `style.css:423` `.form-input:focus` box-shadow | `rgba(124,58,237,.12)` | `rgba(217,119,87,.15)` (терракотовый accent) |
| `style.css:536` `.channel-card.active` box-shadow | `rgba(124,58,237,.15)` | `rgba(217,119,87,.18)` |
| `style.css:550-553` `@keyframes pulse` | `rgba(124,58,237,.5)` / `rgba(124,58,237,0)` | `rgba(217,119,87,.5)` / `rgba(217,119,87,0)` |
| `style.css:582` `.sg-btn:hover` | `rgba(124,58,237,.06)` | `rgba(217,119,87,.08)` |
| `style.css:629` `.color-option.selected` | `border-color: #111` | `border-color: var(--text)` |
| `style.css:684-685` `.allstats-row-active` | `rgba(124,58,237,0.07/0.12)` | `rgba(217,119,87,.07)` / `rgba(217,119,87,.12)` |
| `style.css:688` `.allstats-today` | `#34d399` | `var(--success)` |
| `style.css:689` `.allstats-error` | `#f87171` | `var(--error)` |
| `style.css:175` `.chart-bar:hover::after` tooltip bg | `#1a1a27` | `var(--sidebar-bg)` (новый тёмный тон `#211c18`) |
| `style.css:656,662,666` `.logo-drop-zone` fallback-значения | `var(--border, #334155)` / `var(--surface2, #0f172a)` / `var(--accent, #7c3aed)` | убрать устаревшие fallback-значения, оставить чистые `var(--border)`, `var(--bg)`, `var(--accent)` |
| `style.css:691` `.allstats-badge` fallback | `var(--accent, #7c3aed)` | `var(--accent)` |

`@keyframes slideIn/slideOut` (строки 623-624) — управляют `transform`/`opacity`,
цветовых изменений не требуют.

## 2. Редизайн по компонентам/страницам

Сайдбар (`.sidebar`, `.nav-item`, `.profile-switcher`, `.bot-status`) остаётся тёмным
(`--sidebar-bg`) для контраста с новым светлым фоном — токены уже покрывают это,
дополнительных правок кроме токенов не требуется.

Карточки (`.card`, `.stat-card`, `.channel-card`, модалки, тосты, таблица
`allstats-table`, логи) — токены `--surface`/`--border`/`--shadow` дают новый светлый
вид автоматически. Точечно проверить читаемость на новом фоне: `--shadow`/`--shadow-md`
уже пересчитаны под тёплый фон (используют `rgba(40,30,20,...)` вместо `rgba(0,0,0,...)`).

Кнопки/бейджи (`.btn-*`, `.badge-*`) — автоматически подхватывают новый `--accent`
(терракот) и `--success/--warning/--error/--info` без структурных изменений.

## 3. Карточки циклов автопилота — редизайн `.ap-cycle`

В `index.html`, секция `#dashboardGrowthCard` → блок `style="padding:12px 16px 8px"` →
`.ap-grid` (2x2, было `display:grid;grid-template-columns:1fr 1fr;gap:8px` через inline
style — заменить на класс `.ap-grid` с `@media max-width:700px` → 1 колонка).

Каждая из 4 карточек (`#apCycleSettings-{type}`) получает новую структуру
(на основе утверждённого `_mockup_autopilot.html`):

```html
<div class="ap-cycle" id="apCycleSettings-posts">
  <div class="ap-cycle-head">
    <div class="ap-cycle-icon">[SVG-иконка типа медиа]</div>
    <div class="ap-cycle-title">Посты</div>
    <span class="ap-status-dot"></span>
  </div>
  <div class="ap-cycle-status-row" id="apStatusText-posts">—</div>
  <div class="ap-progress">
    <div class="ap-progress-track">
      <div class="ap-progress-fill" id="apProgressFill-posts" style="width:0%"></div>
    </div>
    <div class="ap-progress-meta">
      <span id="apProgressLabel-posts">—</span>
      <span id="apProgressPct-posts">0%</span>
    </div>
  </div>
  <div class="ap-cycle-settings grid-3">
    <!-- существующие inputs apInterval/apDownload/apPublish-posts без изменений id -->
  </div>
  <div class="ap-cycle-actions">
    <!-- существующие кнопки apLoopBtn-posts / apSave-posts без изменений id/onclick -->
  </div>
</div>
```

- Иконки: простые inline SVG (документ/фото/видео/клип), 18-20px, цвет `var(--accent)`
  в кружке `var(--accent-light)`.
- `.ap-status-dot` — кружок 8px, `var(--success)` при `running=true` с pulse-анимацией
  (переиспользовать `@keyframes pulse`, перекрашенный на терракот/успех), серый
  `var(--text-faint)` при `running=false`.
- Существующие `apInterval/apDownload/apPublish-{type}` инпуты и кнопки
  `apLoopBtn-{type}`/`apSave-{type}` — id, onclick и текстовые состояния кнопок НЕ
  меняются, только оборачиваются в новую обёртку с обновлёнными CSS-классами.
- `apStatusText-{type}` и `apProgress*-{type}` — НОВЫЕ элементы, заполняются через
  `autopilot.js`.

## 4. Backend: прогресс-трекинг циклов (Approach A)

Новый helper в `workers/media_autopilot.py`:

```python
def _set_progress(media_type: str, *, phase: str, current: int, total: int, label: str = '') -> None:
    """Обновить прогресс текущего прохода цикла.

    phase: 'download' | 'publish' | 'idle'
    total=0 — фронт скрывает числа/проценты, показывает '—'.
    """
    _set_state(media_type, progress={
        'phase': phase,
        'current': current,
        'total': total,
        'label': label,
    })
```

Вызовы добавляются:

- **`_cycle_posts`** (`workers/media_autopilot.py`) — перед вызовом
  `download_all_worker()`/`publish_worker()` сбрасывает `progress` с известным `total`
  (берётся из настроек цикла `apDownload-posts`/`apPublish-posts`).
  Внутри `workers/download.py` (`download_all_worker`, цикл по `_download_posts_source`)
  и `workers/publish.py` (`publish_worker`, цикл по очереди) — на каждой итерации,
  где уже инкрементируется `downloaded`/`published`/`index`, добавить
  `_set_progress('posts', phase=..., current=..., total=..., label=...)`.
- **`_cycle_photos`** — аналогично для `download_photos_worker`/`publish_photos_worker`
  в `workers/photos.py` (сейчас прогресс-трекинга там нет — добавляется с нуля по
  аналогии с posts).
- **`_cycle_videos`** / **`_cycle_clips`** — аналогично в `workers/videos.py` /
  `workers/clips.py`.

Когда цикл уходит в `sleeping` после прохода — `progress` НЕ сбрасывается, остаётся
последним значением (100% или сколько успели обработать) — это даёт "замороженный
серый прогресс-бар" для sleeping-состояния. При следующем старте прохода helper
перезапишет `progress` на новый `total`.

`total=0` — фронт показывает "—" вместо процентов (как в mockup для videos/stopped).

## 5. Поток данных к фронту

Без новых endpoint'ов. `loops_status()` в `workers/media_autopilot.py` уже спредит
`app_state.media_loop_state[media_type]` (включая новое поле `progress`) в ответ
`/autopilot/loops`.

В `frontend/js/autopilot.js`, в `apRefreshLoops()` (или аналогичной функции, читающей
`/autopilot/loops`), после существующей обработки `for (const [type, st] of
Object.entries(data.loops))` добавить:

```js
const progress = st.progress || {};
const total = progress.total || 0;
const current = progress.current || 0;
const pct = total > 0 ? Math.round(current / total * 100) : 0;

const fill = document.getElementById(`apProgressFill-${type}`);
const label = document.getElementById(`apProgressLabel-${type}`);
const pctEl = document.getElementById(`apProgressPct-${type}`);
const statusEl = document.getElementById(`apStatusText-${type}`);

if (fill) fill.style.width = total > 0 ? `${pct}%` : '0%';
if (label) label.textContent = total > 0 ? `${current} из ${total}` : '—';
if (pctEl) pctEl.textContent = total > 0 ? `${pct}%` : '—';
if (statusEl) statusEl.textContent = formatApStatus(type, st);
```

`formatApStatus(type, st)` — новая небольшая функция, строящая строку статуса
("Скачивание · источник 3 из 7", "Ждёт следующего запуска · 14:30", "Остановлен" и
т.п.) на основе `st.running`, `st.phase` (общий, не из progress), `progress.phase`,
`progress.label`, `st.next_run`.

## 6. Тестирование

- `tests/test_media_autopilot.py` — unit-тест на `_set_progress()`: проверяет, что
  `media_loop_state[media_type]['progress']` корректно обновляется и что
  `loops_status()` отдаёт его наружу (включая случай `total=0`).
- Для каждого из воркеров (`download.py`, `publish.py`, `photos.py`, `videos.py`,
  `clips.py`) — расширить существующие тесты циклов проверкой, что `progress.current`
  растёт по мере обработки очереди и доходит до `progress.total` к концу прохода.
- UI: ручная проверка на живом дашборде — прогресс-бары двигаются от 0% к 100% за
  проход, после завершения остаются на 100% (серые) до следующего старта.
- Полный набор тестов должен оставаться зелёным:
  `pytest tests/ -q --ignore=tests/test_playwright_ui.py`.

## Вне скоупа

- Подключение веб-шрифтов (Inter и т.п.) — остаётся системный font-stack.
- Изменение HTML-структуры/контрактов JS за пределами добавления новых
  `apStatusText-{type}`/`apProgress*-{type}` элементов и переноса существующих
  элементов в новую обёртку `.ap-cycle`.
- Рефакторинг `app_state.download_progress` (Approach B) — не требуется, т.к.
  Approach A полностью решает задачу аддитивно.
- Удаление временного `_mockup_autopilot.html` — решить после завершения вёрстки
  (можно оставить как референс или удалить отдельным коммитом).
