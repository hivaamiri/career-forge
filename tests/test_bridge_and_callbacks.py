"""Unit tests for Career-Ops bridge and Telegram callback handler."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.bridge_careerops import append_job_to_pipeline_md, queue_job_to_careerops
from src.config import AppConfig
from src.db import Database, JobRecord, compute_job_id
from src.telegram_listener import TelegramCallbackHandler


def test_append_job_to_pipeline_md():
    with tempfile.TemporaryDirectory() as tmp_dir:
        pipeline_path = Path(tmp_dir) / "pipeline.md"

        job = JobRecord(
            id=compute_job_id("https://company.de/job/1"),
            source="linkedin",
            title="Senior Distributed Systems Engineer",
            company="FinTech Core AG",
            location="Berlin, Germany",
            url="https://company.de/job/1",
            canonical_url="https://company.de/job/1",
        )

        success, msg = append_job_to_pipeline_md(job, pipeline_path=pipeline_path)
        assert success is True
        assert pipeline_path.exists()

        content = pipeline_path.read_text(encoding="utf-8")
        assert "| FinTech Core AG |" in content
        assert "Senior Distributed Systems Engineer" in content
        assert "| Queued |" in content

        # Duplicate append attempt should be rejected
        success_dup, msg_dup = append_job_to_pipeline_md(job, pipeline_path=pipeline_path)
        assert success_dup is False
        assert "already exists" in msg_dup


def test_queue_job_to_careerops_db_integration():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_bridge.sqlite"
        pipeline_path = Path(tmp_dir) / "pipeline.md"
        db = Database(db_path=db_path)

        canonical_url = "https://example.com/job/devops"
        job_id, _ = db.save_job(
            source="stepstone",
            title="DevOps Engineer",
            company="Scale GmbH",
            url=canonical_url,
            canonical_url=canonical_url,
            location="Munich",
            status="notified",
        )

        assert db.get_job(job_id).status == "notified"

        # Queue to Career-Ops
        success, msg = queue_job_to_careerops(
            job_id=job_id,
            db=db,
            pipeline_path=pipeline_path,
        )
        assert success is True
        assert db.get_job(job_id).status == "queued_career_ops"

        # Non-existent job
        non_existent_success, _ = queue_job_to_careerops(
            job_id="unknown_hash",
            db=db,
            pipeline_path=pipeline_path,
        )
        assert non_existent_success is False


def test_telegram_callback_handler_dispatch():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_cb.sqlite"
        pipeline_path = Path(tmp_dir) / "pipeline.md"
        db = Database(db_path=db_path)

        url = "https://example.com/job/backend"
        job_id, _ = db.save_job(
            source="xing",
            title="Backend Architect",
            company="NetTech",
            url=url,
            canonical_url=url,
            location="Remote",
        )

        config = AppConfig(
            telegram={"bot_token": "token", "chat_id": "123"},
            career_ops={"pipeline_path": str(pipeline_path)},
        )

        mock_notifier = MagicMock()
        mock_notifier.get_updates.return_value = {
            "ok": True,
            "result": [
                {
                    "update_id": 501,
                    "callback_query": {
                        "id": "cb_query_999",
                        "data": f"queue:{job_id}",
                    },
                }
            ],
        }

        handler = TelegramCallbackHandler(config=config, db=db, notifier=mock_notifier)
        processed = handler.process_updates()

        assert processed == 1
        assert db.get_job(job_id).status == "queued_career_ops"
        mock_notifier.answer_callback_query.assert_called_once()
        args = mock_notifier.answer_callback_query.call_args[1]
        assert args["callback_query_id"] == "cb_query_999"
        assert "Queued into Career-Ops" in args["text"]
