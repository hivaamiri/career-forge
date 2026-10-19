"""Main daemon orchestrator for Job Pulse.

Coordinates the periodic execution of:
- Email stream consumer (StepStone, XING, LinkedIn)
- Arbeitsagentur REST API poller
- Target company Personio/ATS poller
- Telegram callback listener for [Queue Career-Ops]
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from src.config import AppConfig, load_config
from src.db import Database
from src.ingest.arbeitsagentur import ArbeitsagenturPoller
from src.ingest.ats_poller import ATSPoller
from src.ingest.email_stream import EmailStreamConsumer
from src.matcher import JobMatcher
from src.notifier import TelegramNotifier

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("job_pulse.orchestrator")


class Orchestrator:
    """Manages ingestion loops and daemon lifecycle."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.db = Database(db_path=config.database.path)
        self.notifier = TelegramNotifier(
            bot_token=config.telegram.bot_token,
            chat_id=config.telegram.chat_id,
        )
        self.matcher = JobMatcher(config=config.matcher)

        self.email_consumer = EmailStreamConsumer(
            config=config,
            db=self.db,
            notifier=self.notifier,
            matcher=self.matcher,
        )
        self.aa_poller = ArbeitsagenturPoller(
            config=config,
            db=self.db,
            notifier=self.notifier,
            matcher=self.matcher,
        )
        self.ats_poller = ATSPoller(
            config=config,
            db=self.db,
            notifier=self.notifier,
            matcher=self.matcher,
        )
        from src.telegram_listener import TelegramCallbackHandler
        self.callback_handler = TelegramCallbackHandler(
            config=config,
            db=self.db,
            notifier=self.notifier,
            on_config_change=self.sync_dynamic_settings,
            on_sweep_request=self.run_once,
        )

        self._running = False
        self._last_email_check = 0.0
        self._last_aa_poll = 0.0
        self._last_ats_poll = 0.0

        # Apply any previously stored dynamic settings on startup
        self.sync_dynamic_settings()

    def sync_dynamic_settings(self) -> None:
        """Apply dynamic configuration overrides stored in SQLite."""
        keywords = self.db.get_setting("keywords", self.config.arbeitsagentur.keywords)
        locations = self.db.get_setting("locations", self.config.arbeitsagentur.locations)
        radius = self.db.get_setting("radius_km", self.config.arbeitsagentur.radius_km)
        companies = self.db.get_setting("personio_companies", self.config.ats.personio_companies)

        # Update Arbeitsagentur poller
        self.aa_poller.aa_config.keywords = list(keywords)
        self.aa_poller.aa_config.locations = list(locations)
        self.aa_poller.aa_config.radius_km = int(radius)

        # Update ATS poller
        self.ats_poller.ats_config.personio_companies = list(companies)

        # Update Matcher location patterns
        self.matcher.update_rules(locations=list(locations))
        logger.info(
            f"Synced dynamic settings: {len(keywords)} keywords, "
            f"{len(locations)} locations, radius={radius}km, {len(companies)} ATS companies"
        )

    def run_once(self) -> dict[str, int]:
        """Execute a single pass across all enabled ingestion sources."""
        logger.info("Executing single ingestion sweep across all active providers...")
        counts = {"email": 0, "arbeitsagentur": 0, "ats": 0}

        # 1. Email Stream
        if self.config.email.enabled:
            try:
                jobs = self.email_consumer.process_inbox()
                counts["email"] = len(jobs)
            except Exception as e:
                logger.error(f"Error during email stream run: {e}", exc_info=True)

        # 2. Arbeitsagentur REST API
        if self.config.arbeitsagentur.enabled:
            try:
                jobs = self.aa_poller.poll()
                counts["arbeitsagentur"] = len(jobs)
            except Exception as e:
                logger.error(f"Error during Arbeitsagentur poll: {e}", exc_info=True)

        # 3. Target ATS Boards
        if self.config.ats.enabled:
            try:
                jobs = self.ats_poller.poll()
                counts["ats"] = len(jobs)
            except Exception as e:
                logger.error(f"Error during ATS poll: {e}", exc_info=True)

        # 4. Process any pending interactive Telegram callbacks
        try:
            self.callback_handler.process_updates(timeout=1)
        except Exception as e:
            logger.warning(f"Error checking Telegram callbacks: {e}")

        total = sum(counts.values())
        logger.info(
            f"Sweep finished. New jobs discovered: Total={total} "
            f"(Email={counts['email']}, Arbeitsagentur={counts['arbeitsagentur']}, ATS={counts['ats']})"
        )
        return counts

    def run_daemon(self) -> None:
        """Run continuous background loop respecting provider intervals."""
        self._running = True
        logger.info("Starting Job Pulse daemon loop. Press Ctrl+C to stop.")

        while self._running:
            now = time.time()

            # Process Telegram interactive buttons (callbacks)
            try:
                self.callback_handler.process_updates(timeout=1)
            except Exception as e:
                logger.warning(f"Error handling Telegram updates: {e}")

            # Email stream check
            if (
                self.config.email.enabled
                and (now - self._last_email_check) >= self.config.email.check_interval_seconds
            ):
                try:
                    self.email_consumer.process_inbox()
                except Exception as e:
                    logger.error(f"Email stream error: {e}")
                self._last_email_check = time.time()

            # Arbeitsagentur check
            if (
                self.config.arbeitsagentur.enabled
                and (now - self._last_aa_poll)
                >= self.config.arbeitsagentur.poll_interval_seconds
            ):
                try:
                    self.aa_poller.poll()
                except Exception as e:
                    logger.error(f"Arbeitsagentur poller error: {e}")
                self._last_aa_poll = time.time()

            # ATS check
            if (
                self.config.ats.enabled
                and (now - self._last_ats_poll) >= self.config.ats.poll_interval_seconds
            ):
                try:
                    self.ats_poller.poll()
                except Exception as e:
                    logger.error(f"ATS poller error: {e}")
                self._last_ats_poll = time.time()

            # Short sleep to prevent CPU spinning while maintaining responsiveness
            time.sleep(3)

        logger.info("Job Pulse daemon stopped cleanly.")

    def stop(self) -> None:
        """Signal the daemon loop to stop."""
        self._running = False


def main():
    parser = argparse.ArgumentParser(description="Job Pulse: Automated Engineering Job Discovery")
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to YAML config file (default: config/config.yaml or env JOB_PULSE_CONFIG)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Execute single polling iteration and exit immediately",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except Exception as e:
        logger.error(f"Configuration failed to load: {e}")
        sys.exit(1)

    orchestrator = Orchestrator(config)

    def handle_signal(sig, frame):
        logger.info(f"Received shutdown signal ({sig}). Stopping gracefully...")
        orchestrator.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if args.once:
        orchestrator.run_once()
    else:
        orchestrator.run_daemon()


if __name__ == "__main__":
    main()
