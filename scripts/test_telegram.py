#!/usr/bin/env python3
"""Sanity check script to verify Telegram bot credentials and test alert dispatch."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.db import JobRecord, compute_job_id
from src.notifier import TelegramNotifier


def main():
    print("🚀 Initializing Telegram sanity check...")
    try:
        config = load_config()
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        sys.exit(1)

    bot_token = config.telegram.bot_token
    chat_id = config.telegram.chat_id

    if not bot_token or bot_token == "YOUR_TELEGRAM_BOT_TOKEN":
        print("⚠️  Warning: TELEGRAM_BOT_TOKEN is not set or still set to default placeholder.")
        print("Please set it in config/config.yaml or via TELEGRAM_BOT_TOKEN environment variable.")
        sys.exit(1)

    notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)

    print("🔍 Testing Telegram Bot credentials via getMe...")
    try:
        bot_info = notifier.verify_credentials()
        bot_username = bot_info.get("username", "Unknown")
        bot_first_name = bot_info.get("first_name", "Bot")
        print(f"✅ Bot verified successfully: @{bot_username} ({bot_first_name})")
    except Exception as e:
        print(f"❌ Failed to verify bot credentials: {e}")
        sys.exit(1)

    print(f"📤 Dispatching sample job alert to chat ID: {chat_id}...")
    sample_url = "https://example.com/jobs/senior-backend-engineer-berlin"
    sample_job = JobRecord(
        id=compute_job_id(sample_url),
        source="sanity-check",
        title="Senior Backend Engineer (Python / Distributed Systems)",
        company="JobPulse Engineering GmbH",
        location="Berlin, Germany (Hybrid)",
        url=sample_url,
        canonical_url=sample_url,
        status="notified",
        meta={"test_mode": True},
    )

    try:
        res = notifier.send_job_alert(sample_job)
        message_id = res.get("result", {}).get("message_id")
        print(f"🎉 Success! Telegram alert sent (Message ID: {message_id}). Check your Telegram app!")
    except Exception as e:
        print(f"❌ Error dispatching test message: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
