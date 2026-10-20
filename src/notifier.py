"""Telegram Bot notification client for dispatching job alerts and handling interactive buttons."""

from __future__ import annotations

import html
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.db import JobRecord

logger = logging.getLogger(__name__)

DEFAULT_BOT_COMMANDS = [
    {"command": "menu", "description": "🎛 Open UI Control Dashboard"},
    {"command": "pipeline", "description": "📋 View application pipeline"},
    {"command": "evaluate", "description": "🎯 Match and score queued jobs"},
    {"command": "generate", "description": "✍️ Generate Anschreiben & CV"},
    {"command": "profile", "description": "👤 View candidate profile"},
    {"command": "config", "description": "⚙️ View scraping settings"},
    {"command": "sweep", "description": "🚀 Run live jobs scan"},
    {"command": "help", "description": "❓ Help & command cheat sheet"},
]


def escape_html(text: Optional[str]) -> str:
    """Escape special HTML characters for Telegram HTML parse mode."""
    if not text:
        return "N/A"
    return html.escape(str(text), quote=False)


def format_job_message(job: JobRecord) -> str:
    """Format a job alert message using Telegram HTML markup."""
    company = escape_html(job.company)
    title = escape_html(job.title)
    location = escape_html(job.location or "Not specified")
    source = escape_html(job.source)
    canonical_url = escape_html(job.canonical_url)

    lines = [
        f"🎯 <b>New Match Found: {company}</b>",
        f"📋 <b>Role:</b> {title}",
        f"📍 <b>Location:</b> {location}",
        f"🏷 <b>Source:</b> {source}",
        "",
        f'🔗 <a href="{canonical_url}">Open Job Posting</a>',
    ]
    return "\n".join(lines)


def build_job_inline_keyboard(job: JobRecord) -> Dict[str, Any]:
    """Build Telegram inline keyboard with [Open Listing] and [Queue Career-Ops] buttons."""
    # Telegram restricts callback_data to 64 bytes max. We use 32-char SHA prefix.
    short_id = job.id[:32] if job.id else ""
    return {
        "inline_keyboard": [
            [
                {"text": "🌐 Open Listing", "url": job.canonical_url},
                {
                    "text": "📥 Queue Career-Ops",
                    "callback_data": f"q:{short_id}",
                },
            ]
        ]
    }


def build_main_reply_keyboard() -> Dict[str, Any]:
    """Build persistent bottom reply keyboard drawer replacing manual slash typing."""
    return {
        "keyboard": [
            [{"text": "📋 Pipeline"}, {"text": "🎯 Evaluate"}],
            [{"text": "✍️ Generate"}, {"text": "👤 Profile"}],
            [{"text": "⚙️ Settings"}, {"text": "🚀 Sweep"}],
            [{"text": "🎛 Control Dashboard"}, {"text": "❓ Help"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def build_dashboard_inline_keyboard() -> Dict[str, Any]:
    """Build interactive inline menu buttons for the central control dashboard."""
    return {
        "inline_keyboard": [
            [
                {"text": "📋 Pipeline", "callback_data": "m:pipe"},
                {"text": "🎯 Evaluate All", "callback_data": "m:eval"},
            ],
            [
                {"text": "✍️ Generate Docs", "callback_data": "m:gen"},
                {"text": "👤 Profile", "callback_data": "m:prof"},
            ],
            [
                {"text": "⚙️ Settings", "callback_data": "m:conf"},
                {"text": "🚀 Run Sweep", "callback_data": "m:sweep"},
            ],
            [
                {"text": "🔄 Refresh", "callback_data": "m:main"},
                {"text": "❓ Help", "callback_data": "m:help"},
            ],
        ]
    }


def build_pipeline_inline_keyboard() -> Dict[str, Any]:
    """Build inline buttons for pipeline view."""
    return {
        "inline_keyboard": [
            [
                {"text": "🎯 Evaluate All", "callback_data": "m:eval"},
                {"text": "✍️ Generate Docs", "callback_data": "m:gen"},
            ],
            [
                {"text": "🔄 Refresh", "callback_data": "m:pipe"},
                {"text": "⬅️ Back to Menu", "callback_data": "m:main"},
            ],
        ]
    }


def build_profile_inline_keyboard() -> Dict[str, Any]:
    """Build inline buttons for candidate profile view."""
    return {
        "inline_keyboard": [
            [
                {"text": "📄 How to Upload CV", "callback_data": "m:hint_cv"},
                {"text": "✏️ Edit Profile Guide", "callback_data": "m:hint_prof"},
            ],
            [
                {"text": "🔄 Refresh", "callback_data": "m:prof"},
                {"text": "⬅️ Back to Menu", "callback_data": "m:main"},
            ],
        ]
    }


def build_config_inline_keyboard() -> Dict[str, Any]:
    """Build inline buttons for configuration view."""
    return {
        "inline_keyboard": [
            [
                {"text": "➕ Keyword Guide", "callback_data": "m:hint_kw"},
                {"text": "📍 Location Guide", "callback_data": "m:hint_loc"},
            ],
            [
                {"text": "🔄 Reset Defaults", "callback_data": "m:reset_conf"},
                {"text": "🚀 Run Sweep", "callback_data": "m:sweep"},
            ],
            [
                {"text": "🔄 Refresh", "callback_data": "m:conf"},
                {"text": "⬅️ Back to Menu", "callback_data": "m:main"},
            ],
        ]
    }


def build_back_inline_keyboard() -> Dict[str, Any]:
    """Build simple back-to-menu inline keyboard."""
    return {
        "inline_keyboard": [
            [{"text": "⬅️ Back to Menu", "callback_data": "m:main"}]
        ]
    }


class TelegramNotifier:
    """Telegram Bot API client with sync and async dispatch capabilities."""

    def __init__(self, bot_token: str, chat_id: str, timeout: float = 15.0):
        self.bot_token = bot_token.strip()
        self.chat_id = str(chat_id).strip()
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    def send_message(
        self,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = False,
    ) -> Dict[str, Any]:
        """Send a message to the configured Telegram chat with 429 rate-limit backoff."""
        url = f"{self.base_url}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        import time

        for attempt in range(4):
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload)
                if response.status_code == 429:
                    retry_after = 2
                    try:
                        retry_after = response.json().get("parameters", {}).get("retry_after", 2)
                    except Exception:
                        pass
                    logger.warning(f"Telegram rate limit hit. Sleeping for {retry_after}s...")
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                data = response.json()
                if not data.get("ok"):
                    raise RuntimeError(
                        f"Telegram API error: {data.get('description', 'Unknown error')}"
                    )
                # Gentle pacing between messages to respect Telegram limits
                time.sleep(0.4)
                return data

        raise RuntimeError("Failed to send Telegram message after rate limit retries.")

    def send_job_alert(self, job: JobRecord) -> Dict[str, Any]:
        """Dispatch a formatted job posting alert with inline action buttons."""
        text = format_job_message(job)
        reply_markup = build_job_inline_keyboard(job)
        return self.send_message(text=text, reply_markup=reply_markup)

    def answer_callback_query(
        self, callback_query_id: str, text: Optional[str] = None, show_alert: bool = False
    ) -> Dict[str, Any]:
        """Acknowledge a callback query from an inline button."""
        url = f"{self.base_url}/answerCallbackQuery"
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    def get_updates(
        self, offset: Optional[int] = None, timeout: int = 10
    ) -> Dict[str, Any]:
        """Fetch incoming bot updates (e.g. inline button clicks)."""
        url = f"{self.base_url}/getUpdates"
        params: Dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset

        with httpx.Client(timeout=timeout + 5) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    def verify_credentials(self) -> Dict[str, Any]:
        """Verify bot credentials by calling getMe."""
        url = f"{self.base_url}/getMe"
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                raise RuntimeError(
                    f"Telegram credentials invalid: {data.get('description')}"
                )
            return data.get("result", {})

    def get_file(self, file_id: str) -> Dict[str, Any]:
        """Fetch file metadata from Telegram."""
        url = f"{self.base_url}/getFile"
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url, params={"file_id": file_id})
            response.raise_for_status()
            return response.json()

    def download_file(self, file_path: str) -> bytes:
        """Download raw file content from Telegram."""
        url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.content

    def edit_message_text(
        self,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> Dict[str, Any]:
        """Edit an existing message in-place for interactive dashboards."""
        url = f"{self.base_url}/editMessageText"
        payload: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        import time

        for attempt in range(4):
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload)
                if response.status_code == 429:
                    retry_after = 2
                    try:
                        retry_after = response.json().get("parameters", {}).get("retry_after", 2)
                    except Exception:
                        pass
                    logger.warning(f"Telegram rate limit hit. Sleeping for {retry_after}s...")
                    time.sleep(retry_after)
                    continue

                # Telegram returns HTTP 400 when edited content is identical
                if response.status_code == 400 and "message is not modified" in response.text:
                    return {"ok": True, "result": "not modified"}

                response.raise_for_status()
                data = response.json()
                if not data.get("ok"):
                    raise RuntimeError(
                        f"Telegram API error: {data.get('description', 'Unknown error')}"
                    )
                time.sleep(0.3)
                return data

        raise RuntimeError("Failed to edit Telegram message after rate limit retries.")

    def set_my_commands(
        self, commands: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """Register the bot command menu with Telegram so it appears in the [/] menu."""
        url = f"{self.base_url}/setMyCommands"
        payload = {"commands": commands or DEFAULT_BOT_COMMANDS}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

