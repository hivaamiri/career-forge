"""Target company Personio XML and ATS board poller for Job Pulse.

Polls target companies using Personio XML/JSON feeds (`https://<company>.jobs.personio.de/xml`)
and standard ATS boards, filters matching roles, saves new postings into SQLite,
and dispatches Telegram alerts.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET
import httpx

from src.config import AppConfig, ATSConfig
from src.db import Database, JobRecord
from src.matcher import JobMatcher
from src.notifier import TelegramNotifier

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "JobPulse/1.0 (+https://github.com/hivaamiri/career-forge)",
    "Accept": "application/xml,text/xml,application/json,*/*",
}


def parse_personio_xml(company_name: str, xml_content: str) -> List[Dict[str, Any]]:
    """Parse Personio XML job board format into standardized dictionary items."""
    jobs: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.warning(f"Failed to parse Personio XML for {company_name}: {e}")
        return []

    # XML root is typically <work-units> or contains <position> children
    positions = root.findall(".//position")
    for pos in positions:
        pos_id = pos.findtext("id") or ""
        name = pos.findtext("name") or ""
        office = pos.findtext("office") or ""
        department = pos.findtext("department") or ""
        employment_type = pos.findtext("employmentType") or ""

        if not name:
            continue

        # Extract descriptions for snippet matching
        snippets = []
        for desc in pos.findall(".//jobDescription"):
            val = desc.findtext("value")
            if val:
                snippets.append(val[:200])

        combined_snippet = f"{department} | {employment_type} | {' '.join(snippets)}".strip()
        job_url = f"https://{company_name}.jobs.personio.de/job/{pos_id}" if pos_id else f"https://{company_name}.jobs.personio.de"

        jobs.append(
            {
                "id": pos_id,
                "title": name.strip(),
                "company": company_name.capitalize(),
                "location": office.strip() or "Remote / Deutschland",
                "url": job_url,
                "canonical_url": job_url,
                "snippet": combined_snippet,
            }
        )

    return jobs


class ATSPoller:
    """Poller for Personio and direct ATS feeds of target companies."""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        notifier: Optional[TelegramNotifier] = None,
        matcher: Optional[JobMatcher] = None,
        timeout: float = 15.0,
    ):
        self.config = config
        self.ats_config: ATSConfig = config.ats
        self.db = db
        self.notifier = notifier or TelegramNotifier(
            bot_token=config.telegram.bot_token, chat_id=config.telegram.chat_id
        )
        self.matcher = matcher or JobMatcher(config=config.matcher)
        self.timeout = timeout

    def fetch_personio_feed(
        self, company_slug: str, client: Optional[httpx.Client] = None
    ) -> List[Dict[str, Any]]:
        """Fetch and parse Personio XML feed for a given company slug."""
        feed_url = f"https://{company_slug}.jobs.personio.de/xml"

        def _do_fetch(c: httpx.Client) -> List[Dict[str, Any]]:
            try:
                response = c.get(feed_url, headers=DEFAULT_HEADERS, timeout=self.timeout)
                if response.status_code == 404:
                    logger.debug(f"Personio feed not found for company '{company_slug}'")
                    return []
                response.raise_for_status()
                return parse_personio_xml(company_slug, response.text)
            except Exception as e:
                logger.warning(f"Error fetching Personio feed for '{company_slug}': {e}")
                return []

        if client:
            return _do_fetch(client)
        with httpx.Client(timeout=self.timeout) as new_client:
            return _do_fetch(new_client)

    def poll(self, client: Optional[httpx.Client] = None) -> List[JobRecord]:
        """Poll all configured company ATS boards."""
        if not self.ats_config.enabled:
            logger.info("ATS ingestion is disabled in config.")
            return []

        companies = self.ats_config.personio_companies
        if not companies:
            logger.debug("No Personio companies configured for ATS polling.")
            return []

        logger.info(f"Starting ATS poll for {len(companies)} company feed(s)...")
        discovered: List[JobRecord] = []

        for comp in companies:
            clean_comp = comp.strip().lower()
            if not clean_comp:
                continue

            raw_jobs = self.fetch_personio_feed(clean_comp, client=client)
            for item in raw_jobs:
                match_res = self.matcher.evaluate(
                    title=item["title"],
                    location=item["location"],
                    snippet=item.get("snippet"),
                )
                if not match_res.matched:
                    continue

                canonical_url = item["canonical_url"]
                if self.db.is_seen(canonical_url):
                    continue

                job_id, inserted = self.db.save_job(
                    source="personio",
                    title=item["title"],
                    company=item["company"],
                    location=item["location"],
                    url=item["url"],
                    canonical_url=canonical_url,
                    status="notified",
                    meta={
                        "personio_id": item.get("id"),
                        "match_reason": match_res.reason,
                        "matched_inclusions": match_res.matched_inclusions,
                    },
                )

                if not inserted:
                    continue

                job_record = self.db.get_job(job_id)
                if not job_record:
                    continue

                try:
                    self.notifier.send_job_alert(job_record)
                    logger.info(
                        f"Dispatched Personio alert: '{job_record.title}' @ '{job_record.company}'"
                    )
                except Exception as err:
                    logger.error(f"Failed to dispatch Telegram alert for {job_id}: {err}")

                discovered.append(job_record)

        logger.info(f"ATS poll complete. Added {len(discovered)} new job(s).")
        return discovered
