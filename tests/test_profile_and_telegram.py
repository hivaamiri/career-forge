"""Unit tests for Candidate Profile Management and Telegram Bot Ingestion."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.career_ops.profile_manager import ProfileManager
from src.config import AppConfig
from src.db import Database
from src.telegram_listener import TelegramCallbackHandler


def test_profile_manager_crud():
    with tempfile.TemporaryDirectory() as tmp_dir:
        prof_path = Path(tmp_dir) / "profile.yaml"
        pm = ProfileManager(profile_path=prof_path)

        # 1. Update field
        pm.update_field("personal", "name", "Dr. Hiva Amiri")
        pm.update_field("personal", "title", "Senior Chemiker")
        pm.update_field("preferences", "salary_expectation", "75.000 €")

        loaded = pm.load_profile()
        assert loaded["personal"]["name"] == "Dr. Hiva Amiri"
        assert loaded["personal"]["title"] == "Senior Chemiker"
        assert loaded["preferences"]["salary_expectation"] == "75.000 €"

        # 2. Add skills
        added = pm.add_skills(["HPLC", "GC-MS", "Titration"])
        assert "HPLC" in added
        assert len(added) == 3

        # Add duplicate skill -> should not duplicate
        added_again = pm.add_skills(["HPLC", "NMR"])
        assert "HPLC" not in added_again
        assert "NMR" in added_again

        # 3. Set skills
        pm.set_skills(["HPLC", "UV-Vis"])
        loaded_after = pm.load_profile()
        assert loaded_after["skills"]["analytical_methods"] == ["HPLC", "UV-Vis"]


def test_profile_manager_cv_text_ingestion():
    with tempfile.TemporaryDirectory() as tmp_dir:
        prof_path = Path(tmp_dir) / "profile.yaml"
        pm = ProfileManager(profile_path=prof_path)

        sample_cv_text = """
        Hiva Amiri
        Musterstraße 10, 10115 Berlin
        Tel: +49 170 9876543
        E-Mail: hiva.chemie@example.com

        Profil:
        Erfahrener Chemiker für instrumentelle Analytik und Qualitätskontrolle nach GMP und GLP.
        Methoden: HPLC, GC-MS, Titration, UV-Vis und Karl-Fischer.
        """

        changes = pm.ingest_cv_text(sample_cv_text)
        assert changes["name"] == "Hiva Amiri"
        assert changes["email"] == "hiva.chemie@example.com"
        assert "+49 170" in changes["phone"]
        assert "Berlin" in changes["location"]
        assert "HPLC" in changes["analytical_methods"]
        assert "GMP" in changes["quality_and_regulations"]


def test_telegram_profile_commands():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.sqlite"
        prof_path = Path(tmp_dir) / "profile.yaml"
        db = Database(db_path=db_path)

        config = AppConfig(
            telegram={"bot_token": "token", "chat_id": "123456"},
        )
        mock_notifier = MagicMock()

        handler = TelegramCallbackHandler(
            config=config,
            db=db,
            notifier=mock_notifier,
        )

        with patch("src.career_ops.profile_manager.DEFAULT_PROFILE_PATH", prof_path):
            # Test /set_name
            msg_name = {"chat": {"id": 123456}, "text": "/set_name Hiva Amiri"}
            assert handler._handle_message(msg_name) is True
            mock_notifier.send_message.assert_called_with("✅ Name updated to: <b>Hiva Amiri</b>")

            # Test /set_salary
            msg_sal = {"chat": {"id": 123456}, "text": "/set_salary 70.000 €"}
            assert handler._handle_message(msg_sal) is True

            # Test /add_skill
            msg_sk = {"chat": {"id": 123456}, "text": "/add_skill HPLC, GC-MS, ICP-MS"}
            assert handler._handle_message(msg_sk) is True

            # Test /profile
            msg_prof = {"chat": {"id": 123456}, "text": "/profile"}
            assert handler._handle_message(msg_prof) is True


def test_telegram_document_upload():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.sqlite"
        db = Database(db_path=db_path)

        config = AppConfig(
            telegram={"bot_token": "token", "chat_id": "123456"},
        )
        mock_notifier = MagicMock()
        mock_notifier.get_file.return_value = {"result": {"file_path": "docs/cv.txt"}}
        mock_notifier.download_file.return_value = (
            b"Hiva Amiri\nE-Mail: hiva@test.de\nTel: +49 170 112233\n10115 Berlin\nHPLC, GC-MS, GMP"
        )

        handler = TelegramCallbackHandler(
            config=config,
            db=db,
            notifier=mock_notifier,
        )

        sample_message = {
            "chat": {"id": 123456},
            "document": {
                "file_id": "doc123",
                "file_name": "lebenslauf.txt",
                "file_size": 2048,
            },
        }

        with patch("pathlib.Path.mkdir"):
            handler._handle_document(sample_message, sample_message["document"])

        mock_notifier.send_message.assert_called()
        # Verify success message sent
        last_msg = mock_notifier.send_message.call_args[0][0]
        assert "CV Successfully Ingested" in last_msg
        assert "Hiva Amiri" in last_msg
