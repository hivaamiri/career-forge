# Job Pulse & Career-Ops Bridge: Architecture & Implementation Tasks

An automated, 24/7 background job discovery service tailored for the German engineering market. It captures live job alerts from **StepStone, XING, and LinkedIn** via email ingestion, polls the **Bundesagentur für Arbeit** and **Personio/ATS** public APIs, filters matches, persists state in SQLite, and dispatches instant Telegram alerts with direct actions to trigger `career-ops` evaluations.

---

## 1. System Architecture

```
┌────────────────────────────────────────────────────────┐
│                   INGESTION LAYER                      │
├────────────────────────────┬───────────────────────────┤
│    Direct API Polling      │    Push / Alert Ingest    │
│  - Bundesagentur API       │  - StepStone Alert Emails │
│  - Target Personio XML/JSON│  - XING Alert Emails      │
│  - Greenhouse / Ashby APIs │  - LinkedIn Alert Emails  │
└─────────────┬──────────────┴─────────────┬─────────────┘
              │                            │
              ▼                            ▼
┌────────────────────────────────────────────────────────┐
│             PIPELINE & DE-DUPLICATION ENGINE           │
│                                                        │
│  1. Canonical URL Resolver (unwraps click-trackers)    │
│  2. Fast Heuristic Filter (Role / Tech / Location)     │
│  3. SQLite State Store (tracks Job ID / URL hash)      │
└───────────────────────────┬────────────────────────────┘
                            │ (If Unseen & Matches Filter)
                            ▼
┌────────────────────────────────────────────────────────┐
│               NOTIFICATION & ACTION LAYER              │
│                                                        │
│  1. Instant Dispatch (Telegram Bot API)                │
│  2. Interactive Inline Buttons:                        │
│     - [Open Posting]                                   │
│     - [Queue to Career-Ops Pipeline]                   │
└────────────────────────────────────────────────────────┘
```

---

## 2. Component Specifications

### 2.1 State Store (`src/db.py`)
* **Storage engine:** SQLite3 with WAL mode enabled.
* **Database path:** `data/jobs.sqlite`
* **Schema:**
  ```sql
  CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY,               -- SHA-256 hash of canonical URL
      source TEXT NOT NULL,              -- stepstone | linkedin | xing | arbeitsagentur | personio | ats
      title TEXT NOT NULL,
      company TEXT NOT NULL,
      location TEXT,
      url TEXT NOT NULL,
      canonical_url TEXT NOT NULL,
      discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      status TEXT DEFAULT 'notified',     -- notified | queued_career_ops | applied | dismissed
      meta_json TEXT
  );
  CREATE INDEX IF NOT EXISTS idx_jobs_canonical ON jobs(canonical_url);
  ```

### 2.2 Ingestion Module A: Email Stream (`src/ingest/email_stream.py`)
* Connects via IMAP/SSL (`imap.gmail.com` or custom host) using an application-specific password.
* Searches for unread messages matching:
  * `FROM "stepstone.de"`
  * `FROM "xing.com"`
  * `FROM "linkedin.com"`
* Parses HTML email body:
  * Extracts job title, company name, location, and tracking links.
  * Resolves tracking URLs using `HEAD` HTTP requests with browser headers to obtain the target landing URL.
* Marks processed emails as read.

### 2.3 Ingestion Module B: Direct API Poller (`src/ingest/arbeitsagentur.py` & `src/ingest/ats_poller.py`)
* **Bundesagentur für Arbeit:**
  * Public REST endpoint: `https://rest.arbeitsagentur.de/opensearch/vam-berufe-service/v1/stellenangebote`
  * Zero auth required. Fetches daily postings by keyword, city, and radius.
* **Personio Boards:**
  * Fetches company XML/JSON feeds directly: `https://<company>.jobs.personio.de/xml`
* **Greenhouse / Ashby / Lever:**
  * Direct public JSON endpoints for curated target company lists.

### 2.4 Heuristic Matcher (`src/matcher.py`)
Applies token and regex matching against title, location, and snippets:
* **Inclusion Patterns:** `(?i)\b(backend|software\s*engineer|systems\s*engineer|network|devops|cloud|infrastructure|linux|platform)\b`
* **Exclusion Patterns:** `(?i)\b(intern|praktikant|working\s*student|werkstudent|trainee|sales|marketing|frontend\s*only)\b`
* **Location Filtering:** Target region, Germany-wide, or Remote.

### 2.5 Telegram Dispatcher (`src/notifier.py`)
* Uses Telegram Bot API via `httpx`.
* Structured HTML template:
  ```text
  🎯 <b>New Match Found: {company}</b>
  📋 <b>Role:</b> {title}
  📍 <b>Location:</b> {location}
  🏷 <b>Source:</b> {source}

  🔗 <a href="{canonical_url}">Open Job Posting</a>
  ```
* Inline buttons:
  * `[Open Listing]` -> External link to original job board.
  * `[Queue Career-Ops]` -> Callback query triggering automatic addition into `career-ops/data/pipeline.md`.

---

## 3. Directory Layout

```
job-pulse/
├── config/
│   ├── config.example.yaml
│   └── config.yaml               # API tokens, IMAP credentials, filters (git-ignored)
├── data/
│   └── jobs.sqlite               # Local state database (git-ignored)
├── src/
│   ├── __init__.py
│   ├── config.py                 # Configuration loader and schema validation
│   ├── db.py                     # SQLite state layer and deduplication
│   ├── matcher.py                # Regex filtering rules
│   ├── notifier.py               # Telegram bot client and payload dispatch
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── email_stream.py       # IMAP consumer for StepStone / LinkedIn / XING
│   │   ├── arbeitsagentur.py     # Bundesagentur public API client
│   │   └── ats_poller.py         # Personio XML and ATS poller
│   └── bridge_careerops.py       # Appends jobs into career-ops pipeline.md
├── main.py                       # Orchestrator & daemon loop
├── requirements.txt
└── systemd/
    ├── job-pulse.service
    └── job-pulse.timer
```

---

## 4. Implementation Checklist & Tasks

### Task Group 1: Core Foundation & Telegram Dispatch
- [x] **Task 1.1:** Create `requirements.txt` (`httpx`, `pyyaml`, `beautifulsoup4`, `pydantic`).
- [x] **Task 1.2:** Implement `config/config.example.yaml` and `src/config.py` parser.
- [x] **Task 1.3:** Build `src/db.py` (database schema initialization, `is_seen(hash)`, `save_job()`).
- [x] **Task 1.4:** Build `src/notifier.py` (Telegram bot integration, text formatting, inline button support).
- [x] **Task 1.5:** Write sanity check script to verify Telegram test message transmission.

### Task Group 2: Email Ingestion (StepStone, XING, LinkedIn)
- [x] **Task 2.1:** Implement `src/ingest/email_stream.py` to connect via IMAP with app-password authentication.
- [x] **Task 2.2:** Build parsers for StepStone, LinkedIn, and XING notification email formats.
- [x] **Task 2.3:** Implement canonical URL unwrap function (`HEAD` redirects resolver).
- [x] **Task 2.4:** Build `src/matcher.py` (title/keyword regex checks).
- [x] **Task 2.5:** Connect email stream -> filter -> SQLite -> Telegram alert.

### Task Group 3: Direct API Ingestion (Arbeitsagentur & Personio)
- [x] **Task 3.1:** Implement `src/ingest/arbeitsagentur.py` using `rest.arbeitsagentur.de` open search.
- [x] **Task 3.2:** Implement `src/ingest/ats_poller.py` for target company Personio XML feeds.
- [x] **Task 3.3:** Integrate both pollers into periodic execution loop.

### Task Group 4: Career-Ops Handshake & Automation
- [ ] **Task 4.1:** Implement `src/bridge_careerops.py` to parse markdown table in `career-ops/data/pipeline.md` and append verified candidates.
- [ ] **Task 4.2:** Implement Telegram polling callback handler so pressing `[Queue Career-Ops]` runs `bridge_careerops.py` automatically.
- [ ] **Task 4.3:** Create systemd unit files (`job-pulse.service` and `job-pulse.timer`) for unattended Linux background execution.