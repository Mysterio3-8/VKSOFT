# Niche Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить анализатор VK-ниш — ищет популярные сообщества по ключевым словам или автоматически, считает скор потенциала, отображает рейтинг в Web UI с возможностью добавить источник одной кнопкой.

**Architecture:** Сервис `services/niche_analyzer.py` делает запросы к VK API (groups.search + wall.get), считает скор и сохраняет результат в `app_state`. Роутер `api/niche_analyzer.py` экспонирует три endpoint. Страница `frontend/niche.html` загружается как отдельная вкладка через существующий механизм `data-tab`.

**Tech Stack:** Python 3.10+, FastAPI, vk_api, threading (паттерн как в monitor/download), Vanilla JS + существующий CSS проекта.

---

## File Map

| Действие | Файл | Ответственность |
|----------|------|-----------------|
| Create | `services/niche_analyzer.py` | Логика: поиск сообществ, подсчёт скора, нормализация |
| Create | `api/niche_analyzer.py` | FastAPI роутер: /niche/scan, /niche/results, /niche/add-source |
| Create | `frontend/niche.html` | UI: форма + прогресс-бар + таблица результатов |
| Modify | `config.py` | Добавить `is_niche_scanning`, `niche_results`, `niche_progress` в `AppState.__init__` |
| Modify | `main.py` | Подключить роутер и статический маршрут `/niche` |
| Modify | `frontend/index.html` | Добавить пункт меню «Ниши» и подключить скрипт страницы |

---

## Task 1: Расширить AppState под нишевый анализатор

**Files:**
- Modify: `config.py:50-70` (метод `__init__`)

- [ ] **Step 1: Добавить три поля в `AppState.__init__`**

Открой `config.py`. Найди блок флагов (строки ~52-68) и добавь после `self.is_autopilot = False`:

```python
        self.is_niche_scanning = False
        self.niche_progress: Dict = {'current': 0, 'total': 0, 'keyword': ''}
        self.niche_results: List[Dict] = []
```

- [ ] **Step 2: Убедиться что импорты покрывают новые типы**

В `config.py` строка 10 уже импортирует `Dict, List, Optional` из `typing` — ничего добавлять не нужно.

- [ ] **Step 3: Запустить сервер и проверить что он стартует**

```bash
cd vk-post-reposting-bot
python main.py
```

Ожидаемый вывод: `VK POST BOT v2.0  —  http://localhost:8000` без ошибок. Остановить Ctrl+C.

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "feat: add niche analyzer state fields to AppState"
```

---

## Task 2: Сервис анализа ниш

**Files:**
- Create: `services/niche_analyzer.py`

- [ ] **Step 1: Создать файл сервиса**

Создай `services/niche_analyzer.py` со следующим содержимым:

```python
# -*- coding: utf-8 -*-
"""Анализатор ниш VK — поиск и ранжирование сообществ."""

import time
from datetime import datetime, timezone
from typing import List, Dict, Optional

import vk_api

from config import app_state, logger
from vk.api import get_vk_api, vk_call_safe

AUTO_KEYWORDS = [
    'юмор', 'фитнес', 'авто', 'кулинария', 'путешествия',
    'мотивация', 'технологии', 'животные', 'красота', 'спорт',
    'музыка', 'кино', 'игры', 'бизнес', 'психология',
    'дети', 'мода', 'здоровье', 'новости', 'природа',
]


def _score_community(members: int, avg_likes: float, posts_per_week: float, activity: float) -> float:
    """Считает сырой скор сообщества. Всегда >= 0."""
    if members <= 0:
        return 0.0
    engagement = avg_likes / max(posts_per_week, 1)
    return members * engagement * max(activity, 0.01)


def _normalize_scores(communities: List[Dict]) -> List[Dict]:
    """Нормализует поле score до 0–100 внутри выборки."""
    if not communities:
        return communities
    max_score = max(c['raw_score'] for c in communities)
    if max_score == 0:
        for c in communities:
            c['score'] = 0.0
        return communities
    for c in communities:
        c['score'] = round(c['raw_score'] / max_score * 100, 1)
    return communities


def _analyze_community(vk, group: Dict) -> Optional[Dict]:
    """
    Берёт данные одного сообщества из groups.search и дополняет их
    стастикой из wall.get. Возвращает None если группа недоступна.
    """
    gid = group.get('id')
    members = group.get('members_count', 0)
    if not gid or members < 1000:
        return None

    owner_id = f'-{gid}'
    try:
        wall = vk_call_safe(vk.wall.get, owner_id=owner_id, count=20, filter='owner')
    except vk_api.exceptions.ApiError as e:
        if getattr(e, 'code', 0) in (15, 19, 7):  # закрытая группа / доступ запрещён
            return None
        return None
    except Exception:
        return None

    items = wall.get('items', [])
    if not items:
        return None

    now_ts = int(datetime.now(timezone.utc).timestamp())
    week_ago = now_ts - 7 * 86400

    total_likes = sum(p.get('likes', {}).get('count', 0) for p in items)
    avg_likes = total_likes / len(items)

    recent = [p for p in items if p.get('date', 0) >= week_ago]
    activity_factor = len(recent) / len(items)

    if items:
        oldest_ts = min(p.get('date', now_ts) for p in items)
        span_weeks = max((now_ts - oldest_ts) / (7 * 86400), 0.01)
        posts_per_week = len(items) / span_weeks
    else:
        posts_per_week = 0.0

    raw_score = _score_community(members, avg_likes, posts_per_week, activity_factor)

    return {
        'id': gid,
        'name': group.get('name', ''),
        'screen_name': group.get('screen_name', ''),
        'members': members,
        'avg_likes': round(avg_likes, 1),
        'posts_per_week': round(posts_per_week, 1),
        'activity_factor': round(activity_factor, 2),
        'raw_score': raw_score,
        'score': 0.0,  # заполняется после нормализации
    }


def _scan_keyword(vk, keyword: str) -> List[Dict]:
    """Ищет до 20 сообществ по ключевому слову и возвращает проанализированные."""
    try:
        resp = vk_call_safe(
            vk.groups.search,
            q=keyword,
            type='page',
            count=20,
            sort=0,  # сортировка по релевантности
        )
    except Exception as e:
        logger.warning(f'groups.search "{keyword}": {e}')
        return []

    groups = resp.get('items', [])
    results = []
    for group in groups:
        time.sleep(0.35)  # не превышать rate limit VK
        community = _analyze_community(vk, group)
        if community:
            results.append(community)

    return _normalize_scores(results)


def run_niche_scan(keywords: List[str]) -> None:
    """
    Фоновый воркер. Вызывается из threading.Thread.
    Обновляет app_state.niche_progress и app_state.niche_results.
    """
    app_state.is_niche_scanning = True
    app_state.niche_results = []
    app_state.niche_progress = {'current': 0, 'total': len(keywords), 'keyword': ''}

    vk_cfg = app_state.profile.get('vk', {})
    user_token = vk_cfg.get('user_token', '').strip()
    api_ver = vk_cfg.get('api_version', '5.131')

    if not user_token:
        app_state.add_log('Нишевый анализ: user_token не задан', 'error')
        app_state.is_niche_scanning = False
        return

    try:
        vk = get_vk_api(user_token, api_ver)
    except Exception as e:
        app_state.add_log(f'Нишевый анализ: ошибка VK API: {e}', 'error')
        app_state.is_niche_scanning = False
        return

    results = []
    for idx, keyword in enumerate(keywords):
        app_state.niche_progress = {'current': idx + 1, 'total': len(keywords), 'keyword': keyword}
        app_state.add_log(f'Анализ ниши: {keyword} ({idx + 1}/{len(keywords)})', 'info')

        communities = _scan_keyword(vk, keyword)
        top = max(communities, key=lambda c: c['score'], default=None) if communities else None

        results.append({
            'keyword': keyword,
            'communities': communities,
            'top_community': top,
            'avg_score': round(sum(c['score'] for c in communities) / len(communities), 1) if communities else 0.0,
            'count': len(communities),
        })

    # Сортируем ниши по среднему скору
    results.sort(key=lambda r: r['avg_score'], reverse=True)
    app_state.niche_results = results
    app_state.niche_progress = {'current': len(keywords), 'total': len(keywords), 'keyword': ''}
    app_state.add_log(f'Анализ ниш завершён: {len(results)} ниш', 'info')
    app_state.is_niche_scanning = False
```

- [ ] **Step 2: Убедиться что сервис импортируется без ошибок**

```bash
cd vk-post-reposting-bot
python -c "from services.niche_analyzer import run_niche_scan, AUTO_KEYWORDS; print('OK', len(AUTO_KEYWORDS))"
```

Ожидаемый вывод: `OK 20`

- [ ] **Step 3: Commit**

```bash
git add services/niche_analyzer.py
git commit -m "feat: add niche analyzer service with VK API scoring"
```

---

## Task 3: FastAPI роутер

**Files:**
- Create: `api/niche_analyzer.py`

- [ ] **Step 1: Создать файл роутера**

Создай `api/niche_analyzer.py`:

```python
# -*- coding: utf-8 -*-
"""Niche analyzer routes."""

import threading
from fastapi import APIRouter

from config import app_state
from services.niche_analyzer import run_niche_scan, AUTO_KEYWORDS

router = APIRouter()


@router.post('/niche/scan')
async def niche_scan(data: dict):
    if app_state.is_niche_scanning:
        return {'status': 'error', 'message': 'Анализ уже запущен'}

    vk_cfg = app_state.profile.get('vk', {})
    if not vk_cfg.get('user_token', '').strip():
        return {'status': 'error', 'message': 'user_token не задан в настройках'}

    auto = data.get('auto', False)
    if auto:
        keywords = AUTO_KEYWORDS
    else:
        raw = data.get('keywords', [])
        keywords = [k.strip() for k in raw if isinstance(k, str) and k.strip()]

    if not keywords:
        return {'status': 'error', 'message': 'Укажите ключевые слова'}

    t = threading.Thread(target=run_niche_scan, args=(keywords,), daemon=True)
    t.start()
    return {'status': 'started', 'keywords_count': len(keywords)}


@router.get('/niche/results')
async def niche_results():
    prog = app_state.niche_progress
    total = prog.get('total', 0)
    current = prog.get('current', 0)
    progress_pct = int(current / total * 100) if total > 0 else 0

    if app_state.is_niche_scanning:
        status = 'running'
    elif app_state.niche_results:
        status = 'done'
    else:
        status = 'idle'

    return {
        'status': status,
        'progress': progress_pct,
        'current_keyword': prog.get('keyword', ''),
        'results': app_state.niche_results,
    }


@router.post('/niche/add-source')
async def niche_add_source(data: dict):
    community_id = str(data.get('community_id', '')).strip()
    name = str(data.get('name', '')).strip() or f'community_{community_id}'

    if not community_id:
        return {'status': 'error', 'message': 'community_id не указан'}

    profile = app_state.config['profiles'][app_state.active_profile_id]
    sources = profile.setdefault('sources', [])

    if any(str(s.get('community_id', '')) == community_id for s in sources):
        return {'status': 'error', 'message': 'Источник уже добавлен'}

    src = {
        'id': max((s.get('id', 0) for s in sources), default=0) + 1,
        'name': name,
        'community_id': community_id,
        'enabled': True,
    }
    sources.append(src)
    app_state.save_config()
    app_state.add_log(f'Добавлен источник из анализа ниш: {name} ({community_id})', 'info')
    return {'status': 'ok', 'source': src}
```

- [ ] **Step 2: Commit**

```bash
git add api/niche_analyzer.py
git commit -m "feat: add niche analyzer FastAPI router"
```

---

## Task 4: Подключить роутер и маршрут в main.py

**Files:**
- Modify: `main.py:81-115` (блок include_router)

- [ ] **Step 1: Добавить импорт и маршрут страницы**

В `main.py` найди блок `# ── Include routers` и добавь в конец:

```python
from api.niche_analyzer import router as niche_router
app.include_router(niche_router, prefix='/api')
```

Также добавь маршрут для HTML-страницы перед блоком `# ── Main`:

```python
@app.get('/niche')
async def niche_page():
    return FileResponse(FRONTEND_DIR / 'niche.html')
```

- [ ] **Step 2: Проверить что сервер стартует без ошибок**

```bash
python main.py
```

Открой в браузере `http://localhost:8000/api/niche/results`. Ожидаемый ответ:
```json
{"status": "idle", "progress": 0, "current_keyword": "", "results": []}
```

Остановить Ctrl+C.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: register niche analyzer router and page route"
```

---

## Task 5: Добавить пункт меню в index.html

**Files:**
- Modify: `frontend/index.html:23-32` (блок `<nav class="nav-menu">`)

- [ ] **Step 1: Вставить пункт меню после кнопки «Логи»**

Найди строку:
```html
    <button class="nav-item" data-tab="logs"><span class="nav-icon">G</span><span>Логи</span></button>
```

И добавь после неё:
```html
    <button class="nav-item" data-tab="niches" onclick="window.location='/niche'"><span class="nav-icon">N</span><span>Ниши</span></button>
```

- [ ] **Step 2: Убедиться что index.html открывается без ошибок консоли**

Запусти сервер, открой `http://localhost:8000`, проверь что в боковом меню появился пункт «Ниши».

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: add Niches menu item to sidebar"
```

---

## Task 6: Создать страницу нишевого анализатора

**Files:**
- Create: `frontend/niche.html`

- [ ] **Step 1: Создать HTML-страницу**

Создай `frontend/niche.html`:

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Анализ ниш — VK Post Bot</title>
  <link rel="stylesheet" href="/static/style.css">
  <style>
    .niche-page { max-width: 1100px; margin: 0 auto; padding: 24px; }
    .niche-header { margin-bottom: 24px; }
    .niche-header h2 { font-size: 1.4rem; font-weight: 600; margin-bottom: 6px; }
    .niche-header p { color: var(--text-secondary, #888); font-size: 0.9rem; }
    .niche-controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 20px; }
    .niche-controls input { flex: 1; min-width: 200px; padding: 8px 12px; border: 1px solid var(--border, #333); border-radius: 8px; background: var(--card-bg, #1a1a1a); color: inherit; font-size: 0.95rem; }
    .progress-bar-wrap { background: var(--border, #333); border-radius: 6px; height: 8px; margin-bottom: 16px; overflow: hidden; }
    .progress-bar-fill { height: 100%; background: var(--accent, #7c3aed); border-radius: 6px; transition: width 0.4s; }
    .progress-label { font-size: 0.85rem; color: var(--text-secondary, #888); margin-bottom: 12px; }
    .niche-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    .niche-table th { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border, #333); color: var(--text-secondary, #888); font-weight: 500; }
    .niche-table td { padding: 10px 12px; border-bottom: 1px solid var(--border, #222); vertical-align: top; }
    .niche-table tr:hover td { background: var(--hover, #222); }
    .score-badge { display: inline-block; padding: 2px 8px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; background: var(--accent, #7c3aed); color: #fff; }
    .score-high { background: #16a34a; }
    .score-mid  { background: #b45309; }
    .score-low  { background: #6b7280; }
    .back-link { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary, #888); text-decoration: none; font-size: 0.9rem; margin-bottom: 20px; }
    .back-link:hover { color: inherit; }
    #statusMsg { font-size: 0.9rem; color: var(--text-secondary, #888); margin-bottom: 12px; min-height: 20px; }
  </style>
</head>
<body>
<div class="niche-page">
  <a class="back-link" href="/">← Назад</a>

  <div class="niche-header">
    <h2>Анализ ниш VK</h2>
    <p>Находит популярные сообщества, считает скор вовлечённости и помогает выбрать нишу для канала.</p>
  </div>

  <div class="niche-controls">
    <input type="text" id="keywordsInput" placeholder="Ниши через запятую: фитнес, юмор, авто…">
    <button class="btn btn-primary" onclick="startScan(false)">🔍 Найти по ключевым словам</button>
    <button class="btn btn-secondary" onclick="startScan(true)">⚡ Авто-обзор топ-ниш</button>
  </div>

  <div id="progressSection" style="display:none">
    <div class="progress-label" id="progressLabel">Анализирую…</div>
    <div class="progress-bar-wrap">
      <div class="progress-bar-fill" id="progressFill" style="width:0%"></div>
    </div>
  </div>

  <div id="statusMsg"></div>

  <div id="resultsSection" style="display:none">
    <table class="niche-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Ниша</th>
          <th>Сообществ</th>
          <th>Ср. подписчики</th>
          <th>Ср. лайки/пост</th>
          <th>Скор ниши</th>
          <th>Действие</th>
        </tr>
      </thead>
      <tbody id="nicheTableBody"></tbody>
    </table>
  </div>
</div>

<script>
let pollTimer = null;

async function startScan(auto) {
  const keywords = document.getElementById('keywordsInput').value
    .split(',').map(k => k.trim()).filter(Boolean);

  if (!auto && keywords.length === 0) {
    setStatus('Введите хотя бы одну нишу или нажмите «Авто-обзор»');
    return;
  }

  setStatus('Запускаю анализ…');
  document.getElementById('resultsSection').style.display = 'none';
  document.getElementById('progressSection').style.display = 'block';
  setProgress(0, 'Запуск…');

  try {
    const res = await fetch('/api/niche/scan', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({auto, keywords}),
    });
    const data = await res.json();
    if (data.status !== 'started') {
      setStatus('Ошибка: ' + data.message);
      document.getElementById('progressSection').style.display = 'none';
      return;
    }
    setStatus('');
    startPolling();
  } catch (e) {
    setStatus('Сетевая ошибка: ' + e.message);
    document.getElementById('progressSection').style.display = 'none';
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(fetchResults, 1500);
}

async function fetchResults() {
  try {
    const res = await fetch('/api/niche/results');
    const data = await res.json();

    if (data.status === 'running') {
      const label = data.current_keyword
        ? `Анализирую: ${data.current_keyword}… (${data.progress}%)`
        : `Анализирую… (${data.progress}%)`;
      setProgress(data.progress, label);
      return;
    }

    clearInterval(pollTimer);
    pollTimer = null;
    document.getElementById('progressSection').style.display = 'none';

    if (data.status === 'done' && data.results.length > 0) {
      renderResults(data.results);
    } else if (data.status === 'idle') {
      setStatus('Нет результатов. Запустите анализ.');
    }
  } catch (e) {
    clearInterval(pollTimer);
    setStatus('Ошибка получения результатов: ' + e.message);
  }
}

function renderResults(results) {
  const tbody = document.getElementById('nicheTableBody');
  tbody.innerHTML = '';

  results.forEach((niche, idx) => {
    const score = niche.avg_score;
    const scoreClass = score >= 60 ? 'score-high' : score >= 30 ? 'score-mid' : 'score-low';
    const top = niche.top_community;
    const avgMembers = top ? Math.round(top.members / 1000) + 'к' : '—';
    const avgLikes = top ? top.avg_likes : '—';

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${idx + 1}</td>
      <td><strong>${niche.keyword}</strong></td>
      <td>${niche.count}</td>
      <td>${avgMembers}</td>
      <td>${avgLikes}</td>
      <td><span class="score-badge ${scoreClass}">${score}</span></td>
      <td>${top
        ? `<button class="btn btn-sm btn-secondary" onclick="addSource('${top.id}','${escHtml(top.name)}')">+ Добавить</button>`
        : '—'
      }</td>
    `;
    tbody.appendChild(tr);
  });

  document.getElementById('resultsSection').style.display = 'block';
  setStatus(`Найдено ${results.length} ниш. Нажмите «+ Добавить» чтобы добавить топ-сообщество как источник.`);
}

async function addSource(communityId, name) {
  try {
    const res = await fetch('/api/niche/add-source', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({community_id: communityId, name}),
    });
    const data = await res.json();
    if (data.status === 'ok') {
      setStatus(`✅ Источник «${name}» добавлен!`);
    } else {
      setStatus('⚠️ ' + data.message);
    }
  } catch (e) {
    setStatus('Ошибка: ' + e.message);
  }
}

function setProgress(pct, label) {
  document.getElementById('progressFill').style.width = pct + '%';
  document.getElementById('progressLabel').textContent = label;
}

function setStatus(msg) {
  document.getElementById('statusMsg').textContent = msg;
}

function escHtml(str) {
  return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// При загрузке — проверить есть ли уже результаты
fetchResults();
</script>
</body>
</html>
```

- [ ] **Step 2: Проверить страницу в браузере**

Запусти сервер и открой `http://localhost:8000/niche`. Должна открыться страница с полем ввода и двумя кнопками. Консоль браузера должна быть без ошибок.

- [ ] **Step 3: Commit**

```bash
git add frontend/niche.html
git commit -m "feat: add niche analyzer frontend page"
```

---

## Task 7: End-to-end проверка

- [ ] **Step 1: Запустить бот**

```bash
python main.py
```

- [ ] **Step 2: Открыть страницу анализа**

Перейди на `http://localhost:8000/niche`.

- [ ] **Step 3: Проверить авто-обзор**

Нажми «⚡ Авто-обзор топ-ниш». Прогресс-бар должен появиться и начать ползти. Статус должен показывать текущую нишу («Анализирую: юмор…»).

- [ ] **Step 4: Дождаться результатов**

После завершения должна появиться таблица с нишами, отсортированными по скору. Хотя бы 5 строк с ненулевым счётом.

- [ ] **Step 5: Проверить добавление источника**

Нажми «+ Добавить» у любой ниши. Должно появиться сообщение «✅ Источник ... добавлен!».

- [ ] **Step 6: Проверить что источник сохранился**

Перейди на главную страницу (`/`), открой вкладку «Каналы» / «Настройки» и убедись что новый источник появился в списке.

- [ ] **Step 7: Проверить защиту от дублей**

Нажми «+ Добавить» у той же ниши ещё раз. Должно появиться «⚠️ Источник уже добавлен».

- [ ] **Step 8: Проверить защиту от двойного запуска**

Пока идёт сканирование, открой второй таб и нажми «Авто-обзор». API должен вернуть `{"status":"error","message":"Анализ уже запущен"}`.

- [ ] **Step 9: Final commit**

```bash
git add -A
git commit -m "feat: niche analyzer — full implementation complete"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** services/niche_analyzer.py покрывает скор-формулу из спека ✓; роутер покрывает все три endpoint ✓; UI покрывает ввод + прогресс + таблица + кнопка «Добавить» ✓; защита от закрытых групп (ошибки 15/19/7) ✓; rate limit 0.35с ✓; защита от двойного запуска ✓; автосписок 20 ниш ✓
- [x] **Placeholders:** нет TBD/TODO — весь код полный
- [x] **Type consistency:** `run_niche_scan(keywords: List[str])` → везде передаётся `List[str]`; `app_state.niche_results: List[Dict]` → читается в роутере как `app_state.niche_results`; `community_id` передаётся как `str` и читается как `str` везде
