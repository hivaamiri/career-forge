# Job Pulse & Career-Ops Bridge

An automated, 24/7 background job discovery service tailored for the German engineering market. It captures live job alerts from **StepStone, XING, and LinkedIn** via email ingestion, polls the **Bundesagentur für Arbeit** and **Personio/ATS** public APIs, filters matches, persists state in SQLite, and dispatches instant Telegram alerts with interactive buttons to trigger `career-ops` pipeline additions.

---

## Architecture Overview

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
│     - [🌐 Open Listing] -> Original job board posting  │
│     - [📥 Queue Career-Ops] -> Appends to pipeline.md  │
└────────────────────────────────────────────────────────┘
```

---

## Quickstart

### 1. Prerequisites & Virtualenv
Ensure Python 3.10+ is installed:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configuration
Copy the configuration template:
```bash
cp config/config.example.yaml config/config.yaml
```
Populate your credentials in `config/config.yaml` or set environment variables:
- `TELEGRAM_BOT_TOKEN`: Your Telegram Bot API token from [@BotFather](https://t.me/BotFather).
- `TELEGRAM_CHAT_ID`: Your personal or channel Telegram chat ID.
- `IMAP_USERNAME` / `IMAP_PASSWORD`: IMAP mailbox credentials (e.g. Gmail app password).

### 3. Verify Telegram Setup
Run the sanity check script to verify credentials and send a test alert:
```bash
python scripts/test_telegram.py
```

### 4. Running the Service
- **Single sweep (all enabled sources once):**
  ```bash
  python main.py --once
  ```
- **Continuous daemon mode:**
  ```bash
  python main.py
  ```

---

### Telegram Bot Command Center

You can configure scraping keywords, locations, search radius, and trigger Career-Ops evaluations dynamically straight from your Telegram chat:

| Command | Description | Example |
| :--- | :--- | :--- |
| **Send Document** | Drop your CV (`.pdf`, `.txt`, `.md`) directly in chat to ingest | *(Attach file in Telegram)* |
| `/profile` | View active candidate profile and skills | `/profile` |
| `/set_name <name>` | Set candidate name | `/set_name Hiva Amiri` |
| `/set_title <title>` | Set candidate title | `/set_title Chemiker / M.Sc.` |
| `/set_contact <info>` | Update email, phone, location | `/set_contact hiva@test.de \| +49 170 123456 \| Berlin` |
| `/add_skill <skills>` | Add analytical/lab skills | `/add_skill HPLC, GC-MS, Titration, GMP` |
| `/set_skills <skills>` | Overwrite analytical skills | `/set_skills HPLC, GC, UV-Vis` |
| `/set_salary <text>` | Set salary expectation | `/set_salary ca. 65.000 € p.a.` |
| `/set_availability <text>` | Set start date / notice period | `/set_availability ab sofort` |
| `/feed_cv <text>` | Paste raw CV text into chat | `/feed_cv Profil: M.Sc. Chemiker...` |
| `/feed_template <text>` | Save custom cover letter template | `/feed_template Sehr geehrte...` |
| `/pipeline` | View active Career-Ops pipeline and match scores | `/pipeline` |
| `/evaluate` | Scrape queued JDs and calculate match score against profile | `/evaluate` |
| `/generate` | Generate tailored German Anschreiben & CV (HTML & MD) | `/generate` |
| `/config` | View active keywords, locations, radius, and ATS targets | `/config` |
| `/add_keyword <text>` | Add one or more search keywords | `/add_keyword biochemie, cta` |
| `/del_keyword <text>` | Remove a keyword | `/del_keyword qualitätskontrolle` |
| `/set_keywords <list>` | Overwrite all search keywords | `/set_keywords chemie, chemielaborant, analytik` |
| `/add_location <city>` | Add target city or region | `/add_location Stuttgart, Köln` |
| `/del_location <city>` | Remove a location | `/del_location Hamburg` |
| `/set_locations <list>` | Overwrite all locations | `/set_locations Berlin, München, Remote` |
| `/set_radius <km>` | Set Bundesagentur search radius | `/set_radius 75` |
| `/add_company <slug>` | Add target Personio company feed | `/add_company biontech` |
| `/del_company <slug>` | Remove Personio company | `/del_company acme` |
| `/sweep` | Trigger an immediate live scan across all scrapers | `/sweep` |
| `/reset_config` | Revert all overrides back to `config.yaml` defaults | `/reset_config` |
| `/help` | Display command cheat-sheet | `/help` |

All changes made via Telegram are persisted to SQLite (`settings` table) and take effect immediately without restarting the service.

---

## Career-Ops Engine (Scraping, Scoring & Application Generator)

Career-Ops automates the second half of the job hunt once a position is queued:
1. **Candidate Profile:** Configured in `career-ops/config/profile.yaml` (personal details, analytical methods, regulatory standards, work history, target roles).
2. **Job Description Scraper (`src/career_ops/jd_scraper.py`):** Automatically extracts full requirements, tasks, and company details from job URLs.
3. **Match Scorer (`src/career_ops/matcher_scorer.py`):** Scores job requirements against your profile (0–100%) across analytical instruments (HPLC, GC-MS, NMR), regulations (GMP, GLP, ISO), and qualifications.
4. **Application Generator (`src/career_ops/generator.py`):** Generates:
   - **DIN 5008 German Cover Letter (*Anschreiben*):** Tailored specifically to the job, highlighting matched methods and company relevance.
   - **German Resume (*Lebenslauf*):** Structured and prioritized for the specific position.
   - Exported as both Markdown and print-ready A4 HTML (`anschreiben.html`, `lebenslauf.html`) in `career-ops/data/applications/{company}_{role}/`.

### Career-Ops CLI
```bash
# View pipeline status
python career-ops/run_careerops.py status

# Scrape and score all queued positions
python career-ops/run_careerops.py evaluate

# Generate tailored cover letters & resumes
python career-ops/run_careerops.py generate

# End-to-end (evaluate + generate)
python career-ops/run_careerops.py all
```

---

## Testing

Run the test suite via pytest:
```bash
pytest -v
```

---

---

## Containerized Deployment (Docker & Docker Compose)

### Using Docker Compose
1. Ensure your config file exists:
   ```bash
   cp config/config.example.yaml config/config.yaml
   ```
2. Build and launch the container in the background:
   ```bash
   docker compose up -d --build
   ```
3. Inspect live logs:
   ```bash
   docker compose logs -f job-pulse
   ```
4. Stop container:
   ```bash
   docker compose down
   ```

### Using Plain Docker
```bash
docker build -t job-pulse:latest .
docker run -d \
  --name job-pulse \
  --restart unless-stopped \
  -v $(pwd)/config/config.yaml:/app/config/config.yaml:ro \
  -v $(pwd)/data:/app/data:rw \
  -v $(pwd)/career-ops:/app/career-ops:rw \
  job-pulse:latest
```

---

## Background Deployment (systemd)

For unattended Linux execution:
```bash
# Copy systemd unit files
sudo cp systemd/job-pulse.service /etc/systemd/system/
sudo cp systemd/job-pulse.timer /etc/systemd/system/

# Reload systemd and enable service
sudo systemctl daemon-reload
sudo systemctl enable --now job-pulse.service
```

---

## License
MIT
