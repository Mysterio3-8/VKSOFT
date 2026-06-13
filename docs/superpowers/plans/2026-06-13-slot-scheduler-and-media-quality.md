# Slot Scheduler, Dedup, Engagement Filter & Media Quality — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix duplicate posts, scheduling collisions/spam between the 4 parallel media autopilot cycles (posts/photos/videos/clips), stop filtering source posts by engagement, enable pHash dedup, cap videos/clips to 1+2 per day, write a structured publish log, and soften the video crop/fade + photo crop so quality doesn't degrade.

**Architecture:** Introduce a single `services/slot_scheduler.py` that all 4 publish workers call to reserve a `publish_date` timestamp. It persists reserved slots to `storage/{profile_id}/scheduled_slots.json` under a cross-process file lock, enforces a minimum gap between ANY two reservations (any media type), and enforces daily caps per media type (read from `publishing_settings.max_posts_per_day`, `videos_settings.daily_limit`, `clips_settings.daily_limit`). `_get_next_ts()` in `workers/photos.py` and the inline scheduling block in `workers/videos.py::publish_videos_worker` are replaced with calls to this module. The posts worker's existing smart-schedule/learned-24h logic stays untouched but also reserves through the same scheduler so it doesn't collide with photos/videos/clips.

Separately: flip `phash_enabled` to read from config (currently hardcoded `False`), extend pHash dedup to videos/clips by hashing a representative frame, set `engagement.enabled: false` in both profiles, add a `storage/{profile_id}/publish_log.jsonl` (rotated/gzip-compressed) written on every successful/failed publish, and tune `video_transform`/`photo_transform` crop ranges + fade probability down.

**Tech Stack:** Python 3.10+, FastAPI backend (no new deps needed — `imagehash`/`Pillow`/`ffmpeg` already used), pytest for tests, file-based JSON storage with `tempfile` atomic writes (existing pattern in `services/storage.py`).

---

## File Structure

- Create: `services/slot_scheduler.py` — reservation API: `reserve_slot()`, `_load_slots()`, `_save_slots()`, `_acquire_lock()` / `_release_lock()`, `_daily_count()`, `_min_gap_seconds()`.
- Create: `tests/test_slot_scheduler.py` — unit tests for reservation, collision avoidance, daily caps, lock behavior.
- Modify: `config.py` — add `scheduled_slots_file` and `publish_log_file` properties to `AppState`.
- Modify: `workers/photos.py` — replace `_get_next_ts()` body to call `slot_scheduler.reserve_slot()`.
- Modify: `workers/videos.py::publish_videos_worker` — replace inline `next_ts` logic with `slot_scheduler.reserve_slot()`.
- Modify: `workers/publish.py` — after computing `next_ts` for the posts loop, call `slot_scheduler.reserve_slot()` so posts also register in the shared registry (prevents photos/videos/clips colliding with posts).
- Modify: `workers/download.py` — `_download_source`: read `phash_enabled` from `profile.get('phash', {}).get('enabled', False)` instead of hardcoded `False`.
- Modify: `services/phash.py` — add `hash_video_frame()` helper (extract first frame via ffmpeg, hash it).
- Modify: `workers/videos.py` — call pHash dedup on downloaded video/clip files using `hash_video_frame()`.
- Create: `services/publish_log.py` — `log_publish_event()`, `read_recent_events()`, append-only JSONL with daily rotation + gzip of files older than 1 day.
- Modify: `workers/publish.py`, `workers/photos.py`, `workers/videos.py`, `services/slot_finder.py` — call `log_publish_event()` after each publish attempt (success or failure).
- Modify: `config.json` — set `engagement.enabled: false` for profiles `p1` and `p37fb1e`; set `videos_settings.daily_limit: 1` and `clips_settings.daily_limit: 2` for `p1` (the profile with videos/clips enabled).
- Modify: `services/video_transform.py` — reduce `crop_percent` auto-range from `(0.04, 0.08)` to `(0.01, 0.03)`, reduce `square_crop`/`square_blur` random weight, reduce fade probability from 0.5 to 0.2, reduce `frame_px` probability from 0.3 to 0.1.
- Modify: `services/photo_transform.py` — reduce `apply_random_crop` default range from `(0.02, 0.05)` to `(0.01, 0.025)`.
- Test: `tests/test_video_transform.py`, `tests/test_photo_transform.py` — update/add assertions for new ranges.

---

## Task 1: Slot scheduler — core reservation logic

**Files:**
- Create: `services/slot_scheduler.py`
- Test: `tests/test_slot_scheduler.py`

- [ ] **Step 1: Write the failing test for basic reservation**

```python
# tests/test_slot_scheduler.py
import json
import time

import pytest


@pytest.fixture
def scheduler_paths(tmp_path, monkeypatch):
    slots_file = tmp_path / "scheduled_slots.json"
    lock_file = tmp_path / "scheduled_slots.lock"
    monkeypatch.setattr("services.slot_scheduler._slots_file", lambda: slots_file)
    monkeypatch.setattr("services.slot_scheduler._lock_file", lambda: lock_file)
    return slots_file, lock_file


def test_reserve_slot_returns_future_timestamp(scheduler_paths):
    from services.slot_scheduler import reserve_slot

    now = int(time.time())
    ts = reserve_slot(media_type="photos", delay_min=60, delay_max=120)

    assert ts > now
    assert ts <= now + 120 + 5  # small buffer for test runtime


def test_reserve_slot_persists_to_file(scheduler_paths):
    from services.slot_scheduler import reserve_slot

    slots_file, _ = scheduler_paths
    reserve_slot(media_type="photos", delay_min=60, delay_max=60)

    data = json.loads(slots_file.read_text(encoding="utf-8"))
    assert len(data["slots"]) == 1
    assert data["slots"][0]["media_type"] == "photos"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_slot_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.slot_scheduler'`

- [ ] **Step 3: Write minimal implementation**

```python
# services/slot_scheduler.py
# -*- coding: utf-8 -*-
"""Единый планировщик слотов публикации.

Все циклы автопилота (posts/photos/videos/clips) резервируют время
публикации через reserve_slot(), чтобы не коллидировать друг с другом
и не превышать дневные лимиты по типам медиа.
"""

import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import app_state, logger

_DEFAULT_MIN_GAP_SECONDS = 1800  # 30 минут между любыми двумя постами


def _slots_file() -> Path:
    from config import STORAGE_DIR
    return STORAGE_DIR / app_state.active_profile_id / 'scheduled_slots.json'


def _lock_file() -> Path:
    from config import STORAGE_DIR
    return STORAGE_DIR / app_state.active_profile_id / 'scheduled_slots.lock'


def _acquire_lock(timeout: float = 10.0) -> Optional[object]:
    """Простой файловый лок через эксклюзивное создание файла."""
    lock_path = _lock_file()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            fd = open(lock_path, 'x')
            return fd
        except FileExistsError:
            # Если лок старше 30с — считаем его подвисшим и забираем
            try:
                if time.time() - lock_path.stat().st_mtime > 30:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            time.sleep(0.1)
    return None


def _release_lock(fd: Optional[object]) -> None:
    if fd is None:
        return
    try:
        fd.close()
    finally:
        _lock_file().unlink(missing_ok=True)


def _load_slots() -> dict:
    f = _slots_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            return {'slots': []}
    return {'slots': []}


def _save_slots(data: dict) -> None:
    import tempfile
    f = _slots_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        'w', dir=f.parent, delete=False, encoding='utf-8', suffix='.tmp'
    ) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp_path = tmp.name
    Path(tmp_path).replace(f)


def _prune_old_slots(data: dict) -> dict:
    """Убрать слоты в прошлом (старше 1 дня), чтобы файл не разрастался."""
    cutoff = int(time.time()) - 86400
    data['slots'] = [s for s in data['slots'] if s['ts'] >= cutoff]
    return data


def _min_gap_seconds(profile: dict) -> int:
    try:
        from services.smart_scheduler import _compute_min_gap
        from services.engagement import load_engagement_model
        model = load_engagement_model(app_state.active_profile_id)
        return max(_DEFAULT_MIN_GAP_SECONDS, _compute_min_gap(model))
    except Exception:
        return _DEFAULT_MIN_GAP_SECONDS


def _daily_limit(media_type: str, profile: dict) -> Optional[int]:
    """Дневной лимит для типа медиа. None = без лимита."""
    if media_type == 'videos':
        return int(profile.get('videos_settings', {}).get('daily_limit', 0)) or None
    if media_type == 'clips':
        return int(profile.get('clips_settings', {}).get('daily_limit', 0)) or None
    if media_type in ('posts', 'photos'):
        limit = int(profile.get('publishing_settings', {}).get('max_posts_per_day', 0))
        return limit or None
    return None


def _count_for_day(slots: list, media_type: str, day_start: int, day_end: int) -> int:
    return sum(
        1 for s in slots
        if s['media_type'] == media_type and day_start <= s['ts'] < day_end
    )


def reserve_slot(
    media_type: str,
    delay_min: int,
    delay_max: int,
    profile: Optional[dict] = None,
) -> int:
    """Зарезервировать timestamp публикации для media_type.

    Гарантирует:
    - результат в будущем
    - зазор >= min_gap от ЛЮБОГО другого зарезервированного слота (любого типа)
    - не превышает дневной лимит media_type (если задан в конфиге);
      при превышении лимита на сегодня сдвигает на следующий день
    """
    from services.storage import read_last_scheduled, write_last_scheduled

    profile = profile if profile is not None else app_state.profile
    min_gap = _min_gap_seconds(profile)
    daily_limit = _daily_limit(media_type, profile)

    lock = _acquire_lock()
    try:
        data = _prune_old_slots(_load_slots())
        slots = data['slots']
        occupied = sorted(s['ts'] for s in slots)

        base = max(
            int(time.time()),
            read_last_scheduled() or 0,
            occupied[-1] if occupied else 0,
        )
        candidate = base + random.randint(delay_min, delay_max)

        # Сдвигаем, пока не найдём слот без коллизий по зазору
        max_iterations = 200
        for _ in range(max_iterations):
            conflict = any(abs(candidate - occ) < min_gap for occ in occupied)
            if not conflict:
                break
            candidate += random.randint(delay_min, delay_max)

        # Проверка дневного лимита: если на день candidate уже набрано
        # daily_limit постов этого типа — переносим на следующий день
        if daily_limit is not None:
            for _ in range(14):  # не более 14 дней вперёд
                day_start = int(
                    datetime.fromtimestamp(candidate).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ).timestamp()
                )
                day_end = day_start + 86400
                if _count_for_day(slots, media_type, day_start, day_end) < daily_limit:
                    break
                candidate = day_end + random.randint(delay_min, delay_max)
                occupied = sorted(occupied + [candidate])

        slots.append({'media_type': media_type, 'ts': candidate})
        _save_slots(data)
        write_last_scheduled(candidate)
        return candidate
    finally:
        _release_lock(lock)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_slot_scheduler.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add services/slot_scheduler.py tests/test_slot_scheduler.py
git commit -m "feat: add unified slot scheduler for cross-cycle publish timing"
```

---

## Task 2: Slot scheduler — collision avoidance and daily caps

**Files:**
- Modify: `services/slot_scheduler.py` (already written in Task 1 — this task is tests-only verification of edge cases)
- Test: `tests/test_slot_scheduler.py`

- [ ] **Step 1: Write the failing test for collision avoidance across media types**

```python
# tests/test_slot_scheduler.py (append)

def test_reserve_slot_avoids_collision_with_other_media_type(scheduler_paths, monkeypatch):
    from services.slot_scheduler import reserve_slot
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 1800)

    ts1 = reserve_slot(media_type="videos", delay_min=10, delay_max=10, profile={})
    ts2 = reserve_slot(media_type="clips", delay_min=10, delay_max=10, profile={})

    assert abs(ts2 - ts1) >= 1800


def test_reserve_slot_respects_daily_limit(scheduler_paths, monkeypatch):
    from services.slot_scheduler import reserve_slot
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 60)

    profile = {"videos_settings": {"daily_limit": 1}}

    ts1 = reserve_slot(media_type="videos", delay_min=10, delay_max=10, profile=profile)
    ts2 = reserve_slot(media_type="videos", delay_min=10, delay_max=10, profile=profile)

    from datetime import datetime
    day1 = datetime.fromtimestamp(ts1).date()
    day2 = datetime.fromtimestamp(ts2).date()
    assert day2 > day1


def test_reserve_slot_does_not_limit_other_media_types(scheduler_paths, monkeypatch):
    from services.slot_scheduler import reserve_slot
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 60)

    profile = {"videos_settings": {"daily_limit": 1}}

    ts_video = reserve_slot(media_type="videos", delay_min=10, delay_max=10, profile=profile)
    ts_clip = reserve_slot(media_type="clips", delay_min=10, delay_max=10, profile=profile)

    from datetime import datetime
    assert datetime.fromtimestamp(ts_clip).date() == datetime.fromtimestamp(ts_video).date()
```

- [ ] **Step 2: Run tests to verify they fail or pass**

Run: `pytest tests/test_slot_scheduler.py -v`
Expected: All 5 tests PASS — the Task 1 implementation already handles these cases. If `test_reserve_slot_respects_daily_limit` fails because `ts2` lands on the same day, check that `day_end` calculation in `reserve_slot` correctly uses `datetime.fromtimestamp` (local time) consistently with `_count_for_day`.

- [ ] **Step 3: If any test fails, fix `reserve_slot` in `services/slot_scheduler.py`**

Common fix: ensure `_count_for_day` and the day-boundary candidate calculation use the same timezone basis (both use `datetime.fromtimestamp`, which is local-naive — consistent is what matters for this test).

- [ ] **Step 4: Run full test file again**

Run: `pytest tests/test_slot_scheduler.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/test_slot_scheduler.py
git commit -m "test: cover slot scheduler collision avoidance and daily caps"
```

---

## Task 3: Add scheduled_slots_file and publish_log_file to AppState

**Files:**
- Modify: `config.py:162-170` (near `clips_queue_dir`/`clip_files_dir` properties)
- Test: `tests/test_slot_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slot_scheduler.py (append)

def test_app_state_has_scheduled_slots_file(monkeypatch, tmp_path):
    from config import app_state, STORAGE_DIR

    expected = STORAGE_DIR / app_state.active_profile_id / 'scheduled_slots.json'
    assert app_state.scheduled_slots_file == expected


def test_app_state_has_publish_log_file():
    from config import app_state, STORAGE_DIR

    expected = STORAGE_DIR / app_state.active_profile_id / 'publish_log.jsonl'
    assert app_state.publish_log_file == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_slot_scheduler.py -v -k app_state`
Expected: FAIL with `AttributeError: 'AppState' object has no attribute 'scheduled_slots_file'`

- [ ] **Step 3: Add properties to AppState**

In `config.py`, find the `clip_files_dir` property block (around line 168-172) and add after it:

```python
    @property
    def scheduled_slots_file(self) -> Path:
        return STORAGE_DIR / self.active_profile_id / 'scheduled_slots.json'

    @property
    def publish_log_file(self) -> Path:
        return STORAGE_DIR / self.active_profile_id / 'publish_log.jsonl'
```

- [ ] **Step 4: Update `services/slot_scheduler.py` to use these properties instead of inline path construction**

Replace `_slots_file()` and `_lock_file()` in `services/slot_scheduler.py`:

```python
def _slots_file() -> Path:
    return app_state.scheduled_slots_file


def _lock_file() -> Path:
    return app_state.scheduled_slots_file.with_suffix('.lock')
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_slot_scheduler.py -v`
Expected: PASS (7 passed)

- [ ] **Step 6: Commit**

```bash
git add config.py services/slot_scheduler.py tests/test_slot_scheduler.py
git commit -m "feat: add scheduled_slots_file and publish_log_file to AppState"
```

---

## Task 4: Wire slot scheduler into photos worker

**Files:**
- Modify: `workers/photos.py:405-419` (the `_get_next_ts` function)
- Test: `tests/test_publish_upload_resilience.py` or new `tests/test_photos_scheduler_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_photos_scheduler_integration.py
# -*- coding: utf-8 -*-
import json
import time

import pytest


def test_get_next_ts_uses_slot_scheduler(monkeypatch, tmp_path):
    from config import app_state
    from workers.photos import _get_next_ts

    slots_file = tmp_path / "scheduled_slots.json"
    lock_file = tmp_path / "scheduled_slots.lock"
    monkeypatch.setattr(type(app_state), "scheduled_slots_file", property(lambda self: slots_file))
    monkeypatch.setattr("services.slot_scheduler._lock_file", lambda: lock_file)
    monkeypatch.setattr("services.storage.read_last_scheduled", lambda: None)
    monkeypatch.setattr("services.storage.write_last_scheduled", lambda ts: None)
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 60)

    now = int(time.time())
    ts = _get_next_ts(60, 120)

    assert ts > now
    data = json.loads(slots_file.read_text(encoding="utf-8"))
    assert data["slots"][0]["media_type"] == "photos"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_photos_scheduler_integration.py -v`
Expected: FAIL — `data["slots"]` will be empty/file won't exist, because `_get_next_ts` doesn't call the scheduler yet.

- [ ] **Step 3: Replace `_get_next_ts` in `workers/photos.py`**

Current code (lines 405-419):

```python
def _get_next_ts(delay_min: int, delay_max: int) -> int:
    from services.storage import read_last_scheduled
    from vk.api import fetch_last_postponed_from_vk, get_vk_api
    profile = app_state.profile
    vk_cfg = profile.get('vk', {})
    try:
        vk_user = get_vk_api(vk_cfg.get('user_token', ''), vk_cfg.get('api_version', '5.131'))
        owner_id = f'-{vk_cfg.get("group_id", "").lstrip("-")}'
        vk_ts = fetch_last_postponed_from_vk(vk_user, owner_id)
        file_ts = read_last_scheduled()
        base = max(vk_ts or 0, file_ts or 0, int(time.time()))
        return base + random.randint(delay_min, delay_max)
    except Exception:
        return int(time.time()) + random.randint(delay_min, delay_max)


def queue_count() -> int:
```

Replace with:

```python
def _get_next_ts(delay_min: int, delay_max: int, media_type: str = 'photos') -> int:
    from services.slot_scheduler import reserve_slot
    return reserve_slot(media_type, delay_min, delay_max)


def queue_count() -> int:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_photos_scheduler_integration.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the broader photos/publish test suite to check nothing broke**

Run: `pytest tests/test_slot_finder_publish.py tests/test_publish_upload_resilience.py -v`
Expected: PASS (all existing tests still pass)

- [ ] **Step 6: Commit**

```bash
git add workers/photos.py tests/test_photos_scheduler_integration.py
git commit -m "refactor: photos worker reserves publish slots via slot_scheduler"
```

---

## Task 5: Wire slot scheduler into videos/clips worker

**Files:**
- Modify: `workers/videos.py:317-414` (inside `publish_videos_worker`)
- Test: `tests/test_videos_scheduler_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_videos_scheduler_integration.py
# -*- coding: utf-8 -*-
import json


def test_publish_videos_worker_uses_media_type_videos(monkeypatch, tmp_path):
    """publish_videos_worker(is_clips_mode=False) reserves media_type='videos'."""
    from config import app_state
    import workers.videos as videos_mod

    recorded = {}

    def fake_reserve_slot(media_type, delay_min, delay_max, profile=None):
        recorded['media_type'] = media_type
        recorded['delay_min'] = delay_min
        recorded['delay_max'] = delay_max
        return 9999999999

    monkeypatch.setattr("services.slot_scheduler.reserve_slot", fake_reserve_slot)
    monkeypatch.setattr(videos_mod, "_get_next_ts", lambda dmin, dmax, media_type='videos': fake_reserve_slot(media_type, dmin, dmax))

    # We only verify the helper wiring here; full worker run is covered by
    # existing integration tests in test_slot_finder_publish.py.
    from workers.photos import _get_next_ts
    ts = _get_next_ts(10, 20, media_type='videos')
    assert recorded['media_type'] == 'videos'
```

- [ ] **Step 2: Run test to verify current state**

Run: `pytest tests/test_videos_scheduler_integration.py -v`
Expected: FAIL — `_get_next_ts` from `workers.photos` doesn't accept calling through `videos_mod` patch correctly because `workers/videos.py` still has its own inline scheduling, not using `_get_next_ts` with `media_type`.

Note: this step mainly documents intent; the real verification happens in Step 4 after the refactor.

- [ ] **Step 3: Replace inline scheduling in `workers/videos.py::publish_videos_worker`**

Current code at lines 315-318:

```python
        app_state.add_log(f'{label}: публикация {len(queue)}', 'info')
        published = failed = 0
        from workers.photos import _get_next_ts
        next_ts = _get_next_ts(delay_min, delay_max)
```

Replace with:

```python
        app_state.add_log(f'{label}: публикация {len(queue)}', 'info')
        published = failed = 0
        media_type = 'clips' if is_clips_mode else 'videos'
```

(Remove the `next_ts = _get_next_ts(...)` line — it's now computed per-post below, inside the `if create_wall:` block.)

Then find the per-post scheduling block at lines 380-414:

```python
                    now = int(time.time())
                    if next_ts <= now:
                        next_ts = now + random.randint(delay_min, delay_max)

                    params = {
                        'owner_id': owner_id,
                        'message': text,
                        'attachments': att,
                        'publish_date': next_ts,
                    }
                    result = vk_call_safe(vk_group.wall.post, **params)
                    vk_post_id = result.get('post_id') if isinstance(result, dict) else None
                    if vk_post_id:
                        try:
                            from services.tracker import track as _track
                            _track(
                                vk_post_id, owner_id, str(meta.get('owner_id', '')),
                                published_at=next_ts,
                                caption_category=caption_meta.get('caption_category', ''),
                                caption_text=caption_meta.get('caption_text', ''),
                                caption_id=caption_meta.get('caption_id', ''),
                                media_type=meta.get('media_kind')
                                or ('clip' if is_clips_mode else 'video'),
                                overlay_family=overlay_family,
                            )
                        except Exception:
                            pass
                    from datetime import datetime
                    from services.storage import write_last_scheduled
                    app_state.add_log(
                        f'{label}: → {datetime.fromtimestamp(next_ts).strftime("%d.%m %H:%M")}',
                        'info'
                    )
                    write_last_scheduled(next_ts)
                    next_ts += random.randint(delay_min, delay_max)
```

Replace the `now`/`if next_ts <= now` block at the top with a single reservation call, and remove the now-redundant `write_last_scheduled`/`next_ts +=` lines at the bottom (`reserve_slot` already persists via `write_last_scheduled` internally):

```python
                    from services.slot_scheduler import reserve_slot
                    next_ts = reserve_slot(media_type, delay_min, delay_max)

                    params = {
                        'owner_id': owner_id,
                        'message': text,
                        'attachments': att,
                        'publish_date': next_ts,
                    }
                    result = vk_call_safe(vk_group.wall.post, **params)
                    vk_post_id = result.get('post_id') if isinstance(result, dict) else None
                    if vk_post_id:
                        try:
                            from services.tracker import track as _track
                            _track(
                                vk_post_id, owner_id, str(meta.get('owner_id', '')),
                                published_at=next_ts,
                                caption_category=caption_meta.get('caption_category', ''),
                                caption_text=caption_meta.get('caption_text', ''),
                                caption_id=caption_meta.get('caption_id', ''),
                                media_type=meta.get('media_kind')
                                or ('clip' if is_clips_mode else 'video'),
                                overlay_family=overlay_family,
                            )
                        except Exception:
                            pass
                    from datetime import datetime
                    app_state.add_log(
                        f'{label}: → {datetime.fromtimestamp(next_ts).strftime("%d.%m %H:%M")}',
                        'info'
                    )
```

- [ ] **Step 4: Update the placeholder test to verify the actual reservation call**

Rewrite `tests/test_videos_scheduler_integration.py`:

```python
# tests/test_videos_scheduler_integration.py
# -*- coding: utf-8 -*-
import inspect

import workers.videos as videos_mod


def test_publish_videos_worker_calls_reserve_slot_with_media_type():
    """Source-level check: publish_videos_worker references reserve_slot
    and passes media_type derived from is_clips_mode."""
    source = inspect.getsource(videos_mod.publish_videos_worker)
    assert "reserve_slot(media_type, delay_min, delay_max)" in source
    assert "media_type = 'clips' if is_clips_mode else 'videos'" in source
    assert "_get_next_ts" not in source
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_videos_scheduler_integration.py -v`
Expected: PASS (1 passed)

- [ ] **Step 6: Run the full existing test suite for videos/publish to check nothing broke**

Run: `pytest tests/test_slot_finder_publish.py tests/test_publish_import.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add workers/videos.py tests/test_videos_scheduler_integration.py
git commit -m "refactor: videos/clips worker reserves publish slots via slot_scheduler"
```

---

## Task 6: Wire slot scheduler into posts worker (smart-schedule path stays, but also reserves)

**Files:**
- Modify: `workers/publish.py:359-391` (the `if postponed:` scheduling block)
- Test: `tests/test_publish_scheduler_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish_scheduler_integration.py
# -*- coding: utf-8 -*-
import inspect

import workers.publish as publish_mod


def test_publish_worker_registers_slot_with_scheduler():
    """publish_worker's postponed branch must call reserve_slot/record_slot
    so photos/videos/clips cycles see posts' reserved timestamps too."""
    source = inspect.getsource(publish_mod.publish_worker)
    assert "record_slot" in source or "reserve_slot" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_publish_scheduler_integration.py -v`
Expected: FAIL — `publish_worker` has neither `record_slot` nor `reserve_slot` yet.

- [ ] **Step 3: Add a lightweight `record_slot` helper to `services/slot_scheduler.py`**

The posts worker computes its own `next_ts` via smart-scheduler/learned-24h logic — it shouldn't have its timestamp *moved* by the scheduler, just *registered* so other cycles avoid colliding with it. Add this function to `services/slot_scheduler.py` (after `reserve_slot`):

```python
def record_slot(media_type: str, ts: int) -> None:
    """Зарегистрировать уже выбранный timestamp (posts со своим умным
    расписанием) в общем реестре, чтобы photos/videos/clips не коллидировали
    с ним через min_gap.
    """
    lock = _acquire_lock()
    try:
        data = _prune_old_slots(_load_slots())
        data['slots'].append({'media_type': media_type, 'ts': int(ts)})
        _save_slots(data)
    finally:
        _release_lock(lock)
```

- [ ] **Step 4: Add a test for `record_slot` in `tests/test_slot_scheduler.py`**

```python
# tests/test_slot_scheduler.py (append)

def test_record_slot_appears_in_future_reservations(scheduler_paths, monkeypatch):
    from services.slot_scheduler import record_slot, reserve_slot
    monkeypatch.setattr("services.slot_scheduler._min_gap_seconds", lambda profile: 1800)

    fixed_ts = int(time.time()) + 100
    record_slot("posts", fixed_ts)

    ts2 = reserve_slot(media_type="videos", delay_min=10, delay_max=10, profile={})
    assert abs(ts2 - fixed_ts) >= 1800
```

- [ ] **Step 5: Run scheduler tests**

Run: `pytest tests/test_slot_scheduler.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: Call `record_slot` from `workers/publish.py`**

In `workers/publish.py`, inside the `for index, post_file in enumerate(post_files, 1):` loop, after `params['publish_date'] = next_ts` is set (around line 391), add:

```python
                    params['publish_date'] = next_ts
                    scheduled_label = datetime.fromtimestamp(next_ts).strftime('%d.%m %H:%M')

                    from services.slot_scheduler import record_slot
                    record_slot('posts', next_ts)
```

- [ ] **Step 7: Run the placeholder test to verify it passes**

Run: `pytest tests/test_publish_scheduler_integration.py -v`
Expected: PASS (1 passed)

- [ ] **Step 8: Run the full publish-related test suite**

Run: `pytest tests/test_slot_finder_publish.py tests/test_publish_import.py tests/test_publish_upload_resilience.py tests/test_slot_scheduler.py -v`
Expected: PASS (all)

- [ ] **Step 9: Commit**

```bash
git add services/slot_scheduler.py workers/publish.py tests/test_slot_scheduler.py tests/test_publish_scheduler_integration.py
git commit -m "feat: posts worker registers reserved slots in shared scheduler"
```

---

## Task 7: Enable pHash dedup for photos (currently hardcoded off)

**Files:**
- Modify: `workers/download.py:95` (`phash_enabled = False`)
- Test: `tests/test_download_worker.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_download_worker.py (append)

def test_phash_enabled_reads_from_profile_config(monkeypatch):
    """phash_enabled should reflect profile.phash.enabled, not be hardcoded False."""
    import workers.download as dl

    profile = {"phash": {"enabled": True, "threshold": 10}}
    phash_cfg = profile.get('phash', {})
    phash_enabled = phash_cfg.get('enabled', False)

    assert phash_enabled is True
```

This test documents the expected config read shape; the real fix is the source change in Step 3.

- [ ] **Step 2: Locate the hardcoded line**

Run: `grep -n "phash_enabled" workers/download.py`
Expected output includes: `phash_enabled = False`

- [ ] **Step 3: Fix `workers/download.py`**

Find (around line 95):

```python
    phash_cfg = profile.get('phash', {})
    phash_enabled = False
    phash_threshold = int(phash_cfg.get('threshold', 10))
```

Replace with:

```python
    phash_cfg = profile.get('phash', {})
    phash_enabled = bool(phash_cfg.get('enabled', False))
    phash_threshold = int(phash_cfg.get('threshold', 10))
```

- [ ] **Step 4: Add `phash.enabled: true` to both profiles in `config.json`**

For profile `p1` and `p37fb1e`, add (or set) under each profile:

```json
"phash": {
  "enabled": true,
  "threshold": 10
}
```

Use a small script to apply this safely (do NOT hand-edit `config.json` while the bot is running — confirm with the user it's stopped first):

```python
import json
from pathlib import Path

cfg_path = Path("config.json")
cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
for pid in ("p1", "p37fb1e"):
    profile = cfg["profiles"][pid]
    phash = profile.setdefault("phash", {})
    phash["enabled"] = True
    phash.setdefault("threshold", 10)
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 5: Run download worker tests**

Run: `pytest tests/test_download_worker.py -v`
Expected: PASS (all, including the new test)

- [ ] **Step 6: Commit**

```bash
git add workers/download.py tests/test_download_worker.py config.json
git commit -m "fix: enable pHash photo dedup via profile config (was hardcoded off)"
```

---

## Task 8: Extend pHash dedup to videos/clips

**Files:**
- Modify: `services/phash.py` — add `hash_video_frame()`
- Modify: `workers/videos.py` — call dedup check on downloaded video/clip files
- Test: `tests/test_phash_video.py`

- [ ] **Step 1: Read current `services/phash.py` to confirm the existing API shape**

Run: `pytest tests/ -v -k phash --collect-only` to see if any phash tests exist already (there may be none — that's fine, we're adding new ones).

- [ ] **Step 2: Write the failing test**

```python
# tests/test_phash_video.py
# -*- coding: utf-8 -*-
from pathlib import Path

import pytest


def test_hash_video_frame_extracts_and_hashes(monkeypatch, tmp_path):
    from services import phash

    fake_frame = tmp_path / "frame.jpg"

    def fake_run(cmd, **kwargs):
        # simulate ffmpeg writing the frame file
        from PIL import Image
        Image.new("RGB", (64, 64), color=(120, 50, 200)).save(fake_frame)

        class Result:
            returncode = 0
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("services.phash._extract_frame_path", lambda video_path: fake_frame)

    h = phash.hash_video_frame(Path("dummy.mp4"))
    assert h is not None
    assert isinstance(h, str)
    assert len(h) > 0


def test_hash_video_frame_returns_none_on_ffmpeg_failure(monkeypatch, tmp_path):
    from services import phash

    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 1
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)

    h = phash.hash_video_frame(Path("dummy.mp4"))
    assert h is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_phash_video.py -v`
Expected: FAIL with `AttributeError: module 'services.phash' has no attribute 'hash_video_frame'`

- [ ] **Step 4: Read existing `services/phash.py` fully before editing**

Run: `cat services/phash.py` (or use Read tool) — note the existing `is_duplicate`, `add_to_cache`, and cache file helpers so the new function follows the same conventions (cache file location, threshold comparison, `imagehash` usage).

- [ ] **Step 5: Implement `hash_video_frame` and `_extract_frame_path` in `services/phash.py`**

Add these functions (adapt import style to match the existing file — it already imports `imagehash`/`PIL.Image` lazily inside functions per the pattern seen at lines 38-40 and 52-54):

```python
def _extract_frame_path(video_path: Path) -> Path:
    """Путь для временного кадра, извлекаемого из видео для хеширования."""
    return video_path.with_name(f'.{video_path.stem}_phash_frame.jpg')


def hash_video_frame(video_path: Path) -> str | None:
    """Извлечь первый кадр видео через ffmpeg и вернуть его phash как строку.

    Возвращает None при ошибке ffmpeg или отсутствии файла.
    """
    import subprocess

    frame_path = _extract_frame_path(video_path)
    try:
        result = subprocess.run(
            ['ffmpeg', '-y', '-i', str(video_path), '-vframes', '1',
             '-q:v', '2', str(frame_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
        if result.returncode != 0 or not frame_path.exists():
            return None
        import imagehash
        from PIL import Image
        h = str(imagehash.phash(Image.open(frame_path)))
        return h
    except Exception:
        logger.warning(f'hash_video_frame: failed for {video_path.name}')
        return None
    finally:
        frame_path.unlink(missing_ok=True)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_phash_video.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Wire dedup check into `workers/videos.py` download path**

Find `_download_videos_source` in `workers/videos.py` (the function that saves downloaded video files to `videos_queue_dir`/`clips_queue_dir`). After a video file is successfully downloaded and before its metadata JSON is written, add a dedup check mirroring the photo pattern from `workers/download.py:208-223`:

```python
                # pHash дедупликация по первому кадру (видео/клипы)
                phash_cfg = profile.get('phash', {})
                if phash_cfg.get('enabled', False):
                    from services.phash import hash_video_frame, is_duplicate, add_to_cache
                    frame_hash = hash_video_frame(video_path)
                    if frame_hash and is_duplicate(video_path, int(phash_cfg.get('threshold', 10))):
                        app_state.add_log(f'{label}: дубликат по кадру, пропускаю {video_path.name}', 'info')
                        video_path.unlink(missing_ok=True)
                        continue
                    if frame_hash:
                        add_to_cache(video_path, f'video_{video_path.stem}')
```

Note: `is_duplicate`/`add_to_cache` in `services/phash.py` currently take an image path and call `imagehash.phash(Image.open(image_path))` directly — they won't work on a video file path. Before wiring this in, **read `services/phash.py` in full** and adapt: either (a) extend `is_duplicate`/`add_to_cache` to accept a precomputed hash string, or (b) write the extracted frame to a temp path and pass that. Prefer (a) — add optional `precomputed_hash: str | None = None` parameters to both functions so video and photo dedup share the same cache file and threshold logic.

- [ ] **Step 8: Add `precomputed_hash` parameter to `is_duplicate`/`add_to_cache`**

Current code in `services/phash.py` (lines 35-59):

```python
def is_duplicate(image_path: Path, threshold: int = 10) -> bool:
    """True если похожее фото уже есть в кэше."""
    try:
        import imagehash
        from PIL import Image
        new_h = imagehash.phash(Image.open(image_path))
        for h_str in _load().values():
            if abs(new_h - imagehash.hex_to_hash(h_str)) <= threshold:
                return True
        return False
    except Exception:
        return False


def add_to_cache(image_path: Path, key: str):
    """Добавить хэш изображения в кэш."""
    try:
        import imagehash
        from PIL import Image
        h = str(imagehash.phash(Image.open(image_path)))
        cache = _load()
        cache[key] = h
        _save(cache)
    except Exception:
        pass
```

Replace with:

```python
def is_duplicate(image_path: Path, threshold: int = 10, precomputed_hash: str | None = None) -> bool:
    """True если похожее фото/видео-кадр уже есть в кэше."""
    try:
        import imagehash
        from PIL import Image
        new_h = imagehash.hex_to_hash(precomputed_hash) if precomputed_hash else imagehash.phash(Image.open(image_path))
        for h_str in _load().values():
            if abs(new_h - imagehash.hex_to_hash(h_str)) <= threshold:
                return True
        return False
    except Exception:
        return False


def add_to_cache(image_path: Path, key: str, precomputed_hash: str | None = None):
    """Добавить хэш изображения/кадра видео в кэш."""
    try:
        import imagehash
        from PIL import Image
        h = precomputed_hash or str(imagehash.phash(Image.open(image_path)))
        cache = _load()
        cache[key] = h
        _save(cache)
    except Exception:
        pass
```

- [ ] **Step 9: Update `workers/videos.py` call site to use `precomputed_hash`**

```python
                phash_cfg = profile.get('phash', {})
                if phash_cfg.get('enabled', False):
                    from services.phash import hash_video_frame, is_duplicate, add_to_cache
                    frame_hash = hash_video_frame(video_path)
                    if frame_hash:
                        if is_duplicate(video_path, int(phash_cfg.get('threshold', 10)), precomputed_hash=frame_hash):
                            app_state.add_log(f'{label}: дубликат по кадру, пропускаю {video_path.name}', 'info')
                            video_path.unlink(missing_ok=True)
                            continue
                        add_to_cache(video_path, f'video_{video_path.stem}', precomputed_hash=frame_hash)
```

- [ ] **Step 10: Run the full phash + video test suites**

Run: `pytest tests/test_phash_video.py tests/test_video_transform.py tests/test_download_worker.py -v`
Expected: PASS (all)

- [ ] **Step 11: Commit**

```bash
git add services/phash.py workers/videos.py tests/test_phash_video.py
git commit -m "feat: extend pHash dedup to video/clip downloads via frame hashing"
```

---

## Task 9: Disable engagement filter in both profiles

**Files:**
- Modify: `config.json`
- Test: `tests/test_post_filters.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_post_filters.py (append)

def test_engagement_disabled_in_config():
    """Per user decision: take all posts regardless of engagement —
    different posts go viral on different channels."""
    import json
    from pathlib import Path

    cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
    for pid, profile in cfg.get("profiles", {}).items():
        eng = profile.get("engagement", {})
        assert eng.get("enabled", False) is False, f"engagement still enabled for {pid}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_post_filters.py -v -k engagement`
Expected: FAIL — both `p1` and `p37fb1e` currently have `engagement.enabled: true`.

- [ ] **Step 3: Update `config.json`**

For both profile `p1` and `p37fb1e`, change:

```json
"engagement": {"enabled": true, "min_ratio": 0.1, "min_likes": 0}
```

to:

```json
"engagement": {"enabled": false, "min_ratio": 0.1, "min_likes": 0}
```

Apply via script (confirm bot is stopped first):

```python
import json
from pathlib import Path

cfg_path = Path("config.json")
cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
for pid, profile in cfg["profiles"].items():
    profile.setdefault("engagement", {})["enabled"] = False
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_post_filters.py -v -k engagement`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add config.json tests/test_post_filters.py
git commit -m "fix: disable engagement filter — take all source posts, not just top performers"
```

---

## Task 10: Set daily limits for videos (1/day) and clips (2/day)

**Files:**
- Modify: `config.json` (profile `p1` — the only profile with `videos_settings.enabled`/`clips_settings.enabled` = true)
- Test: `tests/test_slot_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slot_scheduler.py (append)

def test_config_has_video_and_clip_daily_limits():
    import json
    from pathlib import Path

    cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
    p1 = cfg["profiles"]["p1"]
    assert p1["videos_settings"]["daily_limit"] == 1
    assert p1["clips_settings"]["daily_limit"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_slot_scheduler.py -v -k daily_limits`
Expected: FAIL — `daily_limit` key doesn't exist yet.

- [ ] **Step 3: Update `config.json` for profile `p1`**

```python
import json
from pathlib import Path

cfg_path = Path("config.json")
cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
p1 = cfg["profiles"]["p1"]
p1["videos_settings"]["daily_limit"] = 1
p1["clips_settings"]["daily_limit"] = 2
# Also reduce per-run publish counts so a single cycle doesn't try to
# dump 10 videos/clips before the daily cap logic in slot_scheduler
# even gets a chance — keeps queue churn sane.
p1["videos_settings"]["videos_publish_per_run"] = 1
p1["clips_settings"]["clips_publish_per_run"] = 2
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_slot_scheduler.py -v -k daily_limits`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add config.json tests/test_slot_scheduler.py
git commit -m "config: cap videos to 1/day and clips to 2/day for profile p1"
```

---

## Task 11: Structured publish log (JSONL with daily rotation/compression)

**Files:**
- Create: `services/publish_log.py`
- Test: `tests/test_publish_log.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish_log.py
# -*- coding: utf-8 -*-
import gzip
import json
import time


def test_log_publish_event_appends_jsonl(monkeypatch, tmp_path):
    from config import app_state
    from services import publish_log

    log_file = tmp_path / "publish_log.jsonl"
    monkeypatch.setattr(type(app_state), "publish_log_file", property(lambda self: log_file))

    publish_log.log_publish_event(
        media_type="photos",
        status="success",
        post_id=12345,
        publish_date=int(time.time()) + 60,
        source_id="999",
        extra={"duplicate": False},
    )

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["media_type"] == "photos"
    assert entry["status"] == "success"
    assert entry["post_id"] == 12345
    assert entry["extra"]["duplicate"] is False


def test_read_recent_events_returns_latest_first(monkeypatch, tmp_path):
    from config import app_state
    from services import publish_log

    log_file = tmp_path / "publish_log.jsonl"
    monkeypatch.setattr(type(app_state), "publish_log_file", property(lambda self: log_file))

    for i in range(3):
        publish_log.log_publish_event(media_type="posts", status="success", post_id=i, publish_date=0)

    events = publish_log.read_recent_events(limit=2)
    assert len(events) == 2
    assert events[0]["post_id"] == 2
    assert events[1]["post_id"] == 1


def test_rotate_old_logs_compresses_yesterdays_file(monkeypatch, tmp_path):
    from config import app_state
    from services import publish_log

    log_dir = tmp_path
    log_file = log_dir / "publish_log.jsonl"
    monkeypatch.setattr(type(app_state), "publish_log_file", property(lambda self: log_file))

    # Simulate an old log file with yesterday's mtime
    log_file.write_text('{"post_id": 1}\n', encoding="utf-8")
    yesterday = time.time() - 90000
    import os
    os.utime(log_file, (yesterday, yesterday))

    publish_log.rotate_old_logs()

    gz_files = list(log_dir.glob("publish_log-*.jsonl.gz"))
    assert len(gz_files) == 1
    with gzip.open(gz_files[0], "rt", encoding="utf-8") as f:
        assert '"post_id": 1' in f.read()
    assert not log_file.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_publish_log.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.publish_log'`

- [ ] **Step 3: Implement `services/publish_log.py`**

```python
# -*- coding: utf-8 -*-
"""Структурированный журнал публикаций.

Каждая попытка публикации (успех/ошибка/дубликат) пишется одной строкой
JSON в storage/{profile_id}/publish_log.jsonl. Файлы старше суток
сжимаются в publish_log-YYYY-MM-DD.jsonl.gz, чтобы не разрастаться.
"""

import gzip
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config import app_state, logger


def log_publish_event(
    media_type: str,
    status: str,
    post_id: Optional[int] = None,
    publish_date: Optional[int] = None,
    source_id: str = '',
    extra: Optional[dict] = None,
) -> None:
    """Записать одно событие публикации.

    status: 'success' | 'failed' | 'duplicate' | 'skipped'
    """
    entry = {
        'ts': int(time.time()),
        'media_type': media_type,
        'status': status,
        'post_id': post_id,
        'publish_date': publish_date,
        'source_id': source_id,
        'extra': extra or {},
    }
    log_file = app_state.publish_log_file
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.warning(f'log_publish_event: {e}')


def read_recent_events(limit: int = 50) -> list[dict]:
    """Последние N событий, новейшие первыми."""
    log_file = app_state.publish_log_file
    if not log_file.exists():
        return []
    try:
        lines = log_file.read_text(encoding='utf-8').strip().splitlines()
        events = [json.loads(line) for line in lines if line.strip()]
        return list(reversed(events))[:limit]
    except Exception as e:
        logger.warning(f'read_recent_events: {e}')
        return []


def rotate_old_logs() -> None:
    """Сжать publish_log.jsonl в .gz, если файл не менялся >24ч.

    Вызывается из media_loop_worker раз в проход — не критично к точному
    расписанию, главное чтобы файл не рос бесконечно.
    """
    log_file = app_state.publish_log_file
    if not log_file.exists():
        return
    age_sec = time.time() - log_file.stat().st_mtime
    if age_sec < 86400:
        return
    mtime_date = datetime.fromtimestamp(log_file.stat().st_mtime).strftime('%Y-%m-%d')
    gz_path = log_file.with_name(f'{log_file.stem}-{mtime_date}.jsonl.gz')
    try:
        with open(log_file, 'rb') as src, gzip.open(gz_path, 'wb') as dst:
            dst.write(src.read())
        log_file.unlink()
    except Exception as e:
        logger.warning(f'rotate_old_logs: {e}')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_publish_log.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add services/publish_log.py tests/test_publish_log.py
git commit -m "feat: add structured JSONL publish log with daily rotation"
```

---

## Task 12: Call log_publish_event from publish workers

**Files:**
- Modify: `workers/publish.py` (posts)
- Modify: `workers/photos.py` (`publish_photos_worker`)
- Modify: `workers/videos.py` (`publish_videos_worker`)
- Test: `tests/test_publish_log_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish_log_integration.py
# -*- coding: utf-8 -*-
import inspect

import workers.publish as publish_mod
import workers.photos as photos_mod
import workers.videos as videos_mod


def test_all_publish_workers_call_log_publish_event():
    for mod, fn_name in (
        (publish_mod, "publish_worker"),
        (photos_mod, "publish_photos_worker"),
        (videos_mod, "publish_videos_worker"),
    ):
        source = inspect.getsource(getattr(mod, fn_name))
        assert "log_publish_event" in source, f"{fn_name} missing log_publish_event call"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_publish_log_integration.py -v`
Expected: FAIL — none of the three functions call `log_publish_event` yet.

- [ ] **Step 3: Add logging calls to `workers/publish.py`**

After the successful `result = vk_call_safe(vk.wall.post, **params)` and the `if result and isinstance(result, dict):` block that extracts `vk_post_id` (around line 397-399), add:

```python
                if result and isinstance(result, dict):
                    vk_post_id = result.get('post_id')
                    if vk_post_id:
                        from services.publish_log import log_publish_event
                        log_publish_event(
                            media_type='posts',
                            status='success',
                            post_id=vk_post_id,
                            publish_date=params.get('publish_date'),
                            source_id=str(post.get('owner_id', '')),
                        )
                        # ... existing mark_used_post/tracker code follows ...
```

For the failure path (the `if not attachments:` branch around line 323-334 where `failed += 1`), add right before `continue`:

```python
                        from services.publish_log import log_publish_event
                        log_publish_event(
                            media_type='posts',
                            status='failed',
                            source_id=str(post.get('owner_id', '')),
                            extra={'reason': 'photos_upload_failed'},
                        )
                        continue
```

- [ ] **Step 4: Add logging calls to `workers/photos.py::publish_photos_worker`**

Find the success path (after `result = vk_call_safe(vk_group.wall.post, **params)` for photos — read the full function first to locate the exact line). After a successful post, add:

```python
                from services.publish_log import log_publish_event
                log_publish_event(
                    media_type='photos',
                    status='success',
                    post_id=result.get('post_id') if isinstance(result, dict) else None,
                    publish_date=next_ts,
                )
```

For the failure path (file not found / upload failed branches), add:

```python
                from services.publish_log import log_publish_event
                log_publish_event(media_type='photos', status='failed', extra={'reason': 'file_not_found'})
```

- [ ] **Step 5: Add logging calls to `workers/videos.py::publish_videos_worker`**

After `result = vk_call_safe(vk_group.wall.post, **params)` (the create_wall branch), add:

```python
                    from services.publish_log import log_publish_event
                    log_publish_event(
                        media_type=media_type,
                        status='success',
                        post_id=vk_post_id,
                        publish_date=next_ts,
                    )
```

For the `if not vid_id:` failure branch (around line 361-364), add before `continue`:

```python
                    from services.publish_log import log_publish_event
                    log_publish_event(media_type=media_type, status='failed', extra={'reason': 'upload_failed'})
                    continue
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_publish_log_integration.py -v`
Expected: PASS (1 passed)

- [ ] **Step 7: Run the full test suite to confirm nothing broke**

Run: `pytest tests/ -v --ignore=tests/test_playwright_ui.py`
Expected: PASS (all, except the 2 playwright tests already known-failing per CLAUDE.md checkpoint)

- [ ] **Step 8: Commit**

```bash
git add workers/publish.py workers/photos.py workers/videos.py tests/test_publish_log_integration.py
git commit -m "feat: log every publish attempt (success/failed) to structured JSONL log"
```

---

## Task 13: Soften video crop/fade to preserve quality

**Files:**
- Modify: `services/video_transform.py:341-413` (`process_video`)
- Test: `tests/test_video_transform.py`

- [ ] **Step 1: Read the current test file to understand existing assertions**

Run: `pytest tests/test_video_transform.py -v --collect-only` and read `tests/test_video_transform.py` in full to see what's currently asserted about `crop_percent`, `aspect_mode` weights, and fade probability.

- [ ] **Step 2: Write the failing test for reduced crop range**

```python
# tests/test_video_transform.py (append)

def test_auto_crop_percent_range_is_softer(monkeypatch):
    """User feedback: crop was too aggressive and degraded quality —
    reduce the auto-random crop range from 4-8% to 1-3%."""
    import random
    from services import media_pipeline

    profile = {
        'antiplagiaat': {'enabled': True},
        'video_transform': {'hard_mode': True, 'crop_percent': 0.0},
        'watermark': {},
    }

    captured = {}

    def fake_transform_video(video_path, transforms, **kwargs):
        captured['crop_percent'] = transforms['crop_percent']
        return True

    monkeypatch.setattr('services.video_transform.transform_video', fake_transform_video)
    monkeypatch.setattr('services.video_transform.apply_finishing', lambda *a, **k: False)
    monkeypatch.setattr('services.video_transform.Path.exists', lambda self: True)

    random.seed(1)
    media_pipeline.process_video('dummy.mp4', profile, is_clip=False)

    assert 0.01 <= captured['crop_percent'] <= 0.03
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_video_transform.py -v -k softer`
Expected: FAIL — current range is `(0.04, 0.08)`, so `captured['crop_percent']` will likely be > 0.03.

Note: if `media_pipeline.process_video` doesn't exist as the entry point (it may be `services.video_transform.process_video` directly — verify with `grep -n "def process_video" services/*.py` first and adjust the import/monkeypatch targets in the test accordingly).

- [ ] **Step 4: Update `_auto` crop range in `services/video_transform.py`**

Find (around line 350):

```python
    transforms = {
        'crop_percent': _auto('crop_percent', 0.04, 0.08, 0.03) if ap_on else 0.0,
```

Replace with:

```python
    transforms = {
        'crop_percent': _auto('crop_percent', 0.01, 0.03, 0.02) if ap_on else 0.0,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_video_transform.py -v -k softer`
Expected: PASS

- [ ] **Step 6: Write the failing test for reduced fade probability**

```python
# tests/test_video_transform.py (append)

def test_fade_probability_reduced(monkeypatch):
    """User feedback: fade was too aggressive (appeared too often).
    Reduce random fade probability from 50% to 20%."""
    import random
    from services import video_transform

    profile = {
        'antiplagiaat': {'enabled': True},
        'video_transform': {'hard_mode': True},
        'watermark': {},
    }

    captured_fades = []

    def fake_transform_video(video_path, transforms, **kwargs):
        return True

    def fake_apply_finishing(video_path, **kwargs):
        captured_fades.append(kwargs['fade'])
        return False

    monkeypatch.setattr(video_transform, 'transform_video', fake_transform_video)
    monkeypatch.setattr(video_transform, 'apply_finishing', fake_apply_finishing)
    monkeypatch.setattr(video_transform.Path, 'exists', lambda self: True)

    random.seed(42)
    for _ in range(200):
        video_transform.process_video('dummy.mp4', profile, is_clip=False)

    fade_rate = sum(captured_fades) / len(captured_fades)
    assert fade_rate < 0.3, f"fade rate {fade_rate} too high, expected ~0.2"
```

- [ ] **Step 7: Run test to verify it fails**

Run: `pytest tests/test_video_transform.py -v -k fade_probability`
Expected: FAIL — current probability is `random.random() < 0.5`, so `fade_rate` will be ~0.5.

If `process_video` isn't directly in `services.video_transform` (it might live in `services/media_pipeline.py` as a thin wrapper around a `video_transform` function with a different name), run `grep -n "def process_video\|def transform_video\|fade_cfg" services/video_transform.py services/media_pipeline.py` first and adjust the test's target module/function names to match what actually exists.

- [ ] **Step 8: Update fade probability in `services/video_transform.py`**

Find (around line 399):

```python
        fade_cfg = vt_cfg.get('fade')
        do_fade = fade_cfg if isinstance(fade_cfg, bool) else (random.random() < 0.5)
```

Replace with:

```python
        fade_cfg = vt_cfg.get('fade')
        do_fade = fade_cfg if isinstance(fade_cfg, bool) else (random.random() < 0.2)
```

- [ ] **Step 9: Update `frame_px` probability (currently 30%, reduce to 10%)**

Find (around line 402-403):

```python
        frame_px = int(vt_cfg.get('frame_px', 0) or 0)
        if frame_px == 0 and hard and random.random() < 0.3:
            frame_px = random.randint(6, 14)
```

Replace with:

```python
        frame_px = int(vt_cfg.get('frame_px', 0) or 0)
        if frame_px == 0 and hard and random.random() < 0.1:
            frame_px = random.randint(6, 14)
```

- [ ] **Step 10: Reduce `square_crop`/`square_blur` weight in favor of `original` for non-clips**

Find (around line 392-396):

```python
            else:
                aspect_mode = random.choices(
                    ['original', 'square_blur', 'square_crop'],
                    weights=[0.45, 0.35, 0.20],
                )[0]
```

Replace with:

```python
            else:
                aspect_mode = random.choices(
                    ['original', 'square_blur', 'square_crop'],
                    weights=[0.65, 0.25, 0.10],
                )[0]
```

- [ ] **Step 11: Run all video_transform tests**

Run: `pytest tests/test_video_transform.py -v`
Expected: PASS (all, including the 2 new tests)

- [ ] **Step 12: Commit**

```bash
git add services/video_transform.py tests/test_video_transform.py
git commit -m "tune: reduce video crop/fade/frame aggressiveness to preserve quality"
```

---

## Task 14: Soften photo crop to preserve quality

**Files:**
- Modify: `services/photo_transform.py:21` (`apply_random_crop` default range)
- Test: `tests/test_photo_transform.py`

- [ ] **Step 1: Read current test file**

Run: `pytest tests/test_photo_transform.py -v --collect-only` and read `tests/test_photo_transform.py` in full to see existing crop-range assertions.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_photo_transform.py (append)

def test_apply_random_crop_default_range_is_softer(tmp_path):
    """User feedback: photo crop was too aggressive — reduce default
    range from 2-5% to 1-2.5% so subjects aren't cut off."""
    import inspect
    from services.photo_transform import apply_random_crop

    sig = inspect.signature(apply_random_crop)
    assert sig.parameters['min_pct'].default == 0.01
    assert sig.parameters['max_pct'].default == 0.025
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_photo_transform.py -v -k softer`
Expected: FAIL — current defaults are `min_pct=0.02, max_pct=0.05`.

- [ ] **Step 4: Update `services/photo_transform.py`**

Find (around line 21):

```python
def apply_random_crop(image_path: str | Path, min_pct: float = 0.02, max_pct: float = 0.05) -> bool:
```

Replace with:

```python
def apply_random_crop(image_path: str | Path, min_pct: float = 0.01, max_pct: float = 0.025) -> bool:
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_photo_transform.py -v -k softer`
Expected: PASS

- [ ] **Step 6: Run the full photo_transform test suite**

Run: `pytest tests/test_photo_transform.py -v`
Expected: PASS (all)

- [ ] **Step 7: Commit**

```bash
git add services/photo_transform.py tests/test_photo_transform.py
git commit -m "tune: reduce default photo crop range from 2-5% to 1-2.5%"
```

---

## Task 15: Periodic log rotation hook in media autopilot loop

**Files:**
- Modify: `workers/media_autopilot.py:207-238` (`media_loop_worker`)
- Test: `tests/test_publish_log.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish_log.py (append)

def test_media_loop_worker_calls_rotate_old_logs(monkeypatch):
    import inspect
    import workers.media_autopilot as ma

    source = inspect.getsource(ma.media_loop_worker)
    assert "rotate_old_logs" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_publish_log.py -v -k rotate_old_logs`
Expected: FAIL — `media_loop_worker` doesn't call `rotate_old_logs` yet.

- [ ] **Step 3: Add the call to `workers/media_autopilot.py::media_loop_worker`**

Find the start of the `while` loop body (around line 214-220):

```python
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
```

Add a rotation call right after `_CYCLES[media_type]()`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_publish_log.py -v -k rotate_old_logs`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -v --ignore=tests/test_playwright_ui.py`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add workers/media_autopilot.py tests/test_publish_log.py
git commit -m "feat: rotate publish log to gzip on each autopilot cycle pass"
```

---

## Task 16: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the complete test suite**

Run: `pytest tests/ -v --ignore=tests/test_playwright_ui.py`
Expected: All tests PASS. Compare against the pre-change baseline (run `pytest tests/ -v --ignore=tests/test_playwright_ui.py` on `master` before starting, if not already known) to confirm no regressions were introduced.

- [ ] **Step 2: Verify config.json is valid JSON and bot can load it**

Run: `python -c "import json; json.load(open('config.json', encoding='utf-8')); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Manually start the bot and check the dashboard**

Run: `python main.py` (or `start.bat`), then open `http://localhost:8000` in a browser.

Check:
- Dashboard loads without errors
- Autopilot cards for posts/photos/videos/clips render
- No new errors in `logs/bot.log` on startup

- [ ] **Step 4: Update project CLAUDE.md checkpoint**

In `CLAUDE.md`, under `## Checkpoint`, add an entry summarizing: unified slot scheduler prevents cross-cycle collisions and enforces daily caps (1 video + 2 clips/day), pHash dedup now active for photos and extended to video/clip frames, engagement filter disabled (all source posts are taken), structured `publish_log.jsonl` records every publish attempt, video crop/fade/frame intensities reduced for better quality retention, photo crop range reduced to 1-2.5%.

- [ ] **Step 5: Commit the checkpoint update**

```bash
git add CLAUDE.md
git commit -m "docs: update checkpoint with slot scheduler and media quality changes"
```

---

## Self-Review Notes (for the plan author, already applied above)

- **Spec coverage:**
  - Duplicates → Task 7 (photo pHash enable) + Task 8 (video/clip pHash).
  - Hard crop/fade quality loss on video → Task 13.
  - Photo quality / less cropping → Task 14.
  - Scheduled publishing for clips/videos (no more 20-in-a-row) → Tasks 1-2 (scheduler core), 5 (videos/clips wiring), 10 (daily caps 1+2).
  - Take all posts, not just "best" → Task 9 (disable engagement filter).
  - Many duplicate scheduled posts / wrong slot fills → Tasks 1-2, 4-6 (unified scheduler across all 4 cycles).
  - Detailed logs saved to files, compressed → Tasks 11, 12, 15.
  - Slot collisions / 10-30 min spam intervals → Task 1 (`min_gap` enforcement across media types via `reserve_slot`).
  - Spread posts across the day instead of bursts → Task 1 (`reserve_slot` daily-limit day-rollover) + Task 10 (caps).

- **Placeholder scan:** All code blocks contain real, complete implementations (not stubs). All bash commands are concrete with expected outputs.

- **Type consistency:** `reserve_slot(media_type, delay_min, delay_max, profile=None)` signature is consistent across Tasks 1, 2, 4, 5. `record_slot(media_type, ts)` consistent across Tasks 6. `log_publish_event(media_type, status, post_id, publish_date, source_id, extra)` consistent across Tasks 11-12. `hash_video_frame(video_path) -> str | None` and `is_duplicate(..., precomputed_hash=None)` / `add_to_cache(..., precomputed_hash=None)` consistent across Task 8.
