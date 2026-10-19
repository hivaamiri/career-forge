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

## Testing

Run the test suite via pytest:
```bash
pytest -v
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
