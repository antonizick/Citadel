# AGENTS.md — Nx-Citadel

> Self-hosted intelligence platform. FastAPI + APScheduler + markdown storage.
> See `CLAUDE.md` for full architecture, models, API endpoints, and pipeline details.

## Commands

| Action | Command |
|---|---|
| Dev start | `python run.py` (port 8000, no reload) |
| Dev start (background) | `bash StartCitadel.sh` |
| Stop | `bash StopCitadel.sh` |
| Systemd service | `sudo systemctl start|stop|restart citadel` |
| Install deps | `.venv/bin/pip install -r requirements.txt` |
| Create venv | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |

There is **no test suite, no linter, no type checker, no formatter**. Verification is manual — start the server and exercise the UI or API.

## Critical conventions

- **Markdown storage only** — all data is `.md` files with YAML frontmatter in `data/`. Never introduce a database.
- **Generic store**: `app/storage/markdown_store.py` handles all CRUD. Use it; don't write new file I/O patterns.
- **Report frontmatter**: `interest_id` (or `report_id`/`resource_id`), `name`, `generated_at`. API endpoints strip frontmatter from content but return `generated_at` separately.

## Dev mode — prevent unwanted LLM calls

Set `system_state: dev` in `data/config/settings.yaml` or via `POST /api/admin/system-state` to suppress **all scheduled runs** for interests, resources, and summary reports. Manual runs (UI "Run" button) still fire. Check current state with `GET /api/admin/system-state`.

## Auth

- Session cookies, 12 hr TTL. Bypass paths: `/login`, `/health`, `/static/*`, `/api/auth/*`.
- Roles: user, manager, admin. Manager/admin enforce MFA on first login.
- Default credentials: `admin / admin` (seeded in `main.py:_seed_admin`).
- Auth middleware lives in `main.py`.

## Output config quirk

- Interests & summary reports: `OutputConfig.types` defaults to `["report"]` (always saved).
- Resources: `ResourceOutputConfig.types` defaults to `[]` (no delivery, but reports always saved regardless).
- Don't confuse the two models.

## Scheduling

All jobs registered at startup via `reload_all_schedules()`. Intervals are anchored to `last_run`. Schedule types: `interval`, `weekly`, `cron`, `manual`. See `CLAUDE.md` for exact YAML shape.

## UI

Single-page app: `templates/index.html` + `static/js/app.js`. All UI is JS-driven; the server returns the shell HTML. CSS vars in `static/css/main.css`. Dark default, light toggle via `html.light-theme`, persisted to `localStorage('citadel-theme')`.

## Packaging / deploy

- Build: `POST /api/admin/build-package` → `deploy/nxcitadel-<ts>.tar.gz` (+ `nxcitadel-latest.tar.gz` symlink). Excludes `data/`, `.venv/`, `__pycache__`, old deploys.
- Self-update: `GET /api/admin/self-update/stream?url=...` (SSE). Uses rsync to preserve `data/`, `logs/`, `.venv/`.
- Factory reset wipes all `data/` subdirs except `data/logs/`, re-seeds admin/admin, preserves `logs/` root.

## Known gaps

- `data/resource_reports/` not covered by granular backup (full backup only).
- Resource tag filtering in `get_recent_resource_reports()` not wired to per-interest tags.
- No rate-limiting. No HTTPS termination (use reverse proxy in prod).
- ThreatFox and OTX IOC sources disabled.
