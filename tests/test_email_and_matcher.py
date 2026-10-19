"""Unit tests for Email Ingestion, Parsers, URL Resolver, and Matcher."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import AppConfig, MatcherConfig
from src.db import Database
from src.ingest.email_stream import EmailStreamConsumer, extract_html_body
from src.ingest.parsers import (
    parse_email_message,
    parse_linkedin_email,
    parse_stepstone_email,
    parse_xing_email,
)
from src.ingest.url_resolver import resolve_canonical_url, strip_tracking_params
from src.matcher import JobMatcher


def test_matcher_logic():
    matcher = JobMatcher()

    # Inclusion match
    res1 = matcher.evaluate("Senior Backend Engineer", location="Berlin")
    assert res1.matched is True
    assert "backend" in [i.lower() for i in res1.matched_inclusions]

    # Systems engineer match
    res2 = matcher.evaluate("Staff Cloud Systems Engineer", location="Remote")
    assert res2.matched is True

    # Exclusion match (intern / werkstudent)
    res_ex1 = matcher.evaluate("Backend Engineer Intern", location="Berlin")
    assert res_ex1.matched is False
    assert any("intern" in ex.lower() for ex in res_ex1.matched_exclusions)

    res_ex2 = matcher.evaluate("DevOps Werkstudent / Working Student", location="Munich")
    assert res_ex2.matched is False

    # Irrelevant role (neither inclusion nor exclusion)
    res_irr = matcher.evaluate("Senior HR Talent Acquisition Manager", location="Berlin")
    assert res_irr.matched is False

    # Location mismatch (when location is explicitly provided and outside scope)
    res_loc = matcher.evaluate("Backend Engineer", location="Tokyo, Japan")
    assert res_loc.matched is False
    assert "Location 'Tokyo, Japan' did not match" in res_loc.reason


def test_url_resolver_stripping():
    dirty_url = (
        "https://example.com/jobs/123"
        "?utm_source=linkedin&utm_medium=email&utm_campaign=daily_alert&refId=abc789&validParam=keep"
    )
    cleaned = strip_tracking_params(dirty_url)
    assert "utm_source" not in cleaned
    assert "utm_medium" not in cleaned
    assert "refId" not in cleaned
    assert "validParam=keep" in cleaned
    assert cleaned.startswith("https://example.com/jobs/123")


@patch("httpx.Client.head")
def test_resolve_canonical_url_redirect(mock_head):
    mock_response = MagicMock()
    mock_response.url = "https://target-company.de/careers/backend-dev?utm_source=stepstone"
    mock_head.return_value = mock_response

    resolved = resolve_canonical_url("https://click.stepstone.de/redirect-token-123")
    assert resolved == "https://target-company.de/careers/backend-dev"


@patch("httpx.Client.head", side_effect=Exception("Connection timed out"))
@patch("httpx.Client.get", side_effect=Exception("Connection timed out"))
def test_resolve_canonical_url_fallback(mock_get, mock_head):
    # Graceful fallback on network failure
    raw = "https://target.de/job?utm_source=test&id=55"
    resolved = resolve_canonical_url(raw)
    assert resolved == "https://target.de/job?id=55"


def test_parse_stepstone_email():
    html_sample = """
    <html>
      <body>
        <div class="job-item">
          <a href="https://www.stepstone.de/stellenangebote--Senior-Platform-Engineer-Berlin--12345.html?utm_source=alert">
            Senior Platform Engineer
          </a>
          <div>FinTech Core GmbH</div>
          <div>Berlin, Germany</div>
          <div>Kubernetes, Go, AWS infrastructure</div>
        </div>
        <a href="https://www.stepstone.de/hilfe">Hilfe & Kontakt</a>
      </body>
    </html>
    """
    jobs = parse_stepstone_email(html_sample)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "stepstone"
    assert job.title == "Senior Platform Engineer"
    assert job.company == "FinTech Core GmbH"
    assert job.location == "Berlin, Germany"
    assert "stellenangebote" in job.raw_url


def test_parse_linkedin_email():
    html_sample = """
    <html>
      <body>
        <table>
          <tr>
            <td>
              <a href="https://www.linkedin.com/comm/jobs/view/4567890123/?trackingId=xyz">
                Senior DevOps & Cloud Engineer
              </a>
              <div>ScaleTech Systems</div>
              <div>Munich, Bavaria, Germany</div>
            </td>
          </tr>
        </table>
        <a href="https://www.linkedin.com/help">Manage alert settings</a>
      </body>
    </html>
    """
    jobs = parse_linkedin_email(html_sample)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "linkedin"
    assert job.title == "Senior DevOps & Cloud Engineer"
    assert job.company == "ScaleTech Systems"
    assert "Munich" in (job.location or "")


def test_parse_xing_email():
    html_sample = """
    <html>
      <body>
        <div class="recommendation">
          <a href="https://www.xing.com/jobs/de/berlin-lead-backend-developer-99999?trk=feed">
            Lead Backend Developer
          </a>
          <div>Digital Innovation Labs</div>
          <div>Remote / Berlin</div>
        </div>
      </body>
    </html>
    """
    jobs = parse_xing_email(html_sample)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "xing"
    assert job.title == "Lead Backend Developer"
    assert job.company == "Digital Innovation Labs"


@patch("src.ingest.email_stream.resolve_canonical_url", side_effect=lambda url: url.split("?")[0])
def test_email_stream_pipeline_end_to_end(mock_url_resolver):
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_pipeline.sqlite"
        db = Database(db_path=db_path)

        config = AppConfig(
            telegram={"bot_token": "mock-token", "chat_id": "12345"},
            email={
                "enabled": True,
                "username": "user@gmail.com",
                "password": "secret-pass",
            },
        )

        mock_notifier = MagicMock()
        mock_notifier.send_job_alert.return_value = {"ok": True}

        consumer = EmailStreamConsumer(
            config=config,
            db=db,
            notifier=mock_notifier,
        )

        # Mock IMAP client
        mock_client = MagicMock()
        mock_client.select.return_value = ("OK", [b"1"])
        mock_client.search.return_value = ("OK", [b"101"])

        sample_mime_email = (
            b"From: StepStone Job-Agent <jobagent@stepstone.de>\r\n"
            b"Subject: 1 neue Stellenangebote fur Backend Engineer\r\n"
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n\r\n"
            b'<html><body><a href="https://stepstone.de/stellenangebote--Backend-Engineer--123?utm=x">Backend Engineer</a>'
            b'<div>CloudScale AG</div><div>Berlin</div></body></html>'
        )

        mock_client.fetch.return_value = (
            "OK",
            [(b"1 (RFC822 {100}", sample_mime_email), b")"],
        )

        with patch.object(consumer, "connect", return_value=mock_client):
            discovered = consumer.process_inbox()

        assert len(discovered) == 1
        job = discovered[0]
        assert job.title == "Backend Engineer"
        assert job.company == "CloudScale AG"
        assert job.source == "stepstone"

        # Check DB was written
        assert db.is_seen(job.canonical_url) is True

        # Check Telegram alert was called
        mock_notifier.send_job_alert.assert_called_once()

        # Check email was marked read
        mock_client.store.assert_called_with(b"101", "+FLAGS", "\\Seen")
