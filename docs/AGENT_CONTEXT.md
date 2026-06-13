# Agent context

Use this file as the first project memory checkpoint for Codex sessions. Do not scan the whole
repository by default. Read deeper files only when the current task needs them.

## Hard rules

- Do not add UI elements, product features, behavior changes, or "nice-to-have" improvements without explicit user permission.
- If an improvement seems useful, ask first and wait for approval.
- Keep edits scoped to the user request. Do not refactor unrelated code.
- Do not edit `config.json` by hand while the bot is running.

## Project shape

- App: VK reposting bot for downloading posts/media from source communities, processing media/text, and scheduling posts to the user's VK group.
- Stack: Python 3.10+, FastAPI backend, vanilla JS SPA frontend.
- Run: from `vk-post-reposting-bot/`, use `start.bat` or `python main.py`.
- Main app: `main.py`.
- Global state: `config.py`, singleton `app_state`.
- API layer: `api/`, thin FastAPI routers under `/api/*`.
- Business logic: `services/`.
- Background workers: `workers/`.
- Frontend: `frontend/`, vanilla JS modules in `frontend/js/`.
- Per-profile runtime state: `storage/{profile_id}/`.
- Main log: `logs/bot.log`.

## Important architecture facts

- `app_state` owns the active profile, loaded config, paths, worker flags, progress, logs, and `save_config()`.
- Profiles live under `config.json -> profiles.{profile_id}` with blocks for VK tokens, sources, download, publishing, processing, monitoring, and autopilot.
- Workers are daemon-style background loops launched by FastAPI lifespan/watchdog code.
- API routers should stay thin; business behavior belongs in `services/` or `workers/`.
- Source/media quality logic uses tracker snapshots, learning, bandits, source quality, seasonality, and content library data.
- Media processing centralizes antiplagiarism/transforms in `services/media_pipeline.py` and related photo/video/watermark modules.
- Manual media UI and `/api/media/...` routes were removed. Photo/video/clip work is controlled through `workers/media_autopilot.py` loops.

## Key workflows

- Download posts: `workers/download.py` calls VK wall APIs, filters, downloads photos, writes JSON and offsets.
- Publish posts: `workers/publish.py` reads downloaded posts, applies processing, uploads media, schedules VK posts, then updates queue state.
- Monitor sources: `workers/monitor.py` checks enabled sources periodically and publishes or queues fresh posts.
- Media autopilot: `workers/media_autopilot.py` runs independent post/photo/video/clip loops with per-loop interval/download/publish settings.
- Growth loop: tracker snapshots, caption/content library, learning, bandit selection, source quality, seasonality, and weekly reports.

## Where to look

- Full project reference: `docs/PROJECT_DOCUMENTATION.md`.
- User guide: `docs/РУКОВОДСТВО_ПОЛЬЗОВАТЕЛЯ.md`.
- Architecture invariants: `.claude/rules/bot-invariants.md`.
- Current project checkpoint and backlog: `CLAUDE.md`.
- Slash commands: `.claude/commands/`.

## Working pattern

1. Read this file first.
2. Read `CLAUDE.md` only if the task depends on current checkpoint/backlog.
3. Read specific files by path or symbol search with `rg`.
4. Avoid broad repository reads unless the user asks for an audit, review, or unknown behavior investigation.
