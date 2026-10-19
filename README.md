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

## Telegram Bot Command Center

You can configure scraping keywords, locations, search radius, and target companies dynamically straight from your Telegram chat:

| Command | Description | Example |
| :--- | :--- | :--- |
| `/config` | View active keywords, locations, radius, and ATS targets | `/config` |
| `/add_keyword <text>` | Add one or more search keywords | `/add_keyword rust, distributed systems` |
| `/del_keyword <text>` | Remove a keyword | `/del_keyword devops` |
| `/set_keywords <list>` | Overwrite all search keywords | `/set_keywords backend, python, cloud` |
| `/add_location <city>` | Add target city or region | `/add_location Stuttgart, Köln` |
| `/del_location <city>` | Remove a location | `/del_location Hamburg` |
| `/set_locations <list>` | Overwrite all locations | `/set_locations Berlin, München, Remote` |
| `/set_radius <km>` | Set Bundesagentur search radius | `/set_radius 75` |
| `/add_company <slug>` | Add target Personio company feed | `/add_company celonis` |
| `/del_company <slug>` | Remove Personio company | `/del_company acme` |
| `/sweep` | Trigger an immediate live scan across all scrapers | `/sweep` |
| `/reset_config` | Revert all overrides back to `config.yaml` defaults | `/reset_config` |
| `/help` | Display command cheat-sheet | `/help` |

All changes made via Telegram are persisted to SQLite (`settings` table) and take effect immediately without restarting the service.

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
