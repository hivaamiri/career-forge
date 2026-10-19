"""Unit tests for Arbeitsagentur REST poller, Personio ATS poller, and Orchestrator."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from main import Orchestrator
from src.config import AppConfig
from src.db import Database
from src.ingest.arbeitsagentur import ArbeitsagenturPoller
from src.ingest.ats_poller import ATSPoller, parse_personio_xml


def test_arbeitsagentur_parsing_and_polling():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_aa.sqlite"
        db = Database(db_path=db_path)

        config = AppConfig(
            telegram={"bot_token": "mock-token", "chat_id": "12345"},
            arbeitsagentur={
                "enabled": True,
                "keywords": ["backend engineer"],
                "locations": ["Berlin"],
            },
        )

        mock_notifier = MagicMock()
        mock_notifier.send_job_alert.return_value = {"ok": True}

        poller = ArbeitsagenturPoller(config=config, db=db, notifier=mock_notifier)

        mock_raw_item = {
            "refnr": "10000-9988776655-S",
            "titel": "Senior Backend Cloud Engineer",
            "beruf": "Softwareentwickler/in",
            "arbeitgeber": "Deutsche Cloud Systems AG",
            "arbeitsort": {"ort": "Berlin", "region": "Berlin"},
            "aktuelleVeroeffentlichungsdatum": "2026-10-19",
        }

        parsed = poller.parse_job_item(mock_raw_item)
        assert parsed is not None
        assert parsed["title"] == "Senior Backend Cloud Engineer"
        assert parsed["company"] == "Deutsche Cloud Systems AG"
        assert parsed["location"] == "Berlin"
        assert parsed["canonical_url"] == "https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-9988776655-S"

        # Mock fetch_jobs
        with patch.object(poller, "fetch_jobs", return_value=[mock_raw_item]):
            discovered = poller.poll()

        assert len(discovered) == 1
        record = discovered[0]
        assert record.title == "Senior Backend Cloud Engineer"
        assert record.source == "arbeitsagentur"

        # Check deduplication on second poll
        with patch.object(poller, "fetch_jobs", return_value=[mock_raw_item]):
            second_run = poller.poll()
        assert len(second_run) == 0


def test_personio_xml_parsing():
    sample_xml = """<?xml version="1.0" encoding="utf-8"?>
    <work-units>
        <position>
            <id>123456</id>
            <name>Staff DevOps &amp; Platform Engineer</name>
            <office>Munich, Germany</office>
            <department>Engineering / Infrastructure</department>
            <employmentType>permanent</employmentType>
            <jobDescriptions>
                <jobDescription>
                    <name>About the role</name>
                    <value>Scale our Kubernetes and AWS infrastructure.</value>
                </jobDescription>
            </jobDescriptions>
        </position>
    </work-units>
    """
    jobs = parse_personio_xml("acmetech", sample_xml)
    assert len(jobs) == 1
    job = jobs[0]
    assert job["id"] == "123456"
    assert job["title"] == "Staff DevOps & Platform Engineer"
    assert job["company"] == "Acmetech"
    assert "Munich" in job["location"]
    assert job["canonical_url"] == "https://acmetech.jobs.personio.de/job/123456"
    assert "Kubernetes" in job["snippet"]


def test_ats_poller_flow():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_ats.sqlite"
        db = Database(db_path=db_path)

        config = AppConfig(
            telegram={"bot_token": "mock-token", "chat_id": "12345"},
            ats={
                "enabled": True,
                "personio_companies": ["acmetech"],
            },
        )

        mock_notifier = MagicMock()
        mock_notifier.send_job_alert.return_value = {"ok": True}

        poller = ATSPoller(config=config, db=db, notifier=mock_notifier)

        mock_items = [
            {
                "id": "111",
                "title": "Senior Systems Engineer (Linux)",
                "company": "Acmetech",
                "location": "Berlin",
                "url": "https://acmetech.jobs.personio.de/job/111",
                "canonical_url": "https://acmetech.jobs.personio.de/job/111",
                "snippet": "Linux, distributed systems",
            }
        ]

        with patch.object(poller, "fetch_personio_feed", return_value=mock_items):
            discovered = poller.poll()

        assert len(discovered) == 1
        assert discovered[0].title == "Senior Systems Engineer (Linux)"
        assert db.is_seen(discovered[0].canonical_url) is True
        mock_notifier.send_job_alert.assert_called_once()


def test_orchestrator_run_once():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_orch.sqlite"
        config = AppConfig(
            telegram={"bot_token": "mock-token", "chat_id": "12345"},
            database={"path": str(db_path)},
            email={"enabled": False},
            arbeitsagentur={"enabled": True},
            ats={"enabled": True},
        )

        orchestrator = Orchestrator(config)
        with patch.object(orchestrator.aa_poller, "poll", return_value=[MagicMock()]), \
             patch.object(orchestrator.ats_poller, "poll", return_value=[MagicMock()]):
            counts = orchestrator.run_once()

        assert counts["email"] == 0
        assert counts["arbeitsagentur"] == 1
        assert counts["ats"] == 1
