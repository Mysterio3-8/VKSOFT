# Growth Autopilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a separate Growth Autopilot page and read-only/dry-run backend that can score VK post candidates, avoid global duplicates, and propose schedules without changing the existing production download/publish flow.

**Architecture:** Add a focused `services/growth_autopilot.py` module for pure logic and storage-backed reports, an `api/growth_autopilot.py` router for UI calls, and a standalone `frontend/growth-autopilot.html` page. Register the route in `main.py` and add one sidebar link in `frontend/index.html`; existing `/download`, `/publish`, `/autopilot`, and `/growth` behavior remains untouched.

**Tech Stack:** Python 3, FastAPI, pytest, plain HTML/CSS/JS, existing `vk.api`, `app_state`, and JSON files under `storage/{profile_id}`.

---

## File Structure

- Create `services/growth_autopilot.py`: pure scoring, settings defaults, report building, anti-duplicate helpers, and storage helpers.
- Create `api/growth_autopilot.py`: FastAPI endpoints for status and dry-run/read-only run.
- Create `frontend/growth-autopilot.html`: separate page with simple mode, expert settings, status cards, and candidate table.
- Modify `main.py`: include the new API router and serve `/growth-autopilot`.
- Modify `frontend/index.html`: add a sidebar link to the separate Growth Autopilot page.
- Create `tests/test_growth_autopilot.py`: unit tests for scoring, scheduling, anti-duplicates, and report behavior.

---

### Task 1: Growth Settings, Scoring, And Scheduling

**Files:**
- Create: `services/growth_autopilot.py`
- Test: `tests/test_growth_autopilot.py`

- [ ] **Step 1: Write failing tests for defaults, scoring, and schedule**

Add this to `tests/test_growth_autopilot.py`:

```python
# -*- coding: utf-8 -*-

from services.growth_autopilot import (
    DEFAULT_GROWTH_SETTINGS,
    build_schedule_preview,
    score_candidate,
)


def test_default_growth_settings_keep_24_as_preset_not_constant():
    assert DEFAULT_GROWTH_SETTINGS["preset"] == "custom"
    assert DEFAULT_GROWTH_SETTINGS["posts_per_day_min"] == 12
    assert DEFAULT_GROWTH_SETTINGS["posts_per_day_max"] == 24
    assert 24 in DEFAULT_GROWTH_SETTINGS["preset_values"].values()


def test_score_candidate_rewards_viral_signals_and_explains_reasons():
    strong = {
        "id": 10,
        "owner_id": -123,
        "date": 1893456000,
        "text": "Useful viral text",
        "likes": {"count": 200},
        "reposts": {"count": 30},
        "comments": {"count": 15},
        "views": {"count": 5000},
        "attachments": [{"type": "photo"}],
    }
    weak = {
        "id": 11,
        "owner_id": -123,
        "date": 1893456000,
        "text": "x",
        "likes": {"count": 1},
        "reposts": {"count": 0},
        "comments": {"count": 0},
        "views": {"count": 100},
        "attachments": [],
    }

    strong_score = score_candidate(strong, source_id="123")
    weak_score = score_candidate(weak, source_id="123")

    assert strong_score["viral_score"] > weak_score["viral_score"]
    assert strong_score["source_id"] == "123"
    assert strong_score["post_id"] == 10
    assert strong_score["reasons"]


def test_build_schedule_preview_uses_bounds_and_randomized_intervals():
    candidates = [
        {"file": f"post_{i}.json", "viral_score": 80 - i, "post_id": i}
        for i in range(10)
    ]
    settings = {
        "posts_per_day_min": 3,
        "posts_per_day_max": 5,
        "allowed_hours_start": 8,
        "allowed_hours_end": 22,
        "interval_jitter_min": 15,
        "queue_days": 1,
    }

    schedule = build_schedule_preview(candidates, settings, start_ts=1893456000)

    assert 3 <= len(schedule) <= 5
    assert all(item["file"].endswith(".json") for item in schedule)
    assert all("publish_at" in item for item in schedule)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_growth_autopilot.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'services.growth_autopilot'`.

- [ ] **Step 3: Implement minimal settings, scoring, and schedule logic**

Create `services/growth_autopilot.py`:

```python
# -*- coding: utf-8 -*-
"""Read-only Growth Autopilot logic.

This module is intentionally side-effect-light. It scores existing/local posts,
builds reports, and writes only Growth Autopilot report files unless a later
queue/live mode explicitly calls existing production workers.
"""

import hashlib
import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from config import STORAGE_DIR, app_state


DEFAULT_GROWTH_SETTINGS = {
    "source_mode": "single",
    "single_source_id": "",
    "preset": "custom",
    "preset_values": {
        "careful": 4,
        "active": 10,
        "aggressive": 18,
        "max_24": 24,
    },
    "posts_per_day_min": 12,
    "posts_per_day_max": 24,
    "allowed_hours_start": 8,
    "allowed_hours_end": 23,
    "interval_jitter_min": 20,
    "queue_days": 1,
    "postponed_limit": 140,
    "min_viral_score": 30,
    "global_dedup": True,
    
    "run_mode": "dry_run",
    "shortage_strategy": "improve_then_reduce",
}


BAD_TEXT_MARKERS = (
    "реклама", "продам", "скидка", "казино", "ставки", "18+",
    "подпишись на меня", "заработок",
)


def _profile_dir(profile_id: Optional[str] = None) -> Path:
    return STORAGE_DIR / (profile_id or app_state.active_profile_id)


def report_file(profile_id: Optional[str] = None) -> Path:
    return _profile_dir(profile_id) / "growth_autopilot_report.json"


def global_dedup_file() -> Path:
    return STORAGE_DIR / "global_used_posts.json"


def load_growth_settings(profile: Optional[Dict] = None) -> Dict:
    profile = profile or app_state.profile
    settings = DEFAULT_GROWTH_SETTINGS.copy()
    settings.update(profile.get("growth_autopilot", {}) or {})
    return normalize_settings(settings)


def normalize_settings(settings: Dict) -> Dict:
    result = DEFAULT_GROWTH_SETTINGS.copy()
    result.update(settings or {})
    for key in ("posts_per_day_min", "posts_per_day_max", "allowed_hours_start", "allowed_hours_end", "queue_days"):
        try:
            result[key] = int(result.get(key, DEFAULT_GROWTH_SETTINGS[key]))
        except Exception:
            result[key] = DEFAULT_GROWTH_SETTINGS[key]
    if result["posts_per_day_min"] < 1:
        result["posts_per_day_min"] = 1
    if result["posts_per_day_max"] < result["posts_per_day_min"]:
        result["posts_per_day_max"] = result["posts_per_day_min"]
    result["allowed_hours_start"] = max(0, min(23, result["allowed_hours_start"]))
    result["allowed_hours_end"] = max(0, min(23, result["allowed_hours_end"]))
    if result["allowed_hours_end"] <= result["allowed_hours_start"]:
        result["allowed_hours_end"] = 23
    return result


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _post_text(post: Dict) -> str:
    return (post.get("text") or "").strip()


def _attachment_counts(post: Dict) -> Dict:
    photos = len(post.get("_local_photos") or [])
    videos = len(post.get("_vk_videos") or [])
    for att in post.get("attachments", []) or []:
        if att.get("type") == "photo":
            photos += 1
        if att.get("type") == "video":
            videos += 1
    return {"photos": photos, "videos": videos}


def is_bad_text(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in BAD_TEXT_MARKERS)


def text_fingerprint(text: str) -> str:
    cleaned = " ".join((text or "").lower().split())
    return hashlib.sha1(cleaned.encode("utf-8")).hexdigest()


def source_post_key(post: Dict, source_id: str = "") -> str:
    owner = str(post.get("owner_id") or source_id or "").lstrip("-")
    post_id = str(post.get("id") or post.get("post_id") or "")
    return f"{owner}_{post_id}" if owner and post_id else text_fingerprint(_post_text(post))


def score_candidate(post: Dict, source_id: str = "", source_weight: float = 0) -> Dict:
    likes = _safe_int(post.get("likes", {}).get("count", 0))
    reposts = _safe_int(post.get("reposts", {}).get("count", 0))
    comments = _safe_int(post.get("comments", {}).get("count", 0))
    views = _safe_int(post.get("views", {}).get("count", 0))
    post_ts = _safe_int(post.get("date", 0))
    age_hours = max(0, (int(time.time()) - post_ts) / 3600) if post_ts else 72
    text = _post_text(post)
    media = _attachment_counts(post)
    er = (likes + reposts * 2 + comments * 1.5) / max(views, 1) * 100 if views else 0

    score = 15
    score += min(likes * 0.8, 28)
    score += min(reposts * 3.0, 24)
    score += min(comments * 2.0, 16)
    score += min(views / 250, 20)
    score += min(er * 8, 18)
    score += max(0, 18 - min(age_hours / 8, 18))
    score += min(float(source_weight or 0), 12)
    score += min(media["photos"] * 4, 14)
    score += 6 if 20 <= len(text) <= 700 else 2 if text else 0
    if is_bad_text(text):
        score -= 35

    reasons = []
    if likes:
        reasons.append(f"{likes} likes")
    if reposts:
        reasons.append(f"{reposts} reposts")
    if comments:
        reasons.append(f"{comments} comments")
    if views:
        reasons.append(f"{views} views")
    if media["photos"]:
        reasons.append(f"{media['photos']} photos")
    if er:
        reasons.append(f"{er:.2f}% ER")
    if is_bad_text(text):
        reasons.append("bad text marker")

    return {
        "source_id": str(source_id or post.get("owner_id", "")).lstrip("-"),
        "post_id": post.get("id") or post.get("post_id"),
        "owner_id": post.get("owner_id"),
        "file": post.get("_file", ""),
        "viral_score": round(max(score, 0), 1),
        "likes": likes,
        "reposts": reposts,
        "comments": comments,
        "views": views,
        "photos": media["photos"],
        "videos": media["videos"],
        "text_preview": text[:180],
        "fingerprint": text_fingerprint(text),
        "dedup_key": source_post_key(post, source_id),
        "reasons": reasons[:6],
    }


def _push_to_allowed_window(ts: int, start_h: int, end_h: int) -> int:
    d = datetime.fromtimestamp(ts)
    if d.hour < start_h:
        d = d.replace(hour=start_h, minute=random.randint(0, 50), second=random.randint(0, 59))
    elif d.hour >= end_h:
        d = (d + timedelta(days=1)).replace(hour=start_h, minute=random.randint(0, 50), second=random.randint(0, 59))
    return int(d.timestamp())


def build_schedule_preview(candidates: List[Dict], settings: Dict, start_ts: Optional[int] = None) -> List[Dict]:
    settings = normalize_settings(settings)
    if not candidates:
        return []
    daily_limit = random.randint(settings["posts_per_day_min"], settings["posts_per_day_max"])
    limit = min(len(candidates), daily_limit * max(1, settings["queue_days"]))
    start_ts = start_ts or int(time.time())
    start_h = settings["allowed_hours_start"]
    end_h = settings["allowed_hours_end"]
    active_seconds = max(3600, (end_h - start_h) * 3600)
    base_interval = max(900, active_seconds // max(daily_limit, 1))
    jitter = max(0, _safe_int(settings.get("interval_jitter_min", 20), 20) * 60)

    next_ts = _push_to_allowed_window(start_ts, start_h, end_h)
    result = []
    for cand in candidates[:limit]:
        next_ts = _push_to_allowed_window(next_ts, start_h, end_h)
        result.append({
            "file": cand.get("file", ""),
            "post_id": cand.get("post_id"),
            "source_id": cand.get("source_id"),
            "viral_score": cand.get("viral_score", 0),
            "publish_ts": next_ts,
            "publish_at": datetime.fromtimestamp(next_ts).strftime("%d.%m.%Y %H:%M"),
        })
        delta = base_interval + random.randint(-jitter, jitter) if jitter else base_interval
        next_ts += max(900, delta)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_growth_autopilot.py -v`

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add services/growth_autopilot.py tests/test_growth_autopilot.py
git commit -m "Add growth autopilot scoring"
```

---

### Task 2: Global Anti-Duplicate And Report Builder

**Files:**
- Modify: `services/growth_autopilot.py`
- Modify: `tests/test_growth_autopilot.py`

- [ ] **Step 1: Write failing tests for anti-duplicates and read-only reports**

Append to `tests/test_growth_autopilot.py`:

```python
from pathlib import Path

from services.growth_autopilot import (
    build_readonly_report,
    filter_global_duplicates,
    load_used_posts,
    mark_used_post,
)


def test_global_dedup_filters_used_post(tmp_path):
    used_file = tmp_path / "used.json"
    mark_used_post({"dedup_key": "1_10", "source_id": "1", "post_id": 10}, used_file=used_file, profile_id="p1")
    candidates = [
        {"dedup_key": "1_10", "viral_score": 90},
        {"dedup_key": "1_11", "viral_score": 80},
    ]

    filtered = filter_global_duplicates(candidates, used_file=used_file)

    assert [item["dedup_key"] for item in filtered] == ["1_11"]
    assert "1_10" in load_used_posts(used_file)


def test_build_readonly_report_scores_local_queue(tmp_path):
    posts_dir = tmp_path / "posts"
    posts_dir.mkdir()
    (posts_dir / "123_10.json").write_text(
        '{"id": 10, "owner_id": -123, "text": "Nice post", "likes": {"count": 20}, "views": {"count": 500}, "attachments": [{"type": "photo"}]}',
        encoding="utf-8",
    )

    report = build_readonly_report(posts_dir=posts_dir, settings={"posts_per_day_min": 1, "posts_per_day_max": 1})

    assert report["status"] == "ok"
    assert report["summary"]["candidate_count"] == 1
    assert report["top_candidates"][0]["post_id"] == 10
    assert len(report["schedule_preview"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_growth_autopilot.py -v`

Expected: FAIL with missing functions.

- [ ] **Step 3: Add anti-duplicate and report functions**

Append to `services/growth_autopilot.py`:

```python
def load_used_posts(used_file: Optional[Path] = None) -> Dict:
    used_file = used_file or global_dedup_file()
    if used_file.exists():
        try:
            return json.loads(used_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_used_posts(data: Dict, used_file: Optional[Path] = None) -> None:
    used_file = used_file or global_dedup_file()
    used_file.parent.mkdir(parents=True, exist_ok=True)
    used_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_used_post(candidate: Dict, used_file: Optional[Path] = None, profile_id: Optional[str] = None) -> None:
    data = load_used_posts(used_file)
    key = candidate.get("dedup_key")
    if not key:
        return
    data[key] = {
        "source_id": candidate.get("source_id"),
        "post_id": candidate.get("post_id"),
        "profile_id": profile_id or app_state.active_profile_id,
        "used_at": datetime.now().isoformat(timespec="seconds"),
        "fingerprint": candidate.get("fingerprint", ""),
    }
    save_used_posts(data, used_file)


def filter_global_duplicates(candidates: List[Dict], used_file: Optional[Path] = None) -> List[Dict]:
    used = load_used_posts(used_file)
    return [item for item in candidates if item.get("dedup_key") not in used]


def _load_local_posts(posts_dir: Path) -> List[Dict]:
    posts = []
    for fp in sorted(posts_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            post = json.loads(fp.read_text(encoding="utf-8"))
            post["_file"] = fp.name
            posts.append(post)
        except Exception:
            continue
    return posts


def build_readonly_report(
    posts_dir: Optional[Path] = None,
    settings: Optional[Dict] = None,
    used_file: Optional[Path] = None,
) -> Dict:
    settings = normalize_settings(settings or load_growth_settings())
    posts_dir = posts_dir or app_state.posts_dir
    posts = _load_local_posts(posts_dir)
    candidates = [score_candidate(post, source_id=str(post.get("owner_id", "")).lstrip("-")) for post in posts]
    candidates = [c for c in candidates if c["viral_score"] >= float(settings.get("min_viral_score", 30))]
    if settings.get("global_dedup", True):
        candidates = filter_global_duplicates(candidates, used_file=used_file)
    candidates.sort(key=lambda c: c["viral_score"], reverse=True)
    schedule = build_schedule_preview(candidates, settings)

    report = {
        "status": "ok",
        "mode": "read_only",
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "settings": settings,
        "summary": {
            "queue_files": len(posts),
            "candidate_count": len(candidates),
            "scheduled_preview": len(schedule),
            "min_viral_score": settings.get("min_viral_score", 30),
        },
        "checks": build_technical_checks(),
        "top_candidates": candidates[:50],
        "schedule_preview": schedule,
    }
    save_report(report)
    return report


def build_technical_checks() -> List[Dict]:
    profile = app_state.profile
    vk_cfg = profile.get("vk", {})
    sources = [s for s in profile.get("sources", []) if s.get("enabled", True)]
    return [
        {"name": "User Token", "ok": bool(vk_cfg.get("user_token", "").strip())},
        {"name": "Group Token", "ok": bool(vk_cfg.get("group_token", "").strip())},
        {"name": "Group ID", "ok": bool(vk_cfg.get("group_id", "").strip())},
        {"name": "Sources", "ok": bool(sources), "value": len(sources)},
        {"name": "Queue", "ok": app_state.posts_dir.exists(), "value": len(list(app_state.posts_dir.glob("*.json")))},
    ]


def save_report(report: Dict) -> Dict:
    fp = report_file()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def load_report() -> Dict:
    fp = report_file()
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_growth_autopilot.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add services/growth_autopilot.py tests/test_growth_autopilot.py
git commit -m "Add growth autopilot reports"
```

---

### Task 3: API Router

**Files:**
- Create: `api/growth_autopilot.py`
- Modify: `main.py`

- [ ] **Step 1: Create API router**

Create `api/growth_autopilot.py`:

```python
# -*- coding: utf-8 -*-
"""Growth Autopilot API."""

from fastapi import APIRouter

from config import app_state
from services.growth_autopilot import (
    build_readonly_report,
    load_growth_settings,
    load_report,
)

router = APIRouter()


@router.get("/growth-autopilot/status")
async def growth_autopilot_status():
    return {
        "status": "ok",
        "profile_id": app_state.active_profile_id,
        "settings": load_growth_settings(),
        "report": load_report(),
    }


@router.post("/growth-autopilot/run")
async def growth_autopilot_run(data: dict = {}):
    settings = load_growth_settings()
    settings.update(data.get("settings") or {})
    run_mode = data.get("run_mode") or settings.get("run_mode", "dry_run")
    if run_mode not in ("read_only", "dry_run"):
        run_mode = "dry_run"
    report = build_readonly_report(settings=settings)
    report["mode"] = run_mode
    return {"status": "ok", "report": report}
```

- [ ] **Step 2: Register router and page route in `main.py`**

Add imports and includes near the existing routers:

```python
from api.growth_autopilot import router as growth_autopilot_router

app.include_router(growth_autopilot_router, prefix='/api')
```

Add static route near `/niche`:

```python
@app.get('/growth-autopilot')
async def growth_autopilot_page():
    return FileResponse(FRONTEND_DIR / 'growth-autopilot.html')
```

- [ ] **Step 3: Run syntax check**

Run: `python -m py_compile main.py api/growth_autopilot.py services/growth_autopilot.py`

Expected: no output and exit code 0.

- [ ] **Step 4: Commit**

Run:

```bash
git add api/growth_autopilot.py main.py
git commit -m "Add growth autopilot API"
```

---

### Task 4: Separate Frontend Page

**Files:**
- Create: `frontend/growth-autopilot.html`
- Modify: `frontend/index.html`

- [ ] **Step 1: Add the standalone page**

Create `frontend/growth-autopilot.html`:

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Growth Autopilot</title>
  <link rel="stylesheet" href="/style.css?v=growth-autopilot-20260604">
</head>
<body>
<main class="main" style="margin-left:0">
  <div class="topbar">
    <span class="topbar-title">Growth Autopilot</span>
    <div class="topbar-actions">
      <button class="btn btn-ghost btn-sm" onclick="location.href='/'">Назад</button>
      <button class="btn btn-ghost btn-sm" onclick="loadStatus()">Обновить</button>
    </div>
  </div>

  <div class="content-area">
    <section class="card">
      <div class="card-header">
        <div class="card-title"><span class="icon">G</span>Раскачать паблик</div>
      </div>
      <div class="form-section">
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Режим источника</label>
            <select class="form-input" id="sourceMode">
              <option value="single">Один источник</option>
              <option value="approved">Одобренные источники</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Один источник VK</label>
            <input class="form-input" id="singleSourceId" placeholder="ID сообщества">
          </div>
          <div class="form-group">
            <label class="form-label">Режим запуска</label>
            <select class="form-input" id="runMode">
              <option value="dry_run">Dry-run</option>
              <option value="read_only">Read-only</option>
            </select>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Мин постов/день</label>
            <input class="form-input" id="postsMin" type="number" min="1" value="12">
          </div>
          <div class="form-group">
            <label class="form-label">Макс постов/день</label>
            <input class="form-input" id="postsMax" type="number" min="1" value="24">
          </div>
          <div class="form-group">
            <label class="form-label">Мин. viral score</label>
            <input class="form-input" id="minScore" type="number" min="0" value="30">
          </div>
        </div>
        <button class="btn btn-primary btn-lg" onclick="runGrowth()">Раскачать паблик</button>
        <span id="statusText" class="form-hint"></span>
      </div>
    </section>

    <section class="dashboard-grid" style="margin-top:16px">
      <div class="stat-card">
        <div class="stat-label">Кандидатов</div>
        <div class="stat-value" id="candidateCount">0</div>
        <div class="stat-sub">после фильтров</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Запланировано</div>
        <div class="stat-value" id="scheduledCount">0</div>
        <div class="stat-sub">dry-run</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Очередь</div>
        <div class="stat-value" id="queueCountGa">0</div>
        <div class="stat-sub">локальных файлов</div>
      </div>
    </section>

    <section class="card" style="margin-top:16px">
      <div class="card-header"><div class="card-title">Технические проверки</div></div>
      <div id="checksList" class="form-section"></div>
    </section>

    <section class="card" style="margin-top:16px">
      <div class="card-header"><div class="card-title">Лучшие кандидаты</div></div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>Score</th><th>Источник</th><th>Пост</th><th>Причины</th><th>Текст</th></tr></thead>
          <tbody id="candidatesBody"></tbody>
        </table>
      </div>
    </section>

    <section class="card" style="margin-top:16px">
      <div class="card-header"><div class="card-title">План публикаций</div></div>
      <div id="scheduleList" class="form-section"></div>
    </section>
  </div>
</main>

<script>
const api = (path, options = {}) => fetch('/api' + path, {
  headers: {'Content-Type': 'application/json'},
  ...options
}).then(r => r.json());

function settingsFromForm() {
  return {
    source_mode: document.getElementById('sourceMode').value,
    single_source_id: document.getElementById('singleSourceId').value.trim(),
    posts_per_day_min: Number(document.getElementById('postsMin').value || 12),
    posts_per_day_max: Number(document.getElementById('postsMax').value || 24),
    min_viral_score: Number(document.getElementById('minScore').value || 30)
  };
}

function renderReport(report) {
  const summary = report.summary || {};
  document.getElementById('candidateCount').textContent = summary.candidate_count || 0;
  document.getElementById('scheduledCount').textContent = summary.scheduled_preview || 0;
  document.getElementById('queueCountGa').textContent = summary.queue_files || 0;
  document.getElementById('statusText').textContent = report.generated_at ? `Отчет: ${report.generated_at}` : '';

  document.getElementById('checksList').innerHTML = (report.checks || []).map(item =>
    `<div class="health-item">${item.ok ? 'OK' : 'STOP'}: <b>${item.name}</b> ${item.value ?? ''}</div>`
  ).join('');

  document.getElementById('candidatesBody').innerHTML = (report.top_candidates || []).slice(0, 30).map(item =>
    `<tr><td><b>${item.viral_score}</b></td><td>${item.source_id || '-'}</td><td>${item.post_id || '-'}</td><td>${(item.reasons || []).join(', ')}</td><td>${item.text_preview || ''}</td></tr>`
  ).join('');

  document.getElementById('scheduleList').innerHTML = (report.schedule_preview || []).map(item =>
    `<div class="source-item"><b>${item.publish_at}</b> · score ${item.viral_score} · post ${item.post_id || item.file}</div>`
  ).join('');
}

async function loadStatus() {
  const data = await api('/growth-autopilot/status');
  if (data.settings) {
    document.getElementById('sourceMode').value = data.settings.source_mode || 'single';
    document.getElementById('singleSourceId').value = data.settings.single_source_id || '';
    document.getElementById('postsMin').value = data.settings.posts_per_day_min || 12;
    document.getElementById('postsMax').value = data.settings.posts_per_day_max || 24;
    document.getElementById('minScore').value = data.settings.min_viral_score || 30;
  }
  if (data.report && data.report.status) renderReport(data.report);
}

async function runGrowth() {
  document.getElementById('statusText').textContent = 'Анализирую...';
  const data = await api('/growth-autopilot/run', {
    method: 'POST',
    body: JSON.stringify({
      run_mode: document.getElementById('runMode').value,
      settings: settingsFromForm()
    })
  });
  if (data.status !== 'ok') {
    document.getElementById('statusText').textContent = data.message || 'Ошибка';
    return;
  }
  renderReport(data.report);
}

loadStatus();
</script>
</body>
</html>
```

- [ ] **Step 2: Add sidebar link**

In `frontend/index.html`, add this near the existing `/niche` link:

```html
<button class="nav-item" onclick="window.location='/growth-autopilot'"><span class="nav-icon">GA</span><span>Growth</span></button>
```

- [ ] **Step 3: Run static smoke check**

Run: `python -m py_compile main.py api/growth_autopilot.py services/growth_autopilot.py`

Expected: no output and exit code 0.

- [ ] **Step 4: Commit**

Run:

```bash
git add frontend/growth-autopilot.html frontend/index.html
git commit -m "Add growth autopilot page"
```

---

### Task 5: Verification

**Files:**
- No new files.

- [ ] **Step 1: Run unit tests**

Run: `pytest tests/test_growth_autopilot.py -v`

Expected: all Growth Autopilot tests PASS.

- [ ] **Step 2: Run syntax checks**

Run: `python -m py_compile main.py api/growth_autopilot.py services/growth_autopilot.py`

Expected: no output and exit code 0.

- [ ] **Step 3: Start local server**

Run: `python main.py`

Expected: server starts on `http://localhost:8000`.

- [ ] **Step 4: Browser smoke test**

Open `http://localhost:8000/growth-autopilot`.

Expected:
- page loads;
- `Раскачать паблик` button is visible;
- status request to `/api/growth-autopilot/status` returns `status: ok`;
- dry-run does not publish or mutate the existing production queue;
- old dashboard remains reachable at `http://localhost:8000`.

- [ ] **Step 5: Final git status check**

Run: `git status --short`

Expected: only pre-existing unrelated dirty files remain, plus any intentional Growth Autopilot files if not yet committed.

---

## Self-Review

Spec coverage:
- Separate page: Task 4.
- Do not break production flow: Tasks 3 and 4 only register new route/link; no existing download/publish logic is changed.
- One source or approved sources: settings and page fields in Tasks 1 and 4; first implementation reads local queue, queue/live remains out of first safe slice.
- Global anti-duplicate: Task 2.
- Adjustable tempo and 24/day as preset: Task 1 and Task 4.
- Metrics learning: not implemented in this first read-only/dry-run slice; existing `services.tracker` remains available for a later task.
- External models are not used; recommendations are algorithmic.

Intentional first-slice gaps:
- Queue/live mutation is not implemented to protect production.
- Growth metric learning is not implemented in this first pass; no existing tracker behavior is changed.

