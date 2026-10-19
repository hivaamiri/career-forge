"""Unit tests for Telegram bot dynamic configuration commands."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.config import AppConfig
from src.db import Database
from src.telegram_listener import TelegramCallbackHandler


@pytest.fixture
def test_setup():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_cmd.sqlite"
        db = Database(db_path=db_path)
        config = AppConfig(
            telegram={"bot_token": "token", "chat_id": "123456"},
            arbeitsagentur={
                "keywords": ["backend", "devops"],
                "locations": ["Berlin", "Munich"],
                "radius_km": 50,
            },
            ats={"personio_companies": ["acme"]},
        )
        mock_notifier = MagicMock()
        mock_sync = MagicMock()
        mock_sweep = MagicMock(return_value={"arbeitsagentur": 5})

        handler = TelegramCallbackHandler(
            config=config,
            db=db,
            notifier=mock_notifier,
            on_config_change=mock_sync,
            on_sweep_request=mock_sweep,
        )
        yield db, handler, mock_notifier, mock_sync, mock_sweep


def test_command_config_display(test_setup):
    db, handler, mock_notifier, _, _ = test_setup
    msg = {"chat": {"id": 123456}, "text": "/config"}

    assert handler._handle_message(msg) is True
    mock_notifier.send_message.assert_called_once()
    output = mock_notifier.send_message.call_args[0][0]
    assert "Active Scraping Configuration" in output
    assert "backend" in output
    assert "Berlin" in output
    assert "50 km" in output


def test_command_add_del_keyword(test_setup):
    db, handler, mock_notifier, mock_sync, _ = test_setup

    # Add keyword
    add_msg = {"chat": {"id": 123456}, "text": "/add_keyword rust engineer, cloud"}
    assert handler._handle_message(add_msg) is True
    mock_sync.assert_called_once()

    keywords = db.get_setting("keywords")
    assert "rust engineer" in keywords
    assert "cloud" in keywords
    assert len(keywords) == 4

    # Delete keyword
    del_msg = {"chat": {"id": 123456}, "text": "/del_keyword rust engineer"}
    assert handler._handle_message(del_msg) is True
    keywords_after = db.get_setting("keywords")
    assert "rust engineer" not in keywords_after
    assert len(keywords_after) == 3


def test_command_set_keywords(test_setup):
    db, handler, mock_notifier, mock_sync, _ = test_setup
    set_msg = {"chat": {"id": 123456}, "text": "/set_keywords golang, python, kubernetes"}

    assert handler._handle_message(set_msg) is True
    keywords = db.get_setting("keywords")
    assert keywords == ["golang", "python", "kubernetes"]


def test_command_locations_and_radius(test_setup):
    db, handler, mock_notifier, mock_sync, _ = test_setup

    # Add location
    assert handler._handle_message({"chat": {"id": 123456}, "text": "/add_location Hamburg, Köln"}) is True
    locs = db.get_setting("locations")
    assert "Hamburg" in locs
    assert "Köln" in locs

    # Set radius
    assert handler._handle_message({"chat": {"id": 123456}, "text": "/set_radius 100"}) is True
    assert db.get_setting("radius_km") == 100

    # Invalid radius
    assert handler._handle_message({"chat": {"id": 123456}, "text": "/set_radius -10"}) is True
    assert db.get_setting("radius_km") == 100  # unchanged


def test_command_company_management(test_setup):
    db, handler, mock_notifier, mock_sync, _ = test_setup

    assert handler._handle_message({"chat": {"id": 123456}, "text": "/add_company celonis"}) is True
    comps = db.get_setting("personio_companies")
    assert "celonis" in comps

    assert handler._handle_message({"chat": {"id": 123456}, "text": "/del_company acme"}) is True
    comps_after = db.get_setting("personio_companies")
    assert "acme" not in comps_after


def test_command_sweep_trigger(test_setup):
    db, handler, mock_notifier, _, mock_sweep = test_setup

    assert handler._handle_message({"chat": {"id": 123456}, "text": "/sweep"}) is True
    mock_sweep.assert_called_once()
    # Check confirmation was sent
    assert any("Sweep Complete" in call[0][0] for call in mock_notifier.send_message.call_args_list)


def test_command_reset_config(test_setup):
    db, handler, mock_notifier, mock_sync, _ = test_setup
    db.set_setting("keywords", ["custom"])
    assert db.get_setting("keywords") == ["custom"]

    assert handler._handle_message({"chat": {"id": 123456}, "text": "/reset_config"}) is True
    assert db.get_setting("keywords") is None  # Deleted from overrides


def test_unauthorized_chat_rejected(test_setup):
    db, handler, mock_notifier, _, _ = test_setup
    unauth_msg = {"chat": {"id": 999999}, "text": "/set_keywords evil"}

    assert handler._handle_message(unauth_msg) is False
    assert db.get_setting("keywords") is None
