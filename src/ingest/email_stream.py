"""IMAP email stream consumer for Job Pulse.

Connects to IMAP server, queries unread job alerts from StepStone, LinkedIn, and XING,
unwraps URLs, filters against matcher criteria, persists new listings to SQLite,
and triggers instant Telegram notifications.
"""

from __future__ import annotations

import email
from email.header import decode_header
import imaplib
import logging
from typing import List, Optional, Tuple

from src.config import AppConfig, EmailConfig
from src.db import Database, JobRecord
from src.ingest.parsers import ParsedEmailJob, parse_email_message
from src.ingest.url_resolver import resolve_canonical_url
from src.matcher import JobMatcher
from src.notifier import TelegramNotifier

logger = logging.getLogger(__name__)


def _decode_header_str(header_val: Optional[str]) -> str:
    """Decode RFC 2047 email headers safely."""
    if not header_val:
        return ""
    decoded_fragments = decode_header(header_val)
    parts = []
    for fragment, encoding in decoded_fragments:
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(str(fragment))
    return "".join(parts).strip()


def extract_html_body(msg: email.message.Message) -> str:
    """Extract HTML or plain text payload from a MIME email message."""
    html_parts = []
    text_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Skip attachments
            if "attachment" in content_disposition:
                continue

            payload = part.get_payload(decode=True)
            if not payload:
                continue

            charset = part.get_content_charset() or "utf-8"
            decoded_text = payload.decode(charset, errors="replace")

            if content_type == "text/html":
                html_parts.append(decoded_text)
            elif content_type == "text/plain":
                text_parts.append(decoded_text)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded_text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_parts.append(decoded_text)
            else:
                text_parts.append(decoded_text)

    if html_parts:
        return "\n".join(html_parts)
    return "\n".join(text_parts)


class EmailStreamConsumer:
    """Consumes and processes job notification emails from an IMAP mailbox."""

    TARGET_SENDERS = ["stepstone", "linkedin", "xing"]

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        notifier: Optional[TelegramNotifier] = None,
        matcher: Optional[JobMatcher] = None,
    ):
        self.config = config
        self.email_config = config.email
        self.db = db
        self.notifier = notifier or TelegramNotifier(
            bot_token=config.telegram.bot_token, chat_id=config.telegram.chat_id
        )
        self.matcher = matcher or JobMatcher(config=config.matcher)

    def connect(self) -> imaplib.IMAP4_SSL:
        """Establish authenticated IMAP4_SSL connection."""
        if not self.email_config.username or not self.email_config.password:
            raise ValueError(
                "IMAP username and password must be configured in config/config.yaml or via environment variables."
            )

        client = imaplib.IMAP4_SSL(
            host=self.email_config.imap_server,
            port=self.email_config.imap_port,
        )
        username = self.email_config.username.strip()
        pwd = self.email_config.password.strip()
        try:
            client.login(username, pwd)
        except Exception:
            client.login(username, pwd.replace(" ", ""))
        return client

    def process_inbox(self) -> List[JobRecord]:
        """Poll mailbox for unread alerts, filter, save, and notify.

        Returns list of newly discovered JobRecord items.
        """
        if not self.email_config.enabled:
            logger.info("Email stream ingestion is disabled in config.")
            return []

        logger.info(
            f"Connecting to IMAP {self.email_config.imap_server}:{self.email_config.imap_port} as {self.email_config.username}..."
        )

        try:
            client = self.connect()
        except Exception as e:
            logger.error(f"Failed to connect/authenticate to IMAP server: {e}")
            return []

        new_jobs: List[JobRecord] = []
        try:
            status, _ = client.select(self.email_config.folder)
            if status != "OK":
                logger.error(f"Could not select folder '{self.email_config.folder}'")
                return []

            # Search for unread messages
            status, response = client.search(None, "UNSEEN")
            if status != "OK" or not response or not response[0]:
                logger.debug("No unread emails found in mailbox.")
                return []

            message_ids = response[0].split()
            logger.info(f"Found {len(message_ids)} unread email(s). Processing...")

            for msg_id in message_ids:
                try:
                    jobs = self._process_single_message(client, msg_id)
                    new_jobs.extend(jobs)
                except Exception as err:
                    logger.warning(f"Error processing email ID {msg_id}: {err}")
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass

        logger.info(f"Completed email processing. Discovered {len(new_jobs)} new matching job(s).")
        return new_jobs

    def _process_single_message(
        self, client: imaplib.IMAP4_SSL, msg_id: bytes
    ) -> List[JobRecord]:
        status, data = client.fetch(msg_id, "(RFC822)")
        if status != "OK" or not data or not data[0]:
            return []

        raw_email = data[0][1]
        msg = email.message_from_bytes(raw_email)

        sender = _decode_header_str(msg.get("From", ""))
        subject = _decode_header_str(msg.get("Subject", ""))

        # Check if sender matches any target job boards
        is_target = any(t in sender.lower() or t in subject.lower() for t in self.TARGET_SENDERS)
        if not is_target:
            logger.debug(f"Skipping email from '{sender}': Not in target senders list.")
            return []

        logger.info(f"Processing job alert email: '{subject}' from '{sender}'")
        html_body = extract_html_body(msg)
        if not html_body:
            return []

        parsed_jobs = parse_email_message(sender, subject, html_body)
        discovered: List[JobRecord] = []

        for parsed in parsed_jobs:
            # 1. Matcher filter
            match_res = self.matcher.evaluate(
                title=parsed.title,
                location=parsed.location,
                snippet=parsed.snippet,
            )
            if not match_res.matched:
                logger.debug(f"Filtered out '{parsed.title}': {match_res.reason}")
                continue

            # 2. Resolve canonical URL
            canonical_url = resolve_canonical_url(parsed.raw_url)

            # 3. Check SQLite deduplication
            if self.db.is_seen(canonical_url):
                logger.debug(f"Skipping duplicate job: '{parsed.title}' ({canonical_url})")
                continue

            # 4. Save to Database
            job_id, inserted = self.db.save_job(
                source=parsed.source,
                title=parsed.title,
                company=parsed.company,
                location=parsed.location,
                url=parsed.raw_url,
                canonical_url=canonical_url,
                status="notified",
                meta={
                    "match_reason": match_res.reason,
                    "matched_inclusions": match_res.matched_inclusions,
                    "email_subject": subject,
                },
            )

            if not inserted:
                continue

            job_record = self.db.get_job(job_id)
            if not job_record:
                continue

            # 5. Dispatch Telegram Alert
            try:
                self.notifier.send_job_alert(job_record)
                logger.info(f"Dispatched Telegram alert for: '{job_record.title}' @ '{job_record.company}'")
            except Exception as notify_err:
                logger.error(f"Failed to dispatch Telegram alert for {job_id}: {notify_err}")

            discovered.append(job_record)

        # Mark message as read
        client.store(msg_id, "+FLAGS", "\\Seen")
        return discovered
