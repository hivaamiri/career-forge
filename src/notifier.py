"""Telegram Bot notification client for dispatching job alerts and handling interactive buttons."""

from __future__ import annotations

import html
import logging
from typing import Any, Dict, Optional

import httpx

from src.db import JobRecord

logger = logging.getLogger(__name__)


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
    return {
        "inline_keyboard": [
            [
                {"text": "🌐 Open Listing", "url": job.canonical_url},
                {
                    "text": "📥 Queue Career-Ops",
                    "callback_data": f"queue:{job.id}",
                },
            ]
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
        """Send a message to the configured Telegram chat."""
        url = f"{self.base_url}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                raise RuntimeError(
                    f"Telegram API error: {data.get('description', 'Unknown error')}"
                )
            return data

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
