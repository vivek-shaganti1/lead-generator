# Lead Generator

Finds local businesses that have **no working website**, qualifies them, and runs a
throttled, compliance-gated cold-email campaign offering to build one — with reply
handling, follow-ups and a dashboard on top.

The API's own description says it best: *"Finds businesses with no working website and
runs compliant cold outreach offering to build one."*

- **Backend** — FastAPI + SQLAlchemy 2 + Alembic, Celery workers on Redis, Postgres.
- **Frontend** — Next.js 15 / React 19 dashboard (App Router, standalone output).
- **Orchestration** — one Docker image for `api` / `worker` / `beat`, plus Postgres,
  Redis and the frontend, wired together in `docker-compose.yml`.

---

## What it actually does

1. **Discovery.** You give it a bounding box (or a named area) and a set of business
   categories. It queries **OpenStreetMap via Overpass** — free, politeness-throttled —
   and optionally falls back to **Google Places** when OSM coverage for the area looks
   thin (fewer than 15 results). Candidates from both sources are de-duplicated and
   merged into `businesses`.
2. **Qualification & enrichment.** For each business without a mapped website, a worker
   checks the web presence (`LIVE`, `BROKEN`, `MISSING`, `SOCIAL`, `UNKNOWN`), finds a
   contact address from OSM tags or by scraping the site, validates it (syntax, role
   account, optional MX lookup), and resolves the business's local timezone from its
   coordinates.
3. **Scoring.** Every lead gets an explainable 0–100 score with a named breakdown —
   `web_presence`, `category`, `email_quality`, `mailbox_type`, `contactability`,
   `social_signal` — so the dashboard can show *why* a lead ranked where it did. The
   warmest signal is `SOCIAL` (they market online but have no site), then `BROKEN`.
4. **Outreach.** A Celery beat job runs every 5 minutes; a throttle decides whether
   anything actually goes out. Emails are Jinja-rendered from campaign templates, carry
   `List-Unsubscribe` / `List-Unsubscribe-Post` headers and a CAN-SPAM footer, and embed a
   1×1 open-tracking pixel. Follow-ups thread onto the original message via
   `In-Reply-To` / `References`.
5. **Inbox.** IMAP polling pulls recent mail, parses it (including DSN bounces), matches
   it back to a lead by `Message-ID` chain or sender address, and classifies the reply —
   rule-based by default, **Groq** LLM when `AI_CLASSIFY_REPLIES` is on. Unsubscribe
   requests and bounces are enforced automatically; positive replies ping **Telegram**.
6. **Stats.** Daily rollups, a funnel, timeseries and per-country/per-category
   breakdowns feed the dashboard and the nightly Telegram digest.

---

## Architecture

### Pipeline

```mermaid
graph LR
  subgraph Discovery
    A[Overpass / OSM] --> C[dedupe + merge]
    B[Google Places<br/>fallback] --> C
    C --> D[(businesses)]
  end

  subgraph Enrichment
    D --> E[website check<br/>LIVE / BROKEN / MISSING / SOCIAL]
    E --> F[email finder<br/>map tags + site scrape]
    F --> G[validator<br/>syntax / role / MX]
    G --> H[scoring 0-100]
  end

  H --> I{compliance gate<br/>country / suppression /<br/>approval / unsafe mailbox}
  I -->|blocked| Z[DO_NOT_CONTACT]
  I -->|allowed| J[(leads)]

  subgraph Outreach
    J --> K{throttle<br/>daily cap / warmup /<br/>send window / per-domain}
    K -->|slot| L[render template]
    L --> M[SMTP transport<br/>or DRY_RUN]
    M --> N[(email_messages)]
    N --> O[follow-ups<br/>+3d, +7d]
    O --> K
  end

  subgraph Inbox
    P[IMAP poll] --> Q[parse + match lead]
    Q --> R[classify<br/>rules or Groq]
    R --> S[(inbound_messages)]
    R -->|UNSUBSCRIBE / BOUNCE| Y[suppression list]
    R -->|POSITIVE| T[Telegram alert]
  end

  N --> U[stats rollup]
  S --> U
  U --> V[(daily_stats)]
  V --> W[dashboard + digest]
```

### Service topology

```mermaid
graph TD
  User[Browser] --> FE["frontend<br/>Next.js 15 :3000"]
  Recipient[Email recipient] -->|"/u/{token}, /t/o/{token}.gif"| API
  FE -->|"REST + JWT"| API["api<br/>FastAPI + uvicorn :8000"]

  API --> PG[("postgres:16<br/>:5432")]
  API --> RD[("redis:7<br/>:6379")]

  BEAT["beat<br/>Celery scheduler"] --> RD
  RD --> WORK["worker<br/>Celery"]
  WORK --> PG

  WORK -->|discovery| OSM[Overpass API]
  WORK -->|discovery fallback| GP[Google Places]
  WORK -->|send| SMTP[SMTP]
  WORK -->|poll| IMAP[IMAP]
  WORK -->|classify| GROQ[Groq API]
  WORK -->|notify| TG[Telegram]
```

`api`, `worker` and `beat` are the *same* image with a different argument to
`backend/entrypoint.sh`. Migrations (`alembic upgrade head`) run once, from the `api`
container only.

---

## Quick start

### Option A — Docker Compose (the whole stack)

```bash
cp .env.example .env
# Generate a real secret and paste it into SECRET_KEY:
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
# Then edit .env: ADMIN_EMAIL, ADMIN_PASSWORD, COMPANY_*, SENDER_*, SMTP_*, IMAP_*.
# Leave DRY_RUN=true for the first few batches.

make up          # docker compose up -d --build
make logs        # follow every service; `make logs s=api` for one
```

| Surface | URL |
| --- | --- |
| Dashboard | <http://localhost:3000> |
| API root | <http://localhost:8000> |
| OpenAPI docs | <http://localhost:8000/docs> (disabled when `ENV=prod`) |
| Health | <http://localhost:8000/api/system/health> |

On first boot the API creates the schema, seeds the admin user from
`ADMIN_EMAIL`/`ADMIN_PASSWORD`, and creates the default outreach campaign. Log in at
<http://localhost:3000/login> with those credentials.

Stop it with `make down` (volumes are preserved).

> **`.env` is read from the repo root**, resolved from the package location rather than
> the working directory — so `make dev-backend`, `celery` and `alembic` all see the same
> file even though they run from `backend/`. The suite ignores it entirely (`ENV=test`)
> so a local edit can never turn into a red build on one machine only.
>
> `DATABASE_URL` and `REDIS_URL` in `.env` are the **local-dev** values; docker-compose
> overrides both with its in-network hostnames, so a container never reads them. The
> shipped default is SQLite, which means a fresh clone runs with no services at all. A
> relative SQLite path is resolved against the repo root too, so the app and `alembic`
> can't end up pointed at two different files.

### Option B — Local development

You still need Postgres and Redis; the easiest route is to start just those from
compose and run the app processes on the host.

```bash
docker compose up -d postgres redis        # both are published on 127.0.0.1

cp .env.example .env
# Point the host processes at the published ports rather than the compose hostnames:
#   DATABASE_URL=postgresql+psycopg://leadgen:leadgen@localhost:5432/leadgen
#   REDIS_URL=redis://localhost:6379/0

make install        # creates backend/.venv (Python 3.13) + npm ci in frontend/
make migrate        # alembic upgrade head
```

Then run each process in its own terminal:

```bash
make dev-backend    # uvicorn app.main:app --reload  -> :8000
make dev-frontend   # next dev                       -> :3000
make worker         # celery worker
make beat           # celery beat (scheduled jobs)
```

Backend commands read `backend/.env` — `Settings` is configured with
`env_file=".env"` relative to the process's working directory, and the Make targets
`cd backend` first. Either symlink the root file (`ln -s ../.env backend/.env`) or
export the variables in your shell.

### Make targets

| Target | Does |
| --- | --- |
| `make help` | List every target |
| `make install` | `backend/.venv` + `requirements-dev.txt`, then `npm ci` |
| `make dev-backend` / `make dev-frontend` | Reloading API / Next dev server |
| `make worker` / `make beat` | Celery worker / beat scheduler |
| `make test` / `make test-cov` | pytest (SQLite, no services needed) |
| `make lint` / `make lint-fix` | ruff over `app` and `tests` |
| `make typecheck` | `tsc --noEmit` on the frontend |
| `make migrate` / `make migration m="..."` | Apply / autogenerate Alembic revisions |
| `make up` / `make down` / `make restart` / `make ps` / `make logs` | Compose lifecycle |
| `make shell` | Python shell inside the `api` container |
| `make clean` | Drop caches, coverage, `.next` |

---

## Environment variables

Copy `.env.example` to `.env`. Compose injects it into `api`, `worker` and `beat`, and
overrides `DATABASE_URL` / `REDIS_URL` to the in-network hostnames. Defaults below are
the ones in `backend/app/config.py`.

### Core

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENV` | `dev` | `dev` \| `test` \| `prod`. `prod` disables `/docs` and warns on default secrets. |
| `DEBUG` | `true` | Verbose logging. |
| `SECRET_KEY` | *(insecure default)* | Signs JWTs and tracking tokens. **Minimum 16 chars — validated at import.** |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Must be reachable by the *recipient's* mail client: serves the unsubscribe page and the open pixel. |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins. |
| `AUTH_RATE_LIMIT` | `10/minute` | Throttle on `POST /api/auth/login`, per client IP. Storage is in-memory, so the limit is **per uvicorn worker** — with `WEB_CONCURRENCY=2` the effective ceiling is ~20/min. Disabled when `ENV=test`. |

### Database & queue

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `leadgen` / `leadgen` / `leadgen` | Consumed by the `postgres` container and interpolated into `DATABASE_URL`. |
| `DATABASE_URL` | `postgresql+psycopg://leadgen:leadgen@postgres:5432/leadgen` | SQLAlchemy URL. Overridden by compose. |
| `REDIS_URL` | `redis://redis:6379/0` | Celery broker **and** result backend. Overridden by compose. |

### Dashboard login

| Variable | Default | Purpose |
| --- | --- | --- |
| `ADMIN_EMAIL` | `admin@example.com` | The single admin account. Must be a deliverable address — `EmailStr` rejects reserved domains like `admin@localhost`, and a rejected address means you cannot log in. Changing this creates a *second* admin rather than renaming the first. |
| `ADMIN_PASSWORD` | `changeme123` | Re-applied on every boot: rotate it here, restart, and the new password takes effect (logged as `admin.password_rotated_from_env`). |
| `JWT_TTL_MINUTES` | `720` | Access-token lifetime. |

There is **no sign-up page**. The only account is the one seeded from the two variables
above, so a password saved in a browser for some other site will never authenticate here.

If you are locked out:

```bash
make whoami
```

That prints the email the API will accept, the database it is reading, and which `.env`
files it actually loaded. Set `ADMIN_PASSWORD` in `.env`, **restart the API**, and the new
password takes effect — the change is applied at boot and logged as
`admin.password_rotated_from_env`. Editing `.env` while the server is running does
nothing; nothing re-reads it.

### Sender identity (appears in every email)

| Variable | Default | Purpose |
| --- | --- | --- |
| `COMPANY_NAME` | `Your Web Studio` | Used in copy and in the footer. |
| `COMPANY_ADDRESS` | `Street, City, Country` | **Legally required** postal address in the CAN-SPAM footer. |
| `COMPANY_WEBSITE` | `https://example.com` | Linked in the footer/templates. |
| `SENDER_NAME` | `Vivek` | Display name on the `From` header. |
| `SENDER_EMAIL` | `hello@example.com` | Envelope + `From` address. Also used in the scraper user-agent. |
| `REPLY_TO_EMAIL` | *(empty)* | Falls back to `SENDER_EMAIL`. |
| `CALENDAR_LINK` | *(empty)* | Optional booking link available to templates. |

### SMTP (sending)

| Variable | Default | Purpose |
| --- | --- | --- |
| `SMTP_HOST` | *(empty)* | Empty means "not configured" in the health check. |
| `SMTP_PORT` | `587` | |
| `SMTP_USER` / `SMTP_PASSWORD` | *(empty)* | Credentials. |
| `SMTP_STARTTLS` | `true` | STARTTLS on a plain connection. |
| `SMTP_SSL` | `false` | Implicit TLS instead (usually port 465). |
| `SMTP_TIMEOUT` | `30` | Seconds to wait on the SMTP conversation. |

### IMAP (replies & bounces)

| Variable | Default | Purpose |
| --- | --- | --- |
| `IMAP_HOST` | *(empty)* | Empty disables the `poll_inbox` task. |
| `IMAP_PORT` | `993` | |
| `IMAP_USER` / `IMAP_PASSWORD` | *(empty)* | Credentials. |
| `IMAP_SSL` | `true` | |
| `IMAP_FOLDER` | `INBOX` | |
| `IMAP_POLL_SECONDS` | `120` | Doubles as the beat interval for inbox polling. |

### Sending policy

| Variable | Default | Purpose |
| --- | --- | --- |
| `DRY_RUN` | `true` | Renders and records every message but delivers nothing. |
| `DAILY_SEND_CAP` | `200` | Hard ceiling per day. |
| `WARMUP_ENABLED` | `true` | Ramp the cap over the first sending days. |
| `WARMUP_START` | `20` | Day-1 cap. |
| `WARMUP_INCREMENT` | `15` | Added per day elapsed since the first non-dry-run send, up to `DAILY_SEND_CAP`. |
| `MIN_SECONDS_BETWEEN_SENDS` | `45` | Global pacing between any two sends. |
| `MAX_PER_DOMAIN_PER_DAY` | `2` | Per-recipient-domain daily ceiling. |
| `SEND_WINDOW_START_HOUR` | `9` | Business hours in the **recipient's** local timezone. |
| `SEND_WINDOW_END_HOUR` | `17` | |
| `SEND_ON_WEEKENDS` | `false` | |
| `REQUIRE_MANUAL_APPROVAL` | `true` | Nothing leaves until a human approves the lead. |
| `TRACK_OPENS` | `true` | Embeds the 1×1 open pixel. Set `false` to send no pixel at all. |

### Follow-ups

| Variable | Default | Purpose |
| --- | --- | --- |
| `FOLLOWUP_ENABLED` | `true` | |
| `FOLLOWUP_DELAYS_DAYS` | `3,7` | Comma-separated, one entry per follow-up step. |
| `MAX_FOLLOWUPS` | `2` | |

### Discovery

| Variable | Default | Purpose |
| --- | --- | --- |
| `OVERPASS_URL` | `https://overpass-api.de/api/interpreter` | |
| `OVERPASS_TIMEOUT` | `180` | Seconds, passed into the Overpass QL query. |
| `OVERPASS_MIN_INTERVAL_SECONDS` | `5.0` | Client-side politeness throttle. |
| `DISCOVERY_MAX_RESULTS_PER_RUN` | `500` | Ceiling per run. |
| `GOOGLE_PLACES_ENABLED` | `false` | Paid fallback, used only where OSM coverage is thin. |
| `GOOGLE_PLACES_API_KEY` | *(empty)* | |

### Enrichment

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENABLE_WEBSITE_EMAIL_SCRAPE` | `true` | Scrape contact addresses off the business's own site. |
| `SCRAPE_TIMEOUT` | `15` | Seconds per HTTP fetch. |
| `VERIFY_MX` | `true` | DNS MX lookup before accepting an address. |
| `HTTP_USER_AGENT` | `LeadGenBot/1.0 (+contact: {email})` | Sent on every outbound probe/scrape so site owners can identify the crawler. `{email}` is filled with `SENDER_EMAIL`. |

### AI (Groq)

| Variable | Default | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | *(empty)* | Empty falls back to the deterministic rule classifier. |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Override to point at a compatible endpoint. |
| `AI_CLASSIFY_REPLIES` | `true` | Use the LLM to classify inbound replies. |
| `AI_PERSONALIZE_COPY` | `false` | Generate a personalised opening line per lead. |

### Telegram

| Variable | Default | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | *(empty)* | From @BotFather. |
| `TELEGRAM_CHAT_ID` | *(empty)* | From @userinfobot. |
| `TELEGRAM_NOTIFY_POSITIVE` | `true` | Ping on positive replies. |
| `TELEGRAM_NOTIFY_ANY_REPLY` | `false` | Ping on every reply. |
| `TELEGRAM_DAILY_DIGEST_HOUR` | `20` | UTC hour for the digest beat job. |

### Compliance

| Variable | Default | Purpose |
| --- | --- | --- |
| `BLOCKED_COUNTRIES` | 23 EU/EEA codes (`DE,AT,CH,IT,GR,FI,HU,PL,SI,SK,HR,LT,LV,EE,PT,ES,CZ,BG,RO,DK,NO,IS`) | Jurisdictions requiring prior consent for unsolicited B2B email. Leads there are discovered but never auto-mailed. |
| `HONOUR_ROLE_ACCOUNTS` | `true` | `info@`/`contact@` are allowed for B2B but tracked separately. Not in `.env.example`. |

### Frontend

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Baked in at build time (compose passes it as a build arg) and read at runtime. Must point at `API_PORT` and be reachable from the **browser**, not from inside the compose network. |

### Host ports

Only the host side of each mapping is configurable; container ports are fixed. Change
these when something else on the machine already owns a default — a second dev server on
`3000` is the common one. `postgres`, `redis` and `flower` bind to `127.0.0.1` only.

| Variable | Default | Service |
| --- | --- | --- |
| `API_PORT` | `8000` | `api` — must match `NEXT_PUBLIC_API_URL` and `PUBLIC_BASE_URL`. |
| `FRONTEND_PORT` | `3000` | `frontend` |
| `POSTGRES_PORT` | `5432` | `postgres` (loopback only) |
| `REDIS_PORT` | `6379` | `redis` (loopback only) |
| `FLOWER_PORT` | `5555` | `flower`, which only starts under `--profile debug` |

---

## API reference

All `/api/*` routes except `/api/system/health` require `Authorization: Bearer <token>`
from `POST /api/auth/login`. The `/u/*` and `/t/*` routes are deliberately public —
recipients hit them from their mail client.

### Auth

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/auth/login` | Exchange `{email, password}` for a JWT. Failures are deliberately vague. |
| `GET` | `/api/auth/me` | Current user. |

### Discovery

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/discovery/categories` | The 42 category presets with labels and Google support flags. |
| `POST` | `/api/discovery/run` | Start a run. Body needs `label` plus **either** `bbox` or `area_name`; optional `categories`, `limit` (≤5000), `use_google_fallback`, `run_async` (default `true` → queued to Celery). |
| `GET` | `/api/discovery/runs` | Recent runs (`limit`, 1–200). |
| `GET` | `/api/discovery/runs/{run_id}` | One run. |

### Leads

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/leads` | Paginated list. Filters: `status`, `country`, `category`, `approved`, `search`, `min_score`; `page`, `page_size` (≤200); `sort` ∈ `score` \| `created_at` \| `last_contacted_at`. |
| `GET` | `/api/leads/{id}` | Lead detail, with business and message history. |
| `GET` | `/api/leads/{id}/replies` | Inbound messages for the lead. |
| `PATCH` | `/api/leads/{id}` | Partial update; setting `approved` runs the approval transition. |
| `POST` | `/api/leads/{id}/send` | Send now. `?force=true` bypasses **pacing only** — never compliance. `409` with the block reason if refused. |
| `POST` | `/api/leads/bulk` | `{lead_ids, action}` where action ∈ `approve` \| `unapprove` \| `suppress` \| `delete` \| `send_now`. |

### Campaigns

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/campaigns` | List campaigns. |
| `POST` | `/api/campaigns` | Create. Templates are rendered against a probe context, so a broken template is rejected at save time (`422`). Duplicate name → `409`. |
| `PUT` | `/api/campaigns/{id}` | Update, with the same validation. |
| `POST` | `/api/campaigns/preview` | Render `{campaign_id?, lead_id?, step}` and get back `subject`, `text`, `html`. Falls back to a sample context. |

### Stats

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/stats/dashboard` | Totals, funnel, status/country/category breakdowns (`days`, 1–365). |
| `GET` | `/api/stats/timeseries` | Per-day series. |
| `GET` | `/api/stats/today` | Today's snapshot. |
| `POST` | `/api/stats/rollup` | Recompute the last `days` (1–90) of daily stats. |
| `GET` | `/api/stats/events` | Recent audit events (`limit` ≤500, optional `type`). |

### System

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/system/health` | **Unauthenticated.** DB + Redis reachability and which integrations are configured. Used by the compose healthcheck. |
| `GET` | `/api/system/config` | Non-secret view of the running configuration. |
| `GET` | `/api/system/sending` | Current throttle usage: cap, sent today, remaining. |
| `GET` | `/api/system/suppressions` | Do-not-contact list (last 500). |
| `POST` | `/api/system/suppressions` | Add `{value, reason, kind}` — `kind` is `email` or `domain`. Idempotent. |
| `DELETE` | `/api/system/suppressions/{id}` | Remove an entry. |
| `POST` | `/api/system/test/email` | Self-test send. **Honours `DRY_RUN`.** |
| `POST` | `/api/system/test/telegram` | Send a test notification. |
| `POST` | `/api/system/test/groq` | Round-trip a sample reply through the classifier. |

### Public (recipient-facing)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/u/{token}` | Unsubscribe confirmation page. |
| `POST` | `/u/{token}` | Applies the opt-out. Also handles RFC 8058 one-click `List-Unsubscribe=One-Click`. |
| `GET` | `/t/o/{token}.gif` | 1×1 open-tracking pixel. Always returns the image, valid token or not. |
| `GET` | `/` | Service banner: version, docs and health links. |

Every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and
`Referrer-Policy: no-referrer`.

---

## Scheduled jobs

Defined in `backend/app/workers/celery_app.py`; every task is written to be idempotent,
so a retried task never double-sends or double-counts.

| Task | Schedule | What it does |
| --- | --- | --- |
| `leadgen.outreach_batch` | every 5 min | Processes up to 25 due leads. The throttle decides whether anything leaves. |
| `leadgen.poll_inbox` | every `IMAP_POLL_SECONDS` (120s) | Fetches, parses, matches and classifies inbound mail. |
| `leadgen.qualify_pending` | every 10 min | Turns up to 50 discovered businesses into scored leads. |
| `leadgen.rollup_stats` | every 15 min | Recomputes the last few days of `daily_stats`. |
| `leadgen.daily_digest` | daily at `TELEGRAM_DAILY_DIGEST_HOUR`:05 UTC | Rolls up the day and sends the Telegram digest. |
| `leadgen.retention_sweep` | daily at 03:30 UTC | Data-retention purges (below). |

On-demand tasks: `leadgen.discovery_run`, `leadgen.send_lead_now`, `leadgen.alert`,
`leadgen.heartbeat`.

Worker settings worth knowing: `task_acks_late` (a killed worker re-runs its task),
`worker_prefetch_multiplier=1` (long tasks must not hog the queue), 30-minute hard and
25-minute soft time limits, and up to 3 retries per task.

---

## Compliance & anti-spam posture

This is the part that matters most, and it is enforced in code rather than in policy
documents.

**`DRY_RUN` is on by default.** Every message is rendered, recorded and marked
`dry_run=true`, but nothing is delivered. The `/api/system/test/email` endpoint honours
it too. Leave it on until you have watched several batches in the dashboard.

**`REQUIRE_MANUAL_APPROVAL` is on by default.** Leads sit in `NEEDS_APPROVAL` until a
human approves them in the dashboard or via `PATCH /api/leads/{id}`.

**The compliance gate (`can_contact` / `enforce`) runs immediately before every send**,
not just at queue time, and refuses on any of:

- no email address, or an unsafe mailbox (`noreply@`, `abuse@`, `postmaster@`);
- the lead is already in a terminal state (`UNSUBSCRIBED`, `BOUNCED`, `DO_NOT_CONTACT`,
  `NEGATIVE`, `WON`);
- the address or its domain is on the suppression list;
- the business is in a `BLOCKED_COUNTRIES` jurisdiction — **or its country is unknown**,
  because an unprovable jurisdiction is treated as not permitted;
- manual approval is required and hasn't been given.

Suppression, unsafe-mailbox and blocked-country refusals are *hard*: the lead is moved
to `DO_NOT_CONTACT`. `POST /api/leads/{id}/send?force=true` bypasses pacing only; the
compliance gate is never bypassable.

**Unsubscribe is one click and irreversible.** Each lead carries a random
`unsubscribe_token`. Every email carries `List-Unsubscribe` and
`List-Unsubscribe-Post` headers (RFC 8058) plus a footer link to
`{PUBLIC_BASE_URL}/u/{token}`. Opting out flips the lead to `UNSUBSCRIBED` and adds the
address to the suppression list, so a future discovery run cannot resurrect it. A real
postal address (`COMPANY_ADDRESS`) is required in the footer for CAN-SPAM.

**Throttling is layered.** A send needs a slot that satisfies *all* of: the daily cap
(warmup-ramped from `WARMUP_START` by `WARMUP_INCREMENT` per day elapsed since the first
*real* — non-dry-run — send, capped at `DAILY_SEND_CAP`), the global
minimum gap between sends, the per-recipient-domain daily ceiling, the campaign's own
`daily_cap` if one is set, the business-hours window **computed in the recipient's own
timezone** from their coordinates, and the weekend rule. `GET /api/system/sending` shows
the live picture. A campaign hitting its own cap pauses only that campaign; the global
cap stops the whole batch.

**Bounces stop the sequence.** DSN messages are parsed out of the inbox, the lead is
marked `BOUNCED`, and an SMTP "recipient refused" is treated the same way.

**Retention runs nightly** (`leadgen.retention_sweep`):

| Sweep | Window | Why |
| --- | --- | --- |
| Blank Google-sourced detail fields (place ids kept) | 30 days | Google Maps Platform caching terms. |
| Delete never-contacted leads/businesses | 180 days | GDPR/DPDP data minimisation. |
| Delete audit events | 365 days | |
| Redact inbound message bodies | 90 days | |

**Login is rate limited** to `AUTH_RATE_LIMIT` (default `10/minute`) per client IP —
it is the one unauthenticated endpoint that does bcrypt work. The limiter is in-memory,
so the ceiling is per uvicorn worker rather than global; point `slowapi` at Redis if you
need it enforced across workers. `/docs` is disabled when `ENV=prod`, and on boot with
`ENV=prod` the app logs an error if `SECRET_KEY` or `ADMIN_PASSWORD` are still at their
defaults.

Passwords are hashed with `bcrypt` (cost 12) called directly — not through `passlib`,
which is unmaintained and incompatible with `bcrypt >= 4.1`. The stored format is
unchanged (`$2b$`), so hashes written by either path verify.

> Nothing here is legal advice. Confirm your own obligations before shortening
> `BLOCKED_COUNTRIES` or turning off `DRY_RUN`.

---

## Testing

The backend suite is self-contained: `backend/tests/conftest.py` sets the environment
**before** anything imports `app.config` (the settings object is a module-level
singleton), pinning `DATABASE_URL` to a local SQLite file and stubbing SMTP (a recording
transport), Telegram, Groq and the Overpass politeness delay. **No Postgres or Redis is
required to run the tests.**

```bash
make test                       # 330 tests, ~20s
make test-cov                   # with a coverage report
make lint                       # ruff check app tests
make typecheck                  # tsc --noEmit on the frontend

# a single file or test
cd backend && .venv/bin/pytest tests/test_dispatcher.py -v
cd backend && .venv/bin/pytest -k throttle
```

The SQLite file lives at `$TMPDIR/leadgen_test.db` and is dropped/recreated per test.
Because the path is fixed, **two pytest processes on the same machine will clobber each
other** — run one at a time, or set a distinct `TMPDIR`.

CI (`.github/workflows/ci.yml`) runs the same things on every push and PR: a backend job
(Python 3.13 → `ruff check` → `pytest`) and a frontend job (Node 20 → `npm ci` →
`tsc --noEmit` → `next build`).

### Verifying a real install

Unit tests prove the parts; these two scripts prove the wiring. Run them after a deploy,
a config change, or a dependency bump.

**`ops/smoke_test.py`** — 37 assertions over the live HTTP surface of a *running* API:
auth (including that a bad password 401s and an unauthenticated read is refused), every
read endpoint, suppression create/list/delete round-trip and its idempotency, enum
validation on filters, that `/api/system/config` leaks no secret, and that the tracking
pixel returns a real GIF even for a forged token.

```bash
SMOKE_BASE=http://127.0.0.1:8000 \
SMOKE_EMAIL=you@yourdomain.com SMOKE_PASSWORD=... \
  backend/.venv/bin/python ops/smoke_test.py
```

**`ops/pipeline_check.py`** — 25 assertions driving the whole pipeline in-process with
no network at all: candidates → dedupe → businesses → qualification → scoring → approval
→ dry-run send → rendered message → follow-up scheduling → audit event → stats rollup,
plus the compliance gates. It asserts the things that matter legally — that no raw Jinja
survives into a sent message, that every message carries an unsubscribe link and a postal
address, and that a business with a working website never becomes a lead.

```bash
cd backend && env PYTHONPATH="$PWD" DRY_RUN=true \
  DATABASE_URL="sqlite:///$TMPDIR/check.db" \
  ENABLE_WEBSITE_EMAIL_SCRAPE=false VERIFY_MX=false \
  .venv/bin/python ../ops/pipeline_check.py
```

`ENABLE_WEBSITE_EMAIL_SCRAPE=false` matters: `qualify_business(check_site=False)` skips
the *website* probe but not the email scraper, so without it the run reaches out to real
third-party sites.

---

## Project layout

```
.
├── docker-compose.yml          postgres, redis, api, worker, beat, frontend
├── .env.example                every setting, commented
├── Makefile                    developer tasks
├── .github/workflows/ci.yml    backend + frontend CI
│
├── backend/
│   ├── Dockerfile              one image, non-root, used by api/worker/beat
│   ├── entrypoint.sh           role dispatch: api | worker | beat | flower | shell
│   ├── requirements*.txt       runtime / dev pins
│   ├── pytest.ini              testpaths, strict markers
│   ├── alembic/                migrations (c3a33ae4888b = initial schema)
│   └── app/
│       ├── main.py             app factory, CORS, security headers, bootstrap
│       ├── config.py           pydantic-settings Settings singleton
│       ├── db.py               engine, SessionLocal, session_scope
│       ├── models.py           User, Business, DiscoveryRun, Campaign, Lead,
│       │                       EmailMessage, InboundMessage, Suppression,
│       │                       DailyStat, Event, AppSetting
│       ├── schemas.py          Pydantic request/response models
│       ├── security.py         password hashing, JWT, current-user dependency
│       ├── api/                auth, discovery, leads, campaigns, stats,
│       │                       system, public
│       ├── services/
│       │   ├── pipeline.py     ingest_candidates() + qualify_business()
│       │   ├── stats.py        rollups, funnel, timeseries, digest
│       │   ├── discovery/      base, categories, overpass, google_places, merge
│       │   ├── enrichment/     website_check, email_finder, validator, scoring
│       │   ├── outreach/       templates, sender, throttle, dispatcher, tracking
│       │   ├── inbox/          imap_client, parser, matcher, processor
│       │   ├── compliance/     policy, unsubscribe, retention
│       │   ├── ai/             groq, rules
│       │   └── notify/         telegram
│       └── workers/            celery_app.py (beat schedule), tasks.py
│
├── ops/
│   └── smoke_test.py           end-to-end HTTP check against a running API
└── frontend/
    ├── Dockerfile              standalone Next.js build
    ├── next.config.mjs         output: "standalone"
    ├── app/
    │   ├── page.tsx            dashboard: tiles, funnel, timeseries, breakdowns
    │   ├── login/              JWT login
    │   ├── leads/              filterable list + bulk actions
    │   ├── leads/[id]/         lead detail, message history, replies
    │   ├── discovery/          launch runs, watch run history
    │   ├── campaigns/          template editing + live preview
    │   └── settings/           health, config, sending quota, suppressions,
    │                           connection tests (SMTP / Telegram / Groq)
    ├── components/             Shell (nav), charts, ui primitives
    └── lib/                    api client (token handling, error shaping), types
```

### Data model at a glance

A `Business` is a place discovered from OSM or Google, de-duplicated on a
`dedupe_key` built from name + coordinates + phone. A `Lead` is one contactable email
address for a business inside a `Campaign`, and moves through `NEW` →
`NEEDS_APPROVAL` → `READY` → `QUEUED` → `CONTACTED` → `FOLLOWED_UP` → `REPLIED` →
`POSITIVE`/`NEUTRAL`/`NEGATIVE`/`WON`, with `UNSUBSCRIBED`, `BOUNCED`,
`DO_NOT_CONTACT`, `NEGATIVE`, `WON` and `FAILED` as exits. `EmailMessage` rows record
what was sent (one per step, which is what makes re-sends idempotent);
`InboundMessage` rows record what came back.
