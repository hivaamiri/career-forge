"""Unit tests for Job Pulse Core Foundation & Telegram Dispatch."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import AppConfig, TelegramConfig, load_config
from src.db import Database, JobRecord, compute_job_id
from src.notifier import (
    TelegramNotifier,
    build_job_inline_keyboard,
    escape_html,
    format_job_message,
)


def test_config_loading_from_file():
    """Verify loading and validating config from a YAML file."""
    yaml_content = """
telegram:
  bot_token: "test-token"
  chat_id: "12345678"
email:
  enabled: true
  username: "test@example.com"
  password: "app-password"
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f_path = f.name

    try:
        config = load_config(f_path)
        assert isinstance(config, AppConfig)
        assert config.telegram.bot_token == "test-token"
        assert config.telegram.chat_id == "12345678"
        assert config.email.enabled is True
        assert config.email.username == "test@example.com"
        assert config.email.imap_port == 993
        assert len(config.matcher.inclusion_patterns) > 0
    finally:
        os.remove(f_path)


def test_config_environment_overrides(monkeypatch):
    """Verify that environment variables take precedence for secrets."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token-xyz")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99887766")
    monkeypatch.setenv("IMAP_USERNAME", "env-user@gmail.com")
    monkeypatch.setenv("IMAP_PASSWORD", "env-pass")

    config = load_config("config/config.example.yaml")
    assert config.telegram.bot_token == "env-token-xyz"
    assert config.telegram.chat_id == "99887766"
    assert config.email.username == "env-user@gmail.com"
    assert config.email.password == "env-pass"


def test_database_operations():
    """Verify database initialization, WAL mode, deduplication, and status updating."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_jobs.sqlite"
        db = Database(db_path=db_path)

        # Check WAL mode
        with db.get_connection() as conn:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            assert mode.lower() == "wal"

        canonical_url = "https://jobs.example.com/posting-101?source=test"
        job_id = compute_job_id(canonical_url)

        assert not db.is_seen(job_id)
        assert not db.is_seen(canonical_url)

        # Save first time -> should insert
        returned_id, inserted = db.save_job(
            source="stepstone",
            title="Senior Python Engineer",
            company="TechCorp AG",
            url="https://tracking.link/abc",
            canonical_url=canonical_url,
            location="Berlin",
            meta={"salary": "85k"},
        )
        assert returned_id == job_id
        assert inserted is True
        assert db.is_seen(job_id) is True
        assert db.is_seen(canonical_url) is True

        # Duplicate save -> should ignore and return inserted=False
        second_id, inserted_second = db.save_job(
            source="stepstone",
            title="Senior Python Engineer",
            company="TechCorp AG",
            url="https://tracking.link/abc",
            canonical_url=canonical_url,
            location="Berlin",
        )
        assert second_id == job_id
        assert inserted_second is False

        # Get job
        record = db.get_job(job_id)
        assert record is not None
        assert record.title == "Senior Python Engineer"
        assert record.company == "TechCorp AG"
        assert record.meta == {"salary": "85k"}
        assert record.status == "notified"

        # Update status
        updated = db.update_status(job_id, "queued_career_ops")
        assert updated is True
        refetched = db.get_job(job_id)
        assert refetched.status == "queued_career_ops"

        # List jobs
        queued_jobs = db.list_jobs(status="queued_career_ops")
        assert len(queued_jobs) == 1
        assert queued_jobs[0].id == job_id


def test_telegram_message_formatting():
    """Verify HTML escaping and message templates."""
    job = JobRecord(
        id="hash123",
        source="linkedin",
        title="Backend & Cloud <Architect>",
        company="A & B Software GmbH",
        location="Frankfurt & Remote",
        url="https://linkedin.com/orig",
        canonical_url="https://linkedin.com/jobs/view/123",
    )

    formatted = format_job_message(job)
    # Special characters must be escaped
    assert "A &amp; B Software GmbH" in formatted
    assert "Backend &amp; Cloud &lt;Architect&gt;" in formatted
    assert "Frankfurt &amp; Remote" in formatted
    assert '<a href="https://linkedin.com/jobs/view/123">Open Job Posting</a>' in formatted

    keyboard = build_job_inline_keyboard(job)
    buttons = keyboard["inline_keyboard"][0]
    assert len(buttons) == 2
    assert buttons[0]["text"] == "🌐 Open Listing"
    assert buttons[0]["url"] == "https://linkedin.com/jobs/view/123"
    assert buttons[1]["text"] == "📥 Queue Career-Ops"
    assert buttons[1]["callback_data"] == "q:hash123"


@patch("httpx.Client.post")
def test_telegram_dispatch(mock_post):
    """Verify TelegramNotifier.send_job_alert makes expected HTTP post request."""
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"ok": True, "result": {"message_id": 999}},
    )

    notifier = TelegramNotifier(bot_token="test-token", chat_id="12345678")
    job = JobRecord(
        id="hash456",
        source="arbeitsagentur",
        title="Linux Systems Engineer",
        company="CloudNet GmbH",
        location="Munich",
        url="https://example.com/job",
        canonical_url="https://example.com/job",
    )

    response = notifier.send_job_alert(job)
    assert response["ok"] is True
    assert response["result"]["message_id"] == 999

    assert mock_post.called
    call_args = mock_post.call_args
    assert call_args[0][0] == "https://api.telegram.org/bottest-token/sendMessage"
    payload = call_args[1]["json"]
    assert payload["chat_id"] == "12345678"
    assert "CloudNet GmbH" in payload["text"]
    assert payload["reply_markup"]["inline_keyboard"][0][1]["callback_data"] == "q:hash456"
