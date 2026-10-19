"""Telegram Callback Listener: Handles interactive inline button clicks and triggers Career-Ops bridge."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from src.bridge_careerops import queue_job_to_careerops
from src.config import AppConfig
from src.db import Database
from src.notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class TelegramCallbackHandler:
    """Polls Telegram updates for inline button callback queries and executes actions."""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        notifier: Optional[TelegramNotifier] = None,
    ):
        self.config = config
        self.db = db
        self.notifier = notifier or TelegramNotifier(
            bot_token=config.telegram.bot_token, chat_id=config.telegram.chat_id
        )
        self.pipeline_path = config.career_ops.pipeline_path
        self._last_update_id: Optional[int] = None

    def process_updates(self, timeout: int = 5) -> int:
        """Fetch and process pending callback queries. Returns number of processed callbacks."""
        try:
            offset = (self._last_update_id + 1) if self._last_update_id is not None else None
            data = self.notifier.get_updates(offset=offset, timeout=timeout)
        except Exception as e:
            logger.warning(f"Failed to fetch Telegram updates: {e}")
            return 0

        updates = data.get("result", [])
        processed = 0

        for update in updates:
            update_id = update.get("update_id")
            if update_id is not None:
                self._last_update_id = update_id

            callback = update.get("callback_query")
            if not callback:
                continue

            callback_id = callback.get("id")
            callback_data = callback.get("data", "")

            job_id = None
            if callback_data.startswith("q:"):
                job_id = callback_data[len("q:") :].strip()
            elif callback_data.startswith("queue:"):
                job_id = callback_data[len("queue:") :].strip()

            if job_id:
                logger.info(f"Received Queue Career-Ops callback for job_id={job_id}")

                success, message = queue_job_to_careerops(
                    job_id=job_id,
                    db=self.db,
                    pipeline_path=self.pipeline_path,
                )

                notification_text = (
                    "✅ Queued into Career-Ops pipeline!"
                    if success
                    else f"ℹ️ {message}"
                )

                try:
                    self.notifier.answer_callback_query(
                        callback_query_id=callback_id,
                        text=notification_text,
                    )
                except Exception as err:
                    logger.warning(f"Failed to answer callback query: {err}")

                processed += 1

        return processed
