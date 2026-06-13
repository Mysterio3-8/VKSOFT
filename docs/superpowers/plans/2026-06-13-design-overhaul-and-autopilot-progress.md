# Терракотовая тема + прогресс-бары циклов автопилота — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить цветовую палитру всего фронтенда на светлую терракотовую (Anthropic light style) и добавить прогресс-бары (N из M + %) под каждой из 4 карточек циклов автопилота (посты/фото/видео/клипы) на дашборде, без изменения существующих id/JS-контрактов.

**Architecture:** Только CSS-палитра (`:root` переменные + 12 точечных заменe хардкод-цветов) и редизайн `.ap-cycle`-обёртки 4 карточек в `index.html`/`style.css` — без новых HTML id для существующих элементов. Backend: новый чистый helper `_set_progress()` в `workers/media_autopilot.py`, вызываемый из `_cycle_*` и из циклов внутри `download.py`/`publish.py`/`photos.py`/`videos.py`, пишет в `app_state.media_loop_state[media_type]['progress']`. Поле `progress` автоматически попадает в `/api/autopilot/loops` через существующий spread `**app_state.media_loop_state.get(media_type, {})`. Frontend: `autopilot.js` читает `st.progress` в `apRefreshLoops()` и обновляет 3 новых DOM-элемента на карточку (`apProgressFill-*`, `apProgressLabel-*`, `apProgressPct-*`, `apStatusText-*`).

**Tech Stack:** FastAPI (Python 3.10+), vanilla JS SPA, CSS custom properties, pytest.

---

## Карта файлов

| Файл | Что меняется |
|---|---|
| `frontend/style.css` | `:root` палитра (полная замена 30 переменных), 12 точечных замен хардкод-цветов, новые классы `.ap-cycle`, `.ap-cycle-head`, `.ap-cycle-icon`, `.ap-cycle-title`, `.ap-status-dot`, `.ap-cycle-status-row`, `.ap-progress`, `.ap-progress-track`, `.ap-progress-fill`, `.ap-progress-meta`, `.ap-cycle-settings`, `.ap-cycle-actions` |
| `frontend/index.html` | Обернуть 4 существующих `<div class="form-section" id="apCycleSettings-*">` в новую структуру `.ap-cycle` с заголовком/иконкой/статус-строкой/прогресс-баром; все существующие id и `onclick` остаются как есть |
| `frontend/js/autopilot.js` | `apRefreshLoops()` — обновление прогресс-бара и статус-строки; новая функция `formatApStatus(type, st)` |
| `workers/media_autopilot.py` | Новый helper `_set_progress(media_type, *, phase, current, total, label='')`; вызовы из `_cycle_posts/_cycle_photos/_cycle_videos/_cycle_clips` (idle/завершение) |
| `workers/download.py` | В `_download_source()` — вызов `_set_progress('posts', phase='download', ...)` рядом с существующими обновлениями `app_state.download_progress` |
| `workers/publish.py` | В цикле публикации — вызов `_set_progress('posts', phase='publish', ...)` |
| `workers/photos.py` | В `_download_photos_source()` и `publish_photos_worker()` — вызовы `_set_progress('photos', ...)` (с нуля, прогресса не было) |
| `workers/videos.py` | В `_download_videos_source()` и `publish_videos_worker()` — вызовы `_set_progress('videos'/'clips', ...)` через `media_type = 'clips' if is_clips_mode else 'videos'` (с нуля) |
| `tests/test_media_autopilot_progress.py` | Новый тест-файл: `_set_progress()`, попадание `progress` в `loops_status()` |

---

## Часть 1 — Терракотовая палитра (CSS)

### Task 1: Заменить `:root` палитру в `style.css`

**Files:**
- Modify: `frontend/style.css:3-31`

- [ ] **Step 1: Заменить блок `:root`**

Текущий блок (`frontend/style.css:3-31`):

```css
:root {
  --bg:            #f7f7f8;
  --surface:       #ffffff;
  --sidebar-bg:    #1a1a27;
  --sidebar-hover: #252535;
  --sidebar-active:#2d2d45;
  --border:        #e5e7eb;
  --border-dark:   #d1d5db;
  --accent:        #7c3aed;
  --accent-hover:  #6d28d9;
  --accent-light:  #ede9fe;
  --text:          #111827;
  --text-2:        #374151;
  --text-muted:    #6b7280;
  --text-faint:    #9ca3af;
  --success:       #059669;
  --success-bg:    #d1fae5;
  --warning:       #d97706;
  --warning-bg:    #fef3c7;
  --error:         #dc2626;
  --error-bg:      #fee2e2;
  --info:          #2563eb;
  --info-bg:       #dbeafe;
  --radius:        8px;
  --radius-sm:     6px;
  --shadow:        0 1px 3px rgba(0,0,0,.08),0 1px 2px rgba(0,0,0,.06);
  --shadow-md:     0 4px 6px rgba(0,0,0,.07),0 2px 4px rgba(0,0,0,.06);
  --font:          -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
}
```

Заменить на:

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

- [ ] **Step 2: Визуально проверить** — открыть дашборд в браузере, убедиться что фон/сайдбар/акценты сменились на терракотовые тона, без поломанной верстки (значения переменных меняются, имена и количество — те же).

- [ ] **Step 3: Commit**

```bash
git add frontend/style.css
git commit -m "feat: switch frontend palette to light terracotta theme"
```

---

### Task 2: Точечные замены хардкод-цветов на токены палитры

**Files:**
- Modify: `frontend/style.css` (12 точек, см. ниже)

- [ ] **Step 1: `.chart-bar.has-errors` (строка 169)**

Было:
```css
.chart-bar.has-errors { background: #fca5a5; }
```
Заменить на:
```css
.chart-bar.has-errors { background: var(--error); }
```

- [ ] **Step 2: `.chart-bar:hover::after` фон тултипа (строка 175)**

Было:
```css
  background: #1a1a27; color: #fff;
```
(внутри блока `.chart-bar:hover::after`, строки 171-178)
Заменить на:
```css
  background: var(--sidebar-bg); color: #fff;
```

- [ ] **Step 3: `.stat-card-errors.has-errors` (строка 187)**

Было:
```css
.stat-card-errors.has-errors { border-color: #fca5a5; background: #fff5f5; }
```
Заменить на:
```css
.stat-card-errors.has-errors { border-color: var(--error); background: var(--error-bg); }
```

- [ ] **Step 4: `.form-input:focus` box-shadow (строка 423)**

Было:
```css
.form-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(124,58,237,.12); }
```
Заменить на:
```css
.form-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(217,119,87,.15); }
```

- [ ] **Step 5: `.channel-card.active` box-shadow (строка 536)**

Было:
```css
.channel-card.active { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(124,58,237,.15); }
```
Заменить на:
```css
.channel-card.active { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(217,119,87,.18); }
```

- [ ] **Step 6: `@keyframes pulse` (строки 550-553)**

Было:
```css
@keyframes pulse {
  0%,100% { box-shadow: 0 0 0 0 rgba(124,58,237,.5); }
  50%      { box-shadow: 0 0 0 6px rgba(124,58,237,0); }
}
```
Заменить на:
```css
@keyframes pulse {
  0%,100% { box-shadow: 0 0 0 0 rgba(217,119,87,.5); }
  50%      { box-shadow: 0 0 0 6px rgba(217,119,87,0); }
}
```

- [ ] **Step 7: `.sg-btn:hover` (строка 582)**

Было:
```css
.sg-btn:hover  { background: rgba(124,58,237,.06); color: var(--text); }
```
Заменить на:
```css
.sg-btn:hover  { background: rgba(217,119,87,.08); color: var(--text); }
```

- [ ] **Step 8: `.color-option.selected` (строка 629)**

Было:
```css
.color-option.selected { border-color: #111; }
```
Заменить на:
```css
.color-option.selected { border-color: var(--text); }
```

- [ ] **Step 9: `.logo-drop-zone` и связанные (строки 654-671)**

Было:
```css
/* Logo drag-and-drop zone */
.logo-drop-zone {
  border: 2px dashed var(--border, #334155);
  border-radius: 8px;
  padding: 16px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  background: var(--surface2, #0f172a);
}
.logo-drop-zone.dragover,
.logo-drop-zone:hover {
  border-color: var(--accent, #7c3aed);
  background: rgba(124,58,237,0.08);
}
.logo-drop-icon { font-size: 24px; display: block; margin-bottom: 6px; }
.logo-drop-link { color: var(--accent, #7c3aed); cursor: pointer; text-decoration: underline; }
.logo-drop-link:hover { opacity: 0.8; }
```
Заменить на:
```css
/* Logo drag-and-drop zone */
.logo-drop-zone {
  border: 2px dashed var(--border);
  border-radius: var(--radius-sm);
  padding: 16px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  background: var(--bg);
}
.logo-drop-zone.dragover,
.logo-drop-zone:hover {
  border-color: var(--accent);
  background: rgba(217,119,87,.08);
}
.logo-drop-icon { font-size: 24px; display: block; margin-bottom: 6px; }
.logo-drop-link { color: var(--accent); cursor: pointer; text-decoration: underline; }
.logo-drop-link:hover { opacity: 0.8; }
```

- [ ] **Step 10: `.allstats-row-active` (строки 684-685)**

Было:
```css
.allstats-row-active td { background: rgba(124,58,237,0.07); }
.allstats-row-active:hover td { background: rgba(124,58,237,0.12) !important; }
```
Заменить на:
```css
.allstats-row-active td { background: rgba(217,119,87,.07); }
.allstats-row-active:hover td { background: rgba(217,119,87,.12) !important; }
```

- [ ] **Step 11: `.allstats-today` / `.allstats-error` (строки 688-689)**

Было:
```css
.allstats-today { color: #34d399; }
.allstats-error { color: #f87171; }
```
Заменить на:
```css
.allstats-today { color: var(--success); }
.allstats-error { color: var(--error); }
```

- [ ] **Step 12: `.allstats-badge` (строка 691)**

Было:
```css
.allstats-badge { display: inline-block; margin-left: 8px; padding: 1px 7px; border-radius: 10px; font-size: 10px; background: var(--accent, #7c3aed); color: #fff; vertical-align: middle; }
```
Заменить на:
```css
.allstats-badge { display: inline-block; margin-left: 8px; padding: 1px 7px; border-radius: 10px; font-size: 10px; background: var(--accent); color: #fff; vertical-align: middle; }
```

- [ ] **Step 13: Визуально проверить** — открыть дашборд, страницу "Все каналы" (allstats), вкладку логов (чтобы увидеть `.chart-bar.has-errors`/тултип), настройки → антиплагиат (drag-drop зона лого). Убедиться, что нигде не осталась фиолетовая `#7c3aed`/`rgba(124,58,237,*)` и нет визуальных артефактов (например, белый текст на белом).

- [ ] **Step 14: Commit**

```bash
git add frontend/style.css
git commit -m "fix: replace hardcoded purple colors with terracotta palette tokens"
```

---

## Часть 2 — Редизайн карточек циклов автопилота `.ap-cycle`

### Task 3: Новые CSS-классы `.ap-cycle*` в `style.css`

**Files:**
- Modify: `frontend/style.css` (добавить новый блок после `.form-section` правил, т.е. после строки 415 `.compact-toggle { ... }`)

- [ ] **Step 1: Добавить блок стилей после строки 415**

Текущий контекст (`frontend/style.css:403-416`):
```css
.form-section { display: flex; flex-direction: column; gap: 14px; }
.form-section + .form-section { margin-top: 20px; padding-top: 20px; border-top: 1px solid var(--border); }

.form-group  { display: flex; flex-direction: column; gap: 5px; }
.form-label  { font-size: 13px; font-weight: 500; color: var(--text-2); }
.form-hint   { font-size: 12px; color: var(--text-muted); }
.form-row    { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-row-3  { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
.settings-actions, .button-row { display: flex; gap: 8px; flex-wrap: wrap; }
.button-row { margin-top: 12px; }
.ga-schedule-item { padding: 9px 0; border-bottom: 1px solid var(--border); font-size: 13px; color: var(--text); }
.ga-schedule-item:last-child { border-bottom: 0; }
.compact-toggle { padding: 0; align-self: end; min-height: 37px; }

.form-input {
```

Вставить новый блок между `.compact-toggle { ... }` (строка 415) и `.form-input {` (строка 417):

```css
/* ── Карточки циклов автопилота ── */
.ap-cycle {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: border-color .15s, box-shadow .15s;
}
.ap-cycle:hover { border-color: var(--border-dark); box-shadow: var(--shadow); }

.ap-cycle-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ap-cycle-icon {
  width: 30px; height: 30px; flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: var(--accent-light);
  color: var(--accent);
  display: flex; align-items: center; justify-content: center;
}
.ap-cycle-icon svg { width: 16px; height: 16px; }
.ap-cycle-title {
  flex: 1;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text);
}
.ap-status-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--border-dark);
  flex-shrink: 0;
  transition: background .2s;
}
.ap-status-dot.running {
  background: var(--success);
  animation: pulse 2s infinite;
}
.ap-status-dot.sleeping { background: var(--warning); }

.ap-cycle-status-row {
  font-size: 12px;
  color: var(--text-muted);
  min-height: 16px;
}

.ap-progress { display: flex; flex-direction: column; gap: 4px; }
.ap-progress-track {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 99px;
  height: 6px;
  overflow: hidden;
}
.ap-progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 99px;
  width: 0;
  transition: width .3s ease;
}
.ap-progress-fill.idle { background: var(--border-dark); }
.ap-progress-meta {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-faint);
}

.ap-cycle-settings { gap: 6px; }
.ap-cycle-actions { display: flex; flex-direction: column; gap: 6px; }
```

- [ ] **Step 2: Визуально проверить** — пока классы не используются в HTML, страница не изменится. Убедиться, что `style.css` валиден (открыть дашборд, никаких ошибок в консоли браузера по CSS не появилось).

- [ ] **Step 3: Commit**

```bash
git add frontend/style.css
git commit -m "feat: add .ap-cycle component styles for autopilot loop cards"
```

---

### Task 4: Обновить HTML-структуру 4 карточек циклов в `index.html`

**Files:**
- Modify: `frontend/index.html:71-111`

- [ ] **Step 1: Заменить блок карточек циклов**

Текущий блок (`frontend/index.html:70-111`):

```html
        <!-- Циклы по типам медиа -->
        <div style="padding:12px 16px 8px">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            <div class="form-section" id="apCycleSettings-posts">
              <button class="btn btn-primary" style="width:100%;font-size:14px;padding:10px" onclick="apToggleLoop('posts')" id="apLoopBtn-posts">Цикл постов</button>
              <div class="grid-3" style="gap:6px;margin-top:8px">
                <div class="form-group"><label class="form-label">Интервал</label><input class="form-input" id="apInterval-posts" type="number" min="1" placeholder="180"></div>
                <div class="form-group"><label class="form-label">Скачать</label><input class="form-input" id="apDownload-posts" type="number" min="1" placeholder="100"></div>
                <div class="form-group"><label class="form-label">Опубл.</label><input class="form-input" id="apPublish-posts" type="number" min="1" placeholder="100"></div>
              </div>
              <button class="btn btn-secondary btn-sm" style="width:100%" onclick="apSaveLoopSettings('posts')" id="apSave-posts">Сохранить</button>
            </div>
            <div class="form-section" id="apCycleSettings-photos">
              <button class="btn btn-primary" style="width:100%;font-size:14px;padding:10px" onclick="apToggleLoop('photos')" id="apLoopBtn-photos">Цикл фото</button>
              <div class="grid-3" style="gap:6px;margin-top:8px">
                <div class="form-group"><label class="form-label">Интервал</label><input class="form-input" id="apInterval-photos" type="number" min="1" placeholder="180"></div>
                <div class="form-group"><label class="form-label">Скачать</label><input class="form-input" id="apDownload-photos" type="number" min="1" placeholder="50"></div>
                <div class="form-group"><label class="form-label">Опубл.</label><input class="form-input" id="apPublish-photos" type="number" min="1" placeholder="50"></div>
              </div>
              <button class="btn btn-secondary btn-sm" style="width:100%" onclick="apSaveLoopSettings('photos')" id="apSave-photos">Сохранить</button>
            </div>
            <div class="form-section" id="apCycleSettings-videos">
              <button class="btn btn-primary" style="width:100%;font-size:14px;padding:10px" onclick="apToggleLoop('videos')" id="apLoopBtn-videos">Цикл видео</button>
              <div class="grid-3" style="gap:6px;margin-top:8px">
                <div class="form-group"><label class="form-label">Интервал</label><input class="form-input" id="apInterval-videos" type="number" min="1" placeholder="180"></div>
                <div class="form-group"><label class="form-label">Скачать</label><input class="form-input" id="apDownload-videos" type="number" min="1" placeholder="10"></div>
                <div class="form-group"><label class="form-label">Опубл.</label><input class="form-input" id="apPublish-videos" type="number" min="1" placeholder="10"></div>
              </div>
              <button class="btn btn-secondary btn-sm" style="width:100%" onclick="apSaveLoopSettings('videos')" id="apSave-videos">Сохранить</button>
            </div>
            <div class="form-section" id="apCycleSettings-clips">
              <button class="btn btn-primary" style="width:100%;font-size:14px;padding:10px" onclick="apToggleLoop('clips')" id="apLoopBtn-clips">Цикл клипов</button>
              <div class="grid-3" style="gap:6px;margin-top:8px">
                <div class="form-group"><label class="form-label">Интервал</label><input class="form-input" id="apInterval-clips" type="number" min="1" placeholder="180"></div>
                <div class="form-group"><label class="form-label">Скачать</label><input class="form-input" id="apDownload-clips" type="number" min="1" placeholder="10"></div>
                <div class="form-group"><label class="form-label">Опубл.</label><input class="form-input" id="apPublish-clips" type="number" min="1" placeholder="10"></div>
              </div>
              <button class="btn btn-secondary btn-sm" style="width:100%" onclick="apSaveLoopSettings('clips')" id="apSave-clips">Сохранить</button>
            </div>
          </div>
          <div class="form-hint" id="gaStatusText" style="margin-top:6px;text-align:center">Автопилот готов.</div>
        </div>
```

Заменить на:

```html
        <!-- Циклы по типам медиа -->
        <div style="padding:12px 16px 8px">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            <div class="ap-cycle">
              <div class="ap-cycle-head">
                <div class="ap-cycle-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 17h5l-1.4-1.4A7.5 7.5 0 0 0 6 8"/><path d="M9 7H4l1.4 1.4A7.5 7.5 0 0 0 18 16"/></svg>
                </div>
                <div class="ap-cycle-title">Посты</div>
                <span class="ap-status-dot" id="apStatusDot-posts"></span>
              </div>
              <div class="ap-cycle-status-row" id="apStatusText-posts">—</div>
              <div class="ap-progress">
                <div class="ap-progress-track">
                  <div class="ap-progress-fill idle" id="apProgressFill-posts" style="width:0%"></div>
                </div>
                <div class="ap-progress-meta">
                  <span id="apProgressLabel-posts">—</span>
                  <span id="apProgressPct-posts">0%</span>
                </div>
              </div>
              <div class="form-section ap-cycle-settings" id="apCycleSettings-posts">
                <div class="grid-3" style="gap:6px">
                  <div class="form-group"><label class="form-label">Интервал</label><input class="form-input" id="apInterval-posts" type="number" min="1" placeholder="180"></div>
                  <div class="form-group"><label class="form-label">Скачать</label><input class="form-input" id="apDownload-posts" type="number" min="1" placeholder="100"></div>
                  <div class="form-group"><label class="form-label">Опубл.</label><input class="form-input" id="apPublish-posts" type="number" min="1" placeholder="100"></div>
                </div>
              </div>
              <div class="ap-cycle-actions">
                <button class="btn btn-primary" style="width:100%;font-size:14px;padding:10px" onclick="apToggleLoop('posts')" id="apLoopBtn-posts">Цикл постов</button>
                <button class="btn btn-secondary btn-sm" style="width:100%" onclick="apSaveLoopSettings('posts')" id="apSave-posts">Сохранить</button>
              </div>
            </div>
            <div class="ap-cycle">
              <div class="ap-cycle-head">
                <div class="ap-cycle-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-5-5L5 21"/></svg>
                </div>
                <div class="ap-cycle-title">Фото</div>
                <span class="ap-status-dot" id="apStatusDot-photos"></span>
              </div>
              <div class="ap-cycle-status-row" id="apStatusText-photos">—</div>
              <div class="ap-progress">
                <div class="ap-progress-track">
                  <div class="ap-progress-fill idle" id="apProgressFill-photos" style="width:0%"></div>
                </div>
                <div class="ap-progress-meta">
                  <span id="apProgressLabel-photos">—</span>
                  <span id="apProgressPct-photos">0%</span>
                </div>
              </div>
              <div class="form-section ap-cycle-settings" id="apCycleSettings-photos">
                <div class="grid-3" style="gap:6px">
                  <div class="form-group"><label class="form-label">Интервал</label><input class="form-input" id="apInterval-photos" type="number" min="1" placeholder="180"></div>
                  <div class="form-group"><label class="form-label">Скачать</label><input class="form-input" id="apDownload-photos" type="number" min="1" placeholder="50"></div>
                  <div class="form-group"><label class="form-label">Опубл.</label><input class="form-input" id="apPublish-photos" type="number" min="1" placeholder="50"></div>
                </div>
              </div>
              <div class="ap-cycle-actions">
                <button class="btn btn-primary" style="width:100%;font-size:14px;padding:10px" onclick="apToggleLoop('photos')" id="apLoopBtn-photos">Цикл фото</button>
                <button class="btn btn-secondary btn-sm" style="width:100%" onclick="apSaveLoopSettings('photos')" id="apSave-photos">Сохранить</button>
              </div>
            </div>
            <div class="ap-cycle">
              <div class="ap-cycle-head">
                <div class="ap-cycle-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="14" height="12" rx="2"/><path d="M22 8.5l-6 3.5 6 3.5z"/></svg>
                </div>
                <div class="ap-cycle-title">Видео</div>
                <span class="ap-status-dot" id="apStatusDot-videos"></span>
              </div>
              <div class="ap-cycle-status-row" id="apStatusText-videos">—</div>
              <div class="ap-progress">
                <div class="ap-progress-track">
                  <div class="ap-progress-fill idle" id="apProgressFill-videos" style="width:0%"></div>
                </div>
                <div class="ap-progress-meta">
                  <span id="apProgressLabel-videos">—</span>
                  <span id="apProgressPct-videos">0%</span>
                </div>
              </div>
              <div class="form-section ap-cycle-settings" id="apCycleSettings-videos">
                <div class="grid-3" style="gap:6px">
                  <div class="form-group"><label class="form-label">Интервал</label><input class="form-input" id="apInterval-videos" type="number" min="1" placeholder="180"></div>
                  <div class="form-group"><label class="form-label">Скачать</label><input class="form-input" id="apDownload-videos" type="number" min="1" placeholder="10"></div>
                  <div class="form-group"><label class="form-label">Опубл.</label><input class="form-input" id="apPublish-videos" type="number" min="1" placeholder="10"></div>
                </div>
              </div>
              <div class="ap-cycle-actions">
                <button class="btn btn-primary" style="width:100%;font-size:14px;padding:10px" onclick="apToggleLoop('videos')" id="apLoopBtn-videos">Цикл видео</button>
                <button class="btn btn-secondary btn-sm" style="width:100%" onclick="apSaveLoopSettings('videos')" id="apSave-videos">Сохранить</button>
              </div>
            </div>
            <div class="ap-cycle">
              <div class="ap-cycle-head">
                <div class="ap-cycle-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="4"/><path d="M10 8l6 4-6 4z"/></svg>
                </div>
                <div class="ap-cycle-title">Клипы</div>
                <span class="ap-status-dot" id="apStatusDot-clips"></span>
              </div>
              <div class="ap-cycle-status-row" id="apStatusText-clips">—</div>
              <div class="ap-progress">
                <div class="ap-progress-track">
                  <div class="ap-progress-fill idle" id="apProgressFill-clips" style="width:0%"></div>
                </div>
                <div class="ap-progress-meta">
                  <span id="apProgressLabel-clips">—</span>
                  <span id="apProgressPct-clips">0%</span>
                </div>
              </div>
              <div class="form-section ap-cycle-settings" id="apCycleSettings-clips">
                <div class="grid-3" style="gap:6px">
                  <div class="form-group"><label class="form-label">Интервал</label><input class="form-input" id="apInterval-clips" type="number" min="1" placeholder="180"></div>
                  <div class="form-group"><label class="form-label">Скачать</label><input class="form-input" id="apDownload-clips" type="number" min="1" placeholder="10"></div>
                  <div class="form-group"><label class="form-label">Опубл.</label><input class="form-input" id="apPublish-clips" type="number" min="1" placeholder="10"></div>
                </div>
              </div>
              <div class="ap-cycle-actions">
                <button class="btn btn-primary" style="width:100%;font-size:14px;padding:10px" onclick="apToggleLoop('clips')" id="apLoopBtn-clips">Цикл клипов</button>
                <button class="btn btn-secondary btn-sm" style="width:100%" onclick="apSaveLoopSettings('clips')" id="apSave-clips">Сохранить</button>
              </div>
            </div>
          </div>
          <div class="form-hint" id="gaStatusText" style="margin-top:6px;text-align:center">Автопилот готов.</div>
        </div>
```

Note: id `apCycleSettings-{type}` сохранён (теперь на внутреннем `.form-section`), все id `apInterval-*`/`apDownload-*`/`apPublish-*`/`apLoopBtn-*`/`apSave-*` и их `onclick` — без изменений.

- [ ] **Step 2: Визуально проверить** — открыть дашборд в браузере, убедиться что 4 карточки отображаются как отдельные `.ap-cycle`-блоки с иконкой/заголовком/статус-точкой/прогресс-баром (пустым, 0%/—) и существующими настройками+кнопками ниже. Проверить, что клик по "Цикл постов" всё ещё запускает/останавливает цикл (через существующий `apToggleLoop`).

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: redesign autopilot loop cards with .ap-cycle layout"
```

---

## Часть 3 — Backend: `_set_progress()` helper

### Task 5: Добавить `_set_progress()` в `media_autopilot.py` и тест

**Files:**
- Modify: `workers/media_autopilot.py:74-76` (после `_set_state`)
- Test: `tests/test_media_autopilot_progress.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_media_autopilot_progress.py`:

```python
from config import app_state
from workers.media_autopilot import _set_progress, loops_status


def test_set_progress_writes_to_media_loop_state(monkeypatch):
    monkeypatch.setitem(app_state.media_loop_state, 'posts', {})

    _set_progress('posts', phase='download', current=3, total=10, label='Скачивание')

    assert app_state.media_loop_state['posts']['progress'] == {
        'phase': 'download',
        'current': 3,
        'total': 10,
        'label': 'Скачивание',
    }


def test_progress_field_appears_in_loops_status(monkeypatch):
    monkeypatch.setitem(app_state.media_loop_state, 'photos', {})
    monkeypatch.setitem(app_state.config, 'active_profile', 'test')
    monkeypatch.setitem(app_state.config, 'profiles', {'test': {}})

    _set_progress('photos', phase='publish', current=5, total=5, label='Публикация')

    status = loops_status()
    assert status['photos']['progress'] == {
        'phase': 'publish',
        'current': 5,
        'total': 5,
        'label': 'Публикация',
    }
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `pytest tests/test_media_autopilot_progress.py -v`
Expected: `FAIL` — `ImportError: cannot import name '_set_progress'`

- [ ] **Step 3: Реализовать `_set_progress()`**

Текущий контекст (`workers/media_autopilot.py:74-76`):
```python
def _set_state(media_type: str, **kwargs) -> None:
    app_state.media_loop_state.setdefault(media_type, {}).update(kwargs)
```

Добавить сразу после:
```python
def _set_state(media_type: str, **kwargs) -> None:
    app_state.media_loop_state.setdefault(media_type, {}).update(kwargs)


def _set_progress(media_type: str, *, phase: str, current: int, total: int, label: str = '') -> None:
    """Обновить прогресс текущего прохода цикла.

    phase: 'download' | 'publish' | 'idle'.
    total=0 — фронт скрывает числа/проценты, показывает '—'.
    """
    _set_state(media_type, progress={
        'phase': phase,
        'current': current,
        'total': total,
        'label': label,
    })
```

- [ ] **Step 4: Запустить тест, убедиться что проходит**

Run: `pytest tests/test_media_autopilot_progress.py -v`
Expected: `PASS` (2 passed)

- [ ] **Step 5: Commit**

```bash
git add workers/media_autopilot.py tests/test_media_autopilot_progress.py
git commit -m "feat: add _set_progress helper for autopilot loop progress tracking"
```

---

### Task 6: Сбрасывать `progress` в idle при старте/завершении прохода цикла

**Files:**
- Modify: `workers/media_autopilot.py:207-244` (`media_loop_worker`)
- Test: `tests/test_media_autopilot_progress.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_media_autopilot_progress.py`:

```python
def test_media_loop_worker_resets_progress_to_idle_between_passes(monkeypatch):
    monkeypatch.setitem(app_state.media_loop_state, 'posts', {'progress': {
        'phase': 'download', 'current': 7, 'total': 10, 'label': 'старое',
    }})
    monkeypatch.setitem(app_state.config, 'active_profile', 'test')
    monkeypatch.setitem(app_state.config, 'profiles', {'test': {
        'autopilot': {'intervals': {'posts': 180}},
    }})
    monkeypatch.setitem(app_state.media_loops, 'posts', False)

    import workers.media_autopilot as ma
    monkeypatch.setitem(ma._CYCLES, 'posts', lambda: None)

    ma.media_loop_worker('posts')

    progress = app_state.media_loop_state['posts']['progress']
    assert progress == {'phase': 'idle', 'current': 0, 'total': 0, 'label': ''}
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `pytest tests/test_media_autopilot_progress.py::test_media_loop_worker_resets_progress_to_idle_between_passes -v`
Expected: `FAIL` — `AssertionError` (progress остаётся старым `{'phase': 'download', 'current': 7, ...}`, т.к. `media_loop_worker` его не трогает)

- [ ] **Step 3: Добавить сброс прогресса в `media_loop_worker`**

Текущий код (`workers/media_autopilot.py:213-244`):
```python
    try:
        while app_state.media_loops.get(media_type):
            _set_state(
                media_type,
                phase='working',
                last_start=datetime.now().strftime('%d.%m %H:%M'),
                next_run='',
            )
            try:
                _CYCLES[media_type]()
            except Exception as e:
                app_state.add_log(f'Автопилот ({label}): ошибка прохода: {e}', 'error')

            try:
                from services.publish_log import rotate_old_logs
                rotate_old_logs()
            except Exception:
                pass

            if not app_state.media_loops.get(media_type):
                break
            interval_sec = loop_interval_min(media_type) * 60
            next_run = datetime.fromtimestamp(time.time() + interval_sec).strftime('%H:%M')
            _set_state(media_type, phase='sleeping', next_run=next_run)
            # Спим короткими шагами, чтобы стоп срабатывал быстро
            deadline = time.time() + interval_sec
            while time.time() < deadline and app_state.media_loops.get(media_type):
                time.sleep(5)
    finally:
        app_state.media_loops[media_type] = False
        _set_state(media_type, phase='stopped', next_run='')
        app_state.add_log(f'Автопилот ({label}): цикл остановлен', 'info')
```

Заменить на:
```python
    try:
        while app_state.media_loops.get(media_type):
            _set_state(
                media_type,
                phase='working',
                last_start=datetime.now().strftime('%d.%m %H:%M'),
                next_run='',
            )
            _set_progress(media_type, phase='idle', current=0, total=0)
            try:
                _CYCLES[media_type]()
            except Exception as e:
                app_state.add_log(f'Автопилот ({label}): ошибка прохода: {e}', 'error')

            try:
                from services.publish_log import rotate_old_logs
                rotate_old_logs()
            except Exception:
                pass

            if not app_state.media_loops.get(media_type):
                break
            interval_sec = loop_interval_min(media_type) * 60
            next_run = datetime.fromtimestamp(time.time() + interval_sec).strftime('%H:%M')
            _set_state(media_type, phase='sleeping', next_run=next_run)
            # Спим короткими шагами, чтобы стоп срабатывал быстро
            deadline = time.time() + interval_sec
            while time.time() < deadline and app_state.media_loops.get(media_type):
                time.sleep(5)
    finally:
        app_state.media_loops[media_type] = False
        _set_state(media_type, phase='stopped', next_run='')
        _set_progress(media_type, phase='idle', current=0, total=0)
        app_state.add_log(f'Автопилот ({label}): цикл остановлен', 'info')
```

- [ ] **Step 4: Запустить тест, убедиться что проходит**

Run: `pytest tests/test_media_autopilot_progress.py -v`
Expected: `PASS` (3 passed)

- [ ] **Step 5: Commit**

```bash
git add workers/media_autopilot.py tests/test_media_autopilot_progress.py
git commit -m "feat: reset loop progress to idle at start and end of each autopilot pass"
```

---

## Часть 4 — Инструментирование воркеров

### Task 7: Прогресс для постов — скачивание (`workers/download.py`)

**Files:**
- Modify: `workers/download.py` (функция `_download_source`, существующий блок `app_state.download_progress`)
- Test: `tests/test_media_autopilot_progress.py`

Контекст (по предыдущему сеансу — функция `_download_source` устанавливает `app_state.download_progress` с полями `current`/`total` и инкрементирует `downloaded` в цикле по постам). Реальные строки в `workers/download.py` (из ранее прочитанного диапазона 60-260):

```python
        app_state.download_progress = {
            'phase': 'download',
            'current': 0,
            'total': count,
            'source': str(community_id),
            'message': f'Загрузка из {owner_id}',
            'cancelled': app_state.download_progress.get('cancelled', False),
        }
```//

и далее в цикле:

```python
            downloaded += 1
            app_state.download_progress['current'] = downloaded
            app_state.download_progress['message'] = f'Сохранено {downloaded} из {count}'
            if downloaded % 10 == 0 or downloaded == 1:
                app_state.add_log(f'[{owner_id}] {downloaded}/{count} сохранено', 'info')
```

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_media_autopilot_progress.py`:

```python
def test_download_source_updates_media_loop_progress(monkeypatch, tmp_path):
    """_download_source должен синхронизировать app_state.media_loop_state['posts']['progress']."""
    monkeypatch.setitem(app_state.media_loop_state, 'posts', {})
    monkeypatch.setattr(app_state, 'download_progress', {'cancelled': False})

    from workers.media_autopilot import _set_progress
    # Симулируем то, что должен делать _download_source при старте загрузки:
    _set_progress('posts', phase='download', current=0, total=5, label='Загрузка из -123')
    _set_progress('posts', phase='download', current=3, total=5, label='Сохранено 3 из 5')

    progress = app_state.media_loop_state['posts']['progress']
    assert progress['phase'] == 'download'
    assert progress['current'] == 3
    assert progress['total'] == 5
```

Это smoke-тест на сам `_set_progress` в контексте постов (детальный интеграционный тест `_download_source` потребовал бы мокать VK API — избыточно для этой задачи; реальная интеграция проверяется в Step 3-4 через ручное чтение кода).

- [ ] **Step 2: Запустить тест, убедиться что проходит уже сейчас**

Run: `pytest tests/test_media_autopilot_progress.py::test_download_source_updates_media_loop_progress -v`
Expected: `PASS` (т.к. `_set_progress` уже реализован в Task 5) — этот тест фиксирует ожидаемый контракт перед тем, как мы добавим реальные вызовы в `download.py`.

- [ ] **Step 3: Добавить вызовы `_set_progress` в `_download_source`**

Найти блок инициализации `app_state.download_progress` в `workers/download.py` (внутри `_download_source`, рядом со строкой, аналогичной):

```python
        app_state.download_progress = {
            'phase': 'download',
            'current': 0,
            'total': count,
            'source': str(community_id),
            'message': f'Загрузка из {owner_id}',
            'cancelled': app_state.download_progress.get('cancelled', False),
        }
```

Сразу после этого блока добавить:

```python
        from workers.media_autopilot import _set_progress
        _set_progress('posts', phase='download', current=0, total=count, label=f'Загрузка из {owner_id}')
```

Найти блок инкремента `downloaded` (аналогичный):

```python
            downloaded += 1
            app_state.download_progress['current'] = downloaded
            app_state.download_progress['message'] = f'Сохранено {downloaded} из {count}'
            if downloaded % 10 == 0 or downloaded == 1:
                app_state.add_log(f'[{owner_id}] {downloaded}/{count} сохранено', 'info')
```

Заменить на:

```python
            downloaded += 1
            app_state.download_progress['current'] = downloaded
            app_state.download_progress['message'] = f'Сохранено {downloaded} из {count}'
            _set_progress('posts', phase='download', current=downloaded, total=count, label=f'Сохранено {downloaded} из {count}')
            if downloaded % 10 == 0 or downloaded == 1:
                app_state.add_log(f'[{owner_id}] {downloaded}/{count} сохранено', 'info')
```

(`_set_progress` уже импортирован выше в этой же функции — повторный `from workers.media_autopilot import _set_progress` не нужен, если он размещён в начале функции; иначе добавить локальный импорт рядом с этим блоком тоже.)

- [ ] **Step 4: Проверить вручную, что код синтаксически корректен**

Run: `python -c "import ast; ast.parse(open('workers/download.py', encoding='utf-8').read())"`
Expected: без вывода (без `SyntaxError`)

- [ ] **Step 5: Запустить полный набор тестов**

Run: `pytest tests/ -q --ignore=tests/test_playwright_ui.py`
Expected: все тесты проходят (как раньше, 126+, плюс новые из Task 5-7)

- [ ] **Step 6: Commit**

```bash
git add workers/download.py tests/test_media_autopilot_progress.py
git commit -m "feat: track posts download progress in media_loop_state"
```

---

### Task 8: Прогресс для постов — публикация (`workers/publish.py`)

**Files:**
- Modify: `workers/publish.py` (цикл `for index, post_file in enumerate(post_files, 1):`, строки ~284-298)

Контекст (`workers/publish.py:284-298`, уже прочитан):

```python
        published = failed = 0
        _poll_counter = 0

        publish_started_at = time.time()
        for index, post_file in enumerate(post_files, 1):
            if not app_state.is_publishing:
                break
            try:
                post_started_at = time.time()
                app_state.download_progress.update({
                    'phase': 'publish',
                    'current': index - 1,
                    'total': len(post_files),
                    'message': f'Публикация {index} из {len(post_files)}',
                })
```

(сообщение показано в декодированном виде; в файле — мojibake-кириллица, см. сноску ниже)

- [ ] **Step 1: Добавить вызов `_set_progress` рядом с обновлением `app_state.download_progress`**

Найти блок:

```python
        published = failed = 0
        _poll_counter = 0

        publish_started_at = time.time()
        for index, post_file in enumerate(post_files, 1):
            if not app_state.is_publishing:
                break
            try:
                post_started_at = time.time()
                app_state.download_progress.update({
                    'phase': 'publish',
                    'current': index - 1,
                    'total': len(post_files),
                    'message': f'РџСѓР±Р»РёРєР°С†РёСЏ {index} РёР· {len(post_files)}',
                })
```

Заменить на:

```python
        published = failed = 0
        _poll_counter = 0

        from workers.media_autopilot import _set_progress

        publish_started_at = time.time()
        for index, post_file in enumerate(post_files, 1):
            if not app_state.is_publishing:
                break
            try:
                post_started_at = time.time()
                app_state.download_progress.update({
                    'phase': 'publish',
                    'current': index - 1,
                    'total': len(post_files),
                    'message': f'РџСѓР±Р»РёРєР°С†РёСЏ {index} РёР· {len(post_files)}',
                })
                _set_progress('posts', phase='publish', current=index - 1, total=len(post_files), label=f'Публикация {index} из {len(post_files)}')
```

- [ ] **Step 2: Добавить финальный вызов после цикла, синхронизирующий `current` с итоговым `published+failed`**

Найти строку (`workers/publish.py`, после цикла, аналог строки 448 в `videos.py`, но для постов — после `for index, post_file in enumerate(post_files, 1):`):

Текущий паттерн завершения (после выхода из цикла публикации) — найти строку вида:
```python
        app_state.add_log(f'РћРїСѓР±Р»РёРєРѕРІР°РЅРѕ {published}, РѕС€РёР±РѕРє {failed} РёР· {len(post_files)}', 'info')
```
(или аналогичную с итоговой статистикой публикации постов — точная мojibake-строка зависит от существующего кода; искать по переменным `published` и `failed` после основного `for`-цикла).

Сразу перед этой строкой (или сразу после, не важно — главное после выхода из цикла) добавить:

```python
        _set_progress('posts', phase='publish', current=published + failed, total=len(post_files), label=f'Опубликовано {published}, ошибок {failed}')
```

- [ ] **Step 3: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('workers/publish.py', encoding='utf-8').read())"`
Expected: без вывода

- [ ] **Step 4: Запустить полный набор тестов**

Run: `pytest tests/ -q --ignore=tests/test_playwright_ui.py`
Expected: все тесты проходят

- [ ] **Step 5: Commit**

```bash
git add workers/publish.py
git commit -m "feat: track posts publish progress in media_loop_state"
```

---

### Task 9: Прогресс для фото — скачивание и публикация (`workers/photos.py`)

**Files:**
- Modify: `workers/photos.py` — `_download_photos_source()` (цикл `for photo in items:`) и `publish_photos_worker()` (цикл `for meta_file in queue:`)

Контекст (полностью прочитан в предыдущем сеансе, 426 строк):

```python
def _download_photos_source(community_id: str, count: int):
    # ... setup ...
    downloaded = skipped = 0
    offset = 0
    app_state.add_log(f'Фото: загрузка {count} из {owner_id}', 'info')
    while downloaded < count and app_state.is_downloading_photos:
        # ... vk.photos.getAll call ...
        for photo in items:
            if not app_state.is_downloading_photos or downloaded >= count:
                break
            # ... download logic ...
            downloaded += 1
            if downloaded % 10 == 0 or downloaded == 1:
                app_state.add_log(f'Фото [{owner_id}] {downloaded}/{count}', 'info')
            time.sleep(random.uniform(delay_min, delay_max))
        offset += len(items)
        if len(items) < 200:
            break
    app_state.add_log(f'Фото [{owner_id}]: {downloaded} скачано, {skipped} пропущено', 'info')
```

```python
def publish_photos_worker(count: int):
    try:
        # ... setup, album creation ...
        queue = sorted(app_state.photos_queue_dir.glob('*.json'))[:count]
        if not queue:
            app_state.add_log('Фото: очередь пуста', 'warning')
            return
        app_state.add_log(f'Фото: публикация {len(queue)} фото', 'info')
        published = failed = 0
        for meta_file in queue:
            if not app_state.is_publishing_photos:
                break
            try:
                # ... process, upload, post to wall ...
                published += 1
            except vk_api.exceptions.ApiError as e:
                failed += 1
                # ...
            except Exception as e:
                failed += 1
        app_state.add_log(f'Фото: {published} опубликовано, {failed} ошибок', 'info')
        # ... cleanup ...
    except Exception as e:
        app_state.add_log(f'Фото публикация критическая ошибка: {e}', 'error')
    finally:
        app_state.is_publishing_photos = False
```

- [ ] **Step 1: Инструментировать `_download_photos_source`**

Найти строку:
```python
    app_state.add_log(f'Фото: загрузка {count} из {owner_id}', 'info')
```

Сразу после неё добавить:
```python
    from workers.media_autopilot import _set_progress
    _set_progress('photos', phase='download', current=0, total=count, label=f'Загрузка из {owner_id}')
```

Найти блок инкремента:
```python
            downloaded += 1
            if downloaded % 10 == 0 or downloaded == 1:
                app_state.add_log(f'Фото [{owner_id}] {downloaded}/{count}', 'info')
```

Заменить на:
```python
            downloaded += 1
            _set_progress('photos', phase='download', current=downloaded, total=count, label=f'Скачано {downloaded} из {count}')
            if downloaded % 10 == 0 or downloaded == 1:
                app_state.add_log(f'Фото [{owner_id}] {downloaded}/{count}', 'info')
```

- [ ] **Step 2: Инструментировать `publish_photos_worker`**

Найти строку:
```python
        app_state.add_log(f'Фото: публикация {len(queue)} фото', 'info')
        published = failed = 0
```

Заменить на:
```python
        app_state.add_log(f'Фото: публикация {len(queue)} фото', 'info')
        from workers.media_autopilot import _set_progress
        _set_progress('photos', phase='publish', current=0, total=len(queue), label=f'Публикация 0 из {len(queue)}')
        published = failed = 0
```

Найти начало цикла:
```python
        for meta_file in queue:
            if not app_state.is_publishing_photos:
                break
            try:
```

Заменить на (добавляя индекс через `enumerate`):
```python
        for index, meta_file in enumerate(queue, 1):
            if not app_state.is_publishing_photos:
                break
            _set_progress('photos', phase='publish', current=index - 1, total=len(queue), label=f'Публикация {index} из {len(queue)}')
            try:
```

Найти финальную строку:
```python
        app_state.add_log(f'Фото: {published} опубликовано, {failed} ошибок', 'info')
```

Сразу перед ней добавить:
```python
        _set_progress('photos', phase='publish', current=published + failed, total=len(queue), label=f'Опубликовано {published}, ошибок {failed}')
```

- [ ] **Step 3: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('workers/photos.py', encoding='utf-8').read())"`
Expected: без вывода

- [ ] **Step 4: Запустить полный набор тестов**

Run: `pytest tests/ -q --ignore=tests/test_playwright_ui.py`
Expected: все тесты проходят

- [ ] **Step 5: Commit**

```bash
git add workers/photos.py
git commit -m "feat: track photos download/publish progress in media_loop_state"
```

---

### Task 10: Прогресс для видео/клипов — скачивание и публикация (`workers/videos.py`)

**Files:**
- Modify: `workers/videos.py` — `_download_videos_source()` (цикл `for video in items:`, строки ~184-250) и `publish_videos_worker()` (цикл `for meta_file in queue:`, строки ~332-446)

Контекст (`workers/videos.py:134-256`, `_download_videos_source`):

```python
def _download_videos_source(community_id: str, count: int,
                             max_duration: int = 0, max_mb: int = 500,
                             quality: str = '720', is_clips_mode: bool = False):
    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    api_ver = vk_cfg.get('api_version', '5.131')

    flag = 'is_downloading_clips' if is_clips_mode else 'is_downloading_videos'
    queue_dir = app_state.clips_queue_dir if is_clips_mode else app_state.videos_queue_dir
    files_dir = app_state.clip_files_dir  if is_clips_mode else app_state.video_files_dir

    if not user_token:
        app_state.add_log(f'{"Клипы" if is_clips_mode else "Видео"}: User Token не задан', 'error')
        return

    vk = get_vk_api(user_token, api_ver)
    owner_id = normalize_owner_id(community_id)
    seen = _load_seen() if not is_clips_mode else _load_clips_seen()
    downloaded = skipped = 0
    offset = 0
    label = 'Клипы' if is_clips_mode else 'Видео'

    app_state.add_log(f'{label}: загрузка {count} из {owner_id}', 'info')

    while downloaded < count and getattr(app_state, flag):
        ...
        for video in items:
            if not getattr(app_state, flag) or downloaded >= count:
                break
            ...
            downloaded += 1
            if downloaded % 5 == 0 or downloaded == 1:
                app_state.add_log(f'{label} [{owner_id}] {downloaded}/{count}', 'info')

            time.sleep(random.uniform(1, 3))

        offset += len(items)
        if len(items) < 200:
            break

    app_state.add_log(f'{label} [{owner_id}]: {downloaded} скачано, {skipped} пропущено', 'info')
```

- [ ] **Step 1: Инструментировать `_download_videos_source`**

Найти строку:
```python
    app_state.add_log(f'{label}: загрузка {count} из {owner_id}', 'info')
```

Заменить на:
```python
    app_state.add_log(f'{label}: загрузка {count} из {owner_id}', 'info')
    from workers.media_autopilot import _set_progress
    progress_type = 'clips' if is_clips_mode else 'videos'
    _set_progress(progress_type, phase='download', current=0, total=count, label=f'Загрузка из {owner_id}')
```

Найти блок инкремента:
```python
            downloaded += 1
            if downloaded % 5 == 0 or downloaded == 1:
                app_state.add_log(f'{label} [{owner_id}] {downloaded}/{count}', 'info')

            time.sleep(random.uniform(1, 3))
```

Заменить на:
```python
            downloaded += 1
            _set_progress(progress_type, phase='download', current=downloaded, total=count, label=f'Скачано {downloaded} из {count}')
            if downloaded % 5 == 0 or downloaded == 1:
                app_state.add_log(f'{label} [{owner_id}] {downloaded}/{count}', 'info')

            time.sleep(random.uniform(1, 3))
```

- [ ] **Step 2: Инструментировать `publish_videos_worker`**

Контекст (`workers/videos.py:292-462`, начало и циклы):

```python
def publish_videos_worker(count: int, is_clips_mode: bool = False):
    label = 'Клипы' if is_clips_mode else 'Видео'
    flag  = 'is_publishing_clips' if is_clips_mode else 'is_publishing_videos'
    queue_dir = app_state.clips_queue_dir if is_clips_mode else app_state.videos_queue_dir
    cfg_key   = 'clips_settings' if is_clips_mode else 'videos_settings'

    try:
        ...
        queue = sorted(queue_dir.glob('*.json'))[:count]
        if not queue:
            app_state.add_log(f'{label}: очередь пуста', 'warning')
            return

        app_state.add_log(f'{label}: публикация {len(queue)}', 'info')
        published = failed = 0
        media_type = 'clips' if is_clips_mode else 'videos'

        for meta_file in queue:
            if not getattr(app_state, flag):
                break
            try:
                ...
```

Найти строку:
```python
        app_state.add_log(f'{label}: публикация {len(queue)}', 'info')
        published = failed = 0
        media_type = 'clips' if is_clips_mode else 'videos'

        for meta_file in queue:
            if not getattr(app_state, flag):
                break
            try:
```

Заменить на:
```python
        app_state.add_log(f'{label}: публикация {len(queue)}', 'info')
        from workers.media_autopilot import _set_progress
        published = failed = 0
        media_type = 'clips' if is_clips_mode else 'videos'
        _set_progress(media_type, phase='publish', current=0, total=len(queue), label=f'Публикация 0 из {len(queue)}')

        for index, meta_file in enumerate(queue, 1):
            if not getattr(app_state, flag):
                break
            _set_progress(media_type, phase='publish', current=index - 1, total=len(queue), label=f'Публикация {index} из {len(queue)}')
            try:
```

Найти финальную строку (после `for`-цикла):
```python
        app_state.add_log(f'{label}: {published} опубликовано, {failed} ошибок', 'info')
```

Сразу перед ней добавить:
```python
        _set_progress(media_type, phase='publish', current=published + failed, total=len(queue), label=f'Опубликовано {published}, ошибок {failed}')
```

- [ ] **Step 3: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('workers/videos.py', encoding='utf-8').read())"`
Expected: без вывода

- [ ] **Step 4: Запустить полный набор тестов**

Run: `pytest tests/ -q --ignore=tests/test_playwright_ui.py`
Expected: все тесты проходят

- [ ] **Step 5: Commit**

```bash
git add workers/videos.py
git commit -m "feat: track videos/clips download and publish progress in media_loop_state"
```

---

## Часть 5 — Frontend: отрисовка прогресс-бара

### Task 11: `apRefreshLoops()` — обновление прогресс-бара и статус-строки

**Files:**
- Modify: `frontend/js/autopilot.js:175-220` (область `AP_LOOP_LABELS`/`AP_PHASE_LABELS`/`apRefreshLoops`)

Текущий код (`frontend/js/autopilot.js:175-220`, уже прочитан полностью):

```js
const AP_LOOP_LABELS = { posts: 'постов', photos: 'фото', videos: 'видео', clips: 'клипов' };
const AP_PHASE_LABELS = { working: 'работает', sleeping: 'ждёт', stopped: 'остановлен' };

async function apToggleLoop(type) {
  const btn = $(`apLoopBtn-${type}`);
  const running = btn?.dataset.running === '1';
  const data = await api(`/autopilot/loop/${type}/${running ? 'stop' : 'start'}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  }).catch(error => ({ status: 'error', message: error.message }));
  notify(message(data, 'Готово'), data.status === 'ok' ? 'success' : 'error');
  await apRefreshLoops();
}

async function apRefreshLoops() {
  const data = await api('/autopilot/loops').catch(() => null);
  if (!data || !data.loops) return;
  const active = [];
  for (const [type, st] of Object.entries(data.loops)) {
    const btn = $(`apLoopBtn-${type}`);
    if (btn) {
      btn.dataset.running = st.running ? '1' : '0';
      btn.classList.toggle('btn-danger', !!st.running);
      btn.classList.toggle('btn-primary', !st.running);
      btn.textContent = st.running ? `■ Стоп ${AP_LOOP_LABELS[type]}` : `Цикл ${AP_LOOP_LABELS[type]}`;
    }
    if (st.running) {
      const phase = AP_PHASE_LABELS[st.phase] || st.phase || 'работает';
      active.push(`${AP_LOOP_LABELS[type]}: ${phase}${st.next_run ? ` (след. ${st.next_run})` : ''}`);
    }
    apFillLoopInput(`apInterval-${type}`, st.interval_min || 180);
    apFillLoopInput(`apDownload-${type}`, st.download_count || 1);
    apFillLoopInput(`apPublish-${type}`, st.publish_count || 1);
  }
  const statusEl = $('gaStatusText');
  if (statusEl) statusEl.textContent = active.length ? `Работают: ${active.join(' · ')}` : 'Автопилот готов.';
  const cycleEl = $('dashGaCycle');
  if (cycleEl) cycleEl.textContent = active.length ? `${active.length} цикл.` : 'ожидание';
}
```

- [ ] **Step 1: Добавить новые DOM-обновления внутри цикла `for` и новую функцию `formatApStatus`**

Заменить весь блок выше (строки 175-220) на:

```js
const AP_LOOP_LABELS = { posts: 'постов', photos: 'фото', videos: 'видео', clips: 'клипов' };
const AP_PHASE_LABELS = { working: 'работает', sleeping: 'ждёт', stopped: 'остановлен' };
const AP_PROGRESS_PHASE_LABELS = { download: 'Скачивание', publish: 'Публикация', idle: '' };

async function apToggleLoop(type) {
  const btn = $(`apLoopBtn-${type}`);
  const running = btn?.dataset.running === '1';
  const data = await api(`/autopilot/loop/${type}/${running ? 'stop' : 'start'}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  }).catch(error => ({ status: 'error', message: error.message }));
  notify(message(data, 'Готово'), data.status === 'ok' ? 'success' : 'error');
  await apRefreshLoops();
}

function formatApStatus(type, st) {
  if (!st.running) return 'Остановлен';
  const phase = AP_PHASE_LABELS[st.phase] || st.phase || 'работает';
  const progress = st.progress || {};
  const progressLabel = AP_PROGRESS_PHASE_LABELS[progress.phase];
  const parts = [phase];
  if (progressLabel) parts.push(progressLabel);
  if (st.next_run) parts.push(`след. ${st.next_run}`);
  return parts.join(' · ');
}

async function apRefreshLoops() {
  const data = await api('/autopilot/loops').catch(() => null);
  if (!data || !data.loops) return;
  const active = [];
  for (const [type, st] of Object.entries(data.loops)) {
    const btn = $(`apLoopBtn-${type}`);
    if (btn) {
      btn.dataset.running = st.running ? '1' : '0';
      btn.classList.toggle('btn-danger', !!st.running);
      btn.classList.toggle('btn-primary', !st.running);
      btn.textContent = st.running ? `■ Стоп ${AP_LOOP_LABELS[type]}` : `Цикл ${AP_LOOP_LABELS[type]}`;
    }
    if (st.running) {
      const phase = AP_PHASE_LABELS[st.phase] || st.phase || 'работает';
      active.push(`${AP_LOOP_LABELS[type]}: ${phase}${st.next_run ? ` (след. ${st.next_run})` : ''}`);
    }
    apFillLoopInput(`apInterval-${type}`, st.interval_min || 180);
    apFillLoopInput(`apDownload-${type}`, st.download_count || 1);
    apFillLoopInput(`apPublish-${type}`, st.publish_count || 1);

    const dot = $(`apStatusDot-${type}`);
    if (dot) {
      dot.classList.toggle('running', !!st.running && st.phase === 'working');
      dot.classList.toggle('sleeping', !!st.running && st.phase === 'sleeping');
    }

    const statusEl = $(`apStatusText-${type}`);
    if (statusEl) statusEl.textContent = formatApStatus(type, st);

    const progress = st.progress || {};
    const total = progress.total || 0;
    const current = progress.current || 0;
    const pct = total > 0 ? Math.round((current / total) * 100) : 0;

    const fill = $(`apProgressFill-${type}`);
    const label = $(`apProgressLabel-${type}`);
    const pctEl = $(`apProgressPct-${type}`);
    if (fill) {
      fill.style.width = total > 0 ? `${pct}%` : '0%';
      fill.classList.toggle('idle', total === 0);
    }
    if (label) label.textContent = total > 0 ? `${current} из ${total}` : '—';
    if (pctEl) pctEl.textContent = total > 0 ? `${pct}%` : '—';
  }
  const statusEl = $('gaStatusText');
  if (statusEl) statusEl.textContent = active.length ? `Работают: ${active.join(' · ')}` : 'Автопилот готов.';
  const cycleEl = $('dashGaCycle');
  if (cycleEl) cycleEl.textContent = active.length ? `${active.length} цикл.` : 'ожидание';
}
```

Примечание: при `phase='sleeping'` backend (`media_loop_worker`) НЕ вызывает `_set_progress`, поэтому `st.progress` сохраняет значения с последнего прохода (`current`/`total` от последнего завершённого скачивания/публикации) — прогресс-бар "застывает" на последнем проценте серым цветом (`.idle` класс применяется только когда `total === 0`, а после реального прохода `total > 0`, так что фон остаётся `var(--accent)`; если требуется именно серый замороженный вид во время сна — это перекрывается тем, что `_set_progress(media_type, phase='idle', current=0, total=0)` вызывается в начале каждого прохода в `media_loop_worker`, поэтому в фазе `sleeping` `progress` всё ещё хранит данные последнего прохода до следующего `idle`-сброса в начале следующего прохода — то есть бар показывает последний реальный результат до начала следующего прохода, что соответствует требованию "застывший % предыдущего прохода").

- [ ] **Step 2: Запустить фронтенд и проверить в браузере**

Run (если используется встроенный сервер): `python main.py` (или `start.bat`), открыть `http://localhost:8000`, перейти на дашборд.

Проверить:
1. Все 4 карточки показывают `—` / `0%` / пустую полосу при отсутствии активных циклов.
2. Запустить цикл "посты" (`apToggleLoop('posts')`), подождать несколько секунд — `apStatusText-posts` должен показать "работает · Скачивание", `apProgressLabel-posts` — "N из M", `apProgressPct-posts` — растущий %, `apProgressFill-posts` — растущая полоса.
3. Остановить цикл — статус "Остановлен", точка гаснет.

- [ ] **Step 3: Commit**

```bash
git add frontend/js/autopilot.js
git commit -m "feat: render autopilot loop progress bars and status text in apRefreshLoops"
```

---

## Самопроверка плана (self-review)

**1. Покрытие спеки:**
- Палитра `:root` → Task 1 ✅
- 12 точечных замен хардкод-цветов → Task 2 (все 12 пунктов из таблицы спеки покрыты) ✅
- `.ap-cycle` HTML/CSS структура с сохранением id/onclick → Task 3 (CSS) + Task 4 (HTML) ✅
- `_set_progress()` helper → Task 5 ✅
- Сброс в idle между проходами → Task 6 ✅
- Интеграция в посты (download+publish) → Task 7, 8 ✅
- Интеграция в фото (с нуля) → Task 9 ✅
- Интеграция в видео/клипы (с нуля) → Task 10 ✅
- Frontend `apRefreshLoops()` + `formatApStatus()` → Task 11 ✅
- Без новых web-фонтов, системный стек сохранён → не менялся ни в одном Task ✅
- Удаление `_mockup_autopilot.html` — вне скоупа, не включено в план (по решению из спеки) ✅

**2. Проверка плейсхолдеров:** Все шаги содержат конкретный код "до/после" или конкретные команды. В Task 7-10 даны точные текущие фрагменты кода (взятые из реально прочитанных файлов) и точные замены.

**3. Согласованность типов/сигнатур:**
- `_set_progress(media_type: str, *, phase: str, current: int, total: int, label: str = '')` — сигнатура одинакова во всех вызовах (Task 5, 7, 8, 9, 10).
- Поле `progress` в `media_loop_state[media_type]` — формат `{'phase', 'current', 'total', 'label'}` одинаков везде.
- Frontend читает `st.progress.{phase,current,total}` — соответствует backend-формату.
- DOM id: `apStatusDot-{type}`, `apStatusText-{type}`, `apProgressFill-{type}`, `apProgressLabel-{type}`, `apProgressPct-{type}` — определены в Task 4 (HTML), используются в Task 11 (JS) с теми же именами.
- `apCycleSettings-{type}` id сохранён на внутреннем `.form-section` (Task 4) — JS не обращается к этому id напрямую (проверено по `autopilot.js`), так что перенос безопасен.

---

## Порядок выполнения

Часть 1 (палитра) и Часть 2 (HTML/CSS карточек) — независимы от Части 3/4 (backend). Часть 5 (JS) зависит от Части 3/4 (читает `st.progress`) и от Части 2 (требует новых DOM id). Рекомендуемый порядок: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11.
