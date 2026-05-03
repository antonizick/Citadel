# Nx-Citadel

**Self-hosted intelligence monitoring platform.** Track topics, people, technologies, and trusted sources — powered by AI-driven search, summarization, and delivery.

Nx-Citadel runs web searches on a schedule, feeds results to an LLM (Anthropic Claude), generates executive summaries, and delivers them via email, Slack, SMS, or Discord. It also maintains a database of Indicators of Compromise (IOCs) pulled from public threat-intel feeds.

> **Database-free.** All data stored as markdown files with YAML frontmatter. No SQL, no migrations, no external services required beyond the LLM API.

---

## Features

- **Interest monitoring** — Define topics (people, companies, tech, events, custom terms). Each runs on its own schedule, searches the web, and produces an AI summary report.
- **Trusted resource monitors** — Point at any URL (website, RSS feed, X/Twitter profile). The AI extracts and structures stories from the past 48 hours using a configurable prompt.
- **Executive summary reports** — Synthesize across multiple interest reports into cross-topic briefs, on their own schedule.
- **IOC tracking** — Automated daily ingestion from Feodo Tracker, URLhaus, MalwareBazaar, and OpenPhish. Bulk CSV upload with strict validation.
- **Multi-channel delivery** — Email (SMTP/Gmail), Slack webhook, SMS (Twilio), Discord webhook. Per-interest configuration.
- **Role-based access** — user / manager / admin roles with session auth and TOTP MFA (enforced for manager/admin on first login).
- **Full backup & restore** — ZIP-based full and granular backups through the UI.
- **Self-updating** — One-click update via SSE stream, preserving all user data.
- **Dark/light theme** — Dark default, toggle persisted to localStorage.

---

## Quick Start

### Prerequisites

- **Python 3.10+** on Linux
- **Anthropic API key** (for Claude LLM)
- Optional: SMTP details, Twilio account, Slack/Discord webhooks, Brave Search or SerpAPI keys

### Run locally

```bash
# 1. Clone and create virtual environment
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Start the server (port 8000)
python run.py

# 3. Open http://localhost:8000
#    Default login: admin / admin
```

### Run as a background service

```bash
# Development (with PID tracking)
bash StartCitadel.sh

# Stop
bash StopCitadel.sh

# Production (systemd)
sudo cp citadel.service /etc/systemd/system/
sudo systemctl enable --now citadel
```

### Install on a server

```bash
curl -fsSL https://www.antonizick.com/nxcitadel/get.sh | sudo bash
```

Options: `--port 9000`, `--dir /opt/nxcitadel`, `--user nxcitadel`

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Nx-Citadel                           │
│                                                         │
│  ┌───────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ FastAPI    │  │ APScheduler  │  │  LLM (Claude)    │  │
│  │ + Auth     │  │ (cron /      │  │  Anthropic API   │  │
│  │ + UI shell │  │  interval)   │  │                  │  │
│  └─────┬─────┘  └──────┬───────┘  └────────┬─────────┘  │
│        │               │                    │            │
│        ▼               ▼                    ▼            │
│  ┌──────────────────────────────────────────────────┐   │
│  │              Services Layer                       │   │
│  │  search_service.py  → DuckDuckGo / Brave / SerpAPI│   │
│  │  ai_service.py      → LLM summarization           │   │
│  │  output_service.py  → email / slack / sms / discord│  │
│  │  ioc_collector.py   → threat feed ingestion        │   │
│  │  scheduler_service.py → job orchestration          │   │
│  └──────────────────────────┬───────────────────────┘   │
│                             │                           │
│                             ▼                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Markdown Store (data/*.md + YAML frontmatter)   │   │
│  │  interests/  resources/  reports/  iocs/  etc.   │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Directory structure

```
nxcitadel/
├── app/                        # Application code
│   ├── main.py                 # FastAPI entry point, auth middleware
│   ├── auth.py                 # Sessions, bcrypt, TOTP
│   ├── models.py               # Pydantic models
│   ├── config.py               # settings.yaml loader
│   ├── routers/                # API endpoints (CRUD, run, reports)
│   ├── services/               # Business logic (AI, search, scheduler, IOC)
│   └── storage/                # Markdown CRUD layer
├── data/                       # All user data (markdown + YAML)
│   ├── interests/              # Watch topic definitions
│   ├── resources/              # Trusted resource monitor definitions
│   ├── reports/                # Generated interest reports
│   ├── resource_reports/       # Generated resource monitor reports
│   ├── summary_reports/        # Summary report definitions + generated reports
│   ├── iocs/                   # IOC data (ips, domains, urls, hashes)
│   ├── users/                  # User accounts
│   └── config/                 # settings.yaml, ioc_sources.yaml
├── templates/index.html        # SPA shell (Jinja2)
├── static/                     # CSS + JS + assets
├── deploy/                     # Install script, build scripts, packages
├── logs/                       # Application logs (daily rotation)
├── run.py                      # Dev entry point
├── requirements.txt            # Python dependencies
└── citadel.service             # Systemd unit file
```

---

## Configuration

All settings live in `data/config/settings.yaml`. Create it via the Settings UI or manually:

```yaml
llm:
  provider: anthropic
  api_key: sk-ant-...
  model: claude-sonnet-4-6

search:
  provider: duckduckgo          # duckduckgo | brave | serpapi
  max_results: 10
  brave_api_key: ""
  serpapi_key: ""

email:
  smtp_host: smtp.gmail.com
  smtp_port: 587
  smtp_user: you@gmail.com
  smtp_password: your-app-password
  from_address: you@gmail.com
  use_tls: true

slack:
  default_webhook: ""

discord:
  default_webhook: ""

sms:
  provider: twilio
  account_sid: ""
  auth_token: ""
  from_number: ""

system_state: production        # set to "dev" to suppress scheduled LLM calls
```

### Dev mode

During active development, set `system_state: dev` to prevent all scheduled runs from firing. Manual runs (UI "Run" button) still work. Toggle via the API:

```bash
POST /api/admin/system-state  {"system_state": "dev"}
GET  /api/admin/system-state
```

---

## Scheduling

Each interest, resource, and summary report has its own schedule:

```yaml
schedule:
  type: interval          # interval | weekly | cron | manual
  interval_value: 1
  interval_unit: days     # minutes | hours | days | weeks
  run_time: "20:00"       # HH:MM UTC (weekly type)
  days_of_week: [0,1,2]   # 0=Mon … 6=Sun (weekly type)
  cron_expression: "0 20 * * *"  # (cron type)
```

System jobs (always active):
- **IOC maintenance** — 02:00 UTC daily, prunes expired entries
- **IOC collection** — 03:00 UTC daily, pulls all enabled feeds

---

## API

The full API is documented via OpenAPI at `http://localhost:8000/docs` when running. All endpoints require session authentication except `/login`, `/health`, `/static/*`, and `/api/auth/*`.

| Router | Prefix | Purpose |
|---|---|---|
| `auth_router` | (none) | Login page, MFA, logout, `/api/auth/me` |
| `interests` | `/api/interests` | CRUD, run, reports, activity |
| `resources` | `/api/resources` | CRUD, run, reports |
| `summary_reports` | `/api/summary-reports` | CRUD, run, report files |
| `iocs` | `/api/iocs` | IOC CRUD, counts, bulk CSV upload |
| `ioc_config` | `/api/ioc-config` | Feed source config, sync status, manual pull |
| `users` | `/api/users` | User CRUD, MFA reset (admin) |
| `settings` | `/api/settings` | Settings CRUD, test endpoints (LLM, email, SMS, Discord) |
| `logs` | `/api/logs` | Recent log lines, archive listing |
| `admin` | `/api/admin` | Backup/restore, build-package, self-update, factory reset |

---

## Development

```bash
# Create venv
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Start (foreground, no reload)
python run.py

# Start (background, with PID tracking)
bash StartCitadel.sh

# Stop
bash StopCitadel.sh

# View logs
tail -f logs/citadel.log
```

There is no test suite, linter, type checker, or formatter. Verification is manual — start the server and exercise the UI or API.

---

## Deployment

### Build a package

```bash
bash deploy/build_package.sh
# → deploy/nxcitadel-<timestamp>.tar.gz
# → deploy/nxcitadel-latest.tar.gz (symlink)
```

Or via the UI: Admin panel → **Build Package** → **Download Package**.

### One-line install on any Linux server

```bash
curl -fsSL https://www.antonizick.com/nxcitadel/get.sh | sudo bash
```

### Self-update (from within the app)

Admin panel → **Update** — downloads the latest package, backs up data, extracts via rsync, reinstalls dependencies, and restarts the service. All streamed over SSE.

### Production recommendations

- Run behind a reverse proxy (nginx, Caddy) for HTTPS termination
- No built-in rate limiting — add at the proxy layer
- Change the default `admin / admin` credentials immediately
- Enable MFA on all accounts

---

## Security

- Session cookies with 12-hour TTL
- Passwords hashed with bcrypt
- TOTP MFA enforced for manager/admin roles (5-minute pending challenge expiry)
- Admins can be flagged `mfa_exempt`
- Auth middleware runs on all paths except login, health, static, and auth API
- Default admin seeded on first start — **change password immediately**

---

## License

See the repository for license details.
