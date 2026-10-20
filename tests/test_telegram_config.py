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


def test_keyboard_builders():
    from src.notifier import (
        build_back_inline_keyboard,
        build_config_inline_keyboard,
        build_dashboard_inline_keyboard,
        build_main_reply_keyboard,
        build_pipeline_inline_keyboard,
        build_profile_inline_keyboard,
    )

    # Reply keyboard
    reply_kb = build_main_reply_keyboard()
    assert reply_kb["resize_keyboard"] is True
    assert reply_kb["is_persistent"] is True
    assert len(reply_kb["keyboard"]) == 4

    # Dashboard inline keyboard
    dash_kb = build_dashboard_inline_keyboard()
    assert any("m:pipe" in btn["callback_data"] for row in dash_kb["inline_keyboard"] for btn in row)
    assert any("m:conf" in btn["callback_data"] for row in dash_kb["inline_keyboard"] for btn in row)

    # Other inline keyboards
    assert len(build_pipeline_inline_keyboard()["inline_keyboard"]) >= 2
    assert len(build_profile_inline_keyboard()["inline_keyboard"]) >= 2
    assert len(build_config_inline_keyboard()["inline_keyboard"]) >= 3
    assert len(build_back_inline_keyboard()["inline_keyboard"]) == 1


def test_reply_keyboard_buttons_dispatch(test_setup):
    db, handler, mock_notifier, _, mock_sweep = test_setup

    # 1. Pipeline button
    assert handler._handle_message({"chat": {"id": 123456}, "text": "📋 Pipeline"}) is True
    assert any("Pipeline" in call[0][0] for call in mock_notifier.send_message.call_args_list)

    # 2. Settings button
    assert handler._handle_message({"chat": {"id": 123456}, "text": "⚙️ Settings"}) is True
    assert any("Active Scraping Configuration" in call[0][0] for call in mock_notifier.send_message.call_args_list)

    # 3. Sweep button
    assert handler._handle_message({"chat": {"id": 123456}, "text": "🚀 Sweep"}) is True
    mock_sweep.assert_called()

    # 4. Help button
    assert handler._handle_message({"chat": {"id": 123456}, "text": "❓ Help"}) is True
    assert any("Command Center" in call[0][0] for call in mock_notifier.send_message.call_args_list)


def test_menu_dashboard_command(test_setup):
    db, handler, mock_notifier, _, _ = test_setup

    # /menu command
    assert handler._handle_message({"chat": {"id": 123456}, "text": "/menu"}) is True
    last_call = mock_notifier.send_message.call_args_list[-1]
    menu_text = last_call[0][0] if last_call[0] else last_call[1].get("text", "")
    assert "Control Dashboard" in menu_text
    reply_markup = last_call[1].get("reply_markup")
    assert "inline_keyboard" in reply_markup

    # /start command
    assert handler._handle_message({"chat": {"id": 123456}, "text": "/start"}) is True
    all_texts = [c[0][0] if c[0] else c[1].get("text", "") for c in mock_notifier.send_message.call_args_list]
    assert any("Welcome to Job Pulse" in t for t in all_texts)



def test_menu_callbacks_in_place_editing(test_setup):
    db, handler, mock_notifier, _, mock_sweep = test_setup

    # 1. m:conf (scraping settings view)
    cb_conf = {
        "id": "cb_1",
        "data": "m:conf",
        "message": {"message_id": 42},
    }
    handler._handle_callback(cb_conf)
    mock_notifier.answer_callback_query.assert_called_with(callback_query_id="cb_1", text="Updating...")
    mock_notifier.edit_message_text.assert_called()
    assert "Active Scraping Configuration" in mock_notifier.edit_message_text.call_args[1]["text"]

    # 2. m:pipe (pipeline view)
    cb_pipe = {
        "id": "cb_2",
        "data": "m:pipe",
        "message": {"message_id": 42},
    }
    handler._handle_callback(cb_pipe)
    assert "Pipeline" in mock_notifier.edit_message_text.call_args[1]["text"]

    # 3. m:prof (profile view)
    cb_prof = {
        "id": "cb_3",
        "data": "m:prof",
        "message": {"message_id": 42},
    }
    handler._handle_callback(cb_prof)
    assert mock_notifier.edit_message_text.called

    # 4. m:sweep (live sweep view)
    cb_sweep = {
        "id": "cb_4",
        "data": "m:sweep",
        "message": {"message_id": 42},
    }
    handler._handle_callback(cb_sweep)
    mock_sweep.assert_called()
    assert "Sweep Complete" in mock_notifier.edit_message_text.call_args[1]["text"]

    # 5. m:main (return to main dashboard)
    cb_main = {
        "id": "cb_5",
        "data": "m:main",
        "message": {"message_id": 42},
    }
    handler._handle_callback(cb_main)
    assert "Control Dashboard" in mock_notifier.edit_message_text.call_args[1]["text"]

    # 6. m:hint_cv and m:hint_prof
    handler._handle_callback({"id": "cb_6", "data": "m:hint_cv", "message": {"message_id": 42}})
    assert "How to Ingest Your CV" in mock_notifier.edit_message_text.call_args[1]["text"]

    handler._handle_callback({"id": "cb_7", "data": "m:hint_prof", "message": {"message_id": 42}})
    assert "/set_name" in mock_notifier.edit_message_text.call_args[1]["text"]

    # 7. m:reset_conf
    db.set_setting("keywords", ["temporary"])
    handler._handle_callback({"id": "cb_8", "data": "m:reset_conf", "message": {"message_id": 42}})
    assert db.get_setting("keywords") is None
    assert "Configuration Reset" in mock_notifier.edit_message_text.call_args[1]["text"]


def test_telegram_notifier_edit_and_commands():
    from unittest.mock import patch
    from src.notifier import TelegramNotifier

    notifier = TelegramNotifier(bot_token="test_token", chat_id="123")

    # Test edit_message_text
    with patch("httpx.Client.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 42}}

        res = notifier.edit_message_text(message_id=42, text="Hello World")
        assert res["ok"] is True
        mock_post.assert_called_once()
        assert "editMessageText" in mock_post.call_args[0][0]

    # Test edit_message_text with unmodified message (400 Bad Request)
    with patch("httpx.Client.post") as mock_post:
        mock_post.return_value.status_code = 400
        mock_post.return_value.text = "Bad Request: message is not modified"
        res = notifier.edit_message_text(message_id=42, text="Unchanged")
        assert res.get("result") == "not modified"

    # Test set_my_commands
    with patch("httpx.Client.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"ok": True, "result": True}
        res = notifier.set_my_commands()
        assert res["ok"] is True
        assert "setMyCommands" in mock_post.call_args[0][0]


