"""Bundesagentur für Arbeit open REST API poller for Job Pulse.

Fetches daily engineering postings from `rest.arbeitsagentur.de` open search,
evaluates criteria via Matcher, saves new records into SQLite, and triggers Telegram alerts.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx

from src.config import AppConfig, ArbeitsagenturConfig
from src.db import Database, JobRecord
from src.matcher import JobMatcher
from src.notifier import TelegramNotifier

logger = logging.getLogger(__name__)

ARBEITSAGENTUR_BASE_URL = (
    "https://rest.arbeitsagentur.de/opensearch/vam-berufe-service/v1/stellenangebote"
)
DEFAULT_HEADERS = {
    "User-Agent": "JobPulse/1.0 (+https://github.com/hivaamiri/career-forge)",
    "X-API-Key": "jobboerse-jobsuche",
    "Accept": "application/json",
}


class ArbeitsagenturPoller:
    """Poller for Bundesagentur für Arbeit public REST job search endpoint."""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        notifier: Optional[TelegramNotifier] = None,
        matcher: Optional[JobMatcher] = None,
        timeout: float = 15.0,
    ):
        self.config = config
        self.aa_config: ArbeitsagenturConfig = config.arbeitsagentur
        self.db = db
        self.notifier = notifier or TelegramNotifier(
            bot_token=config.telegram.bot_token, chat_id=config.telegram.chat_id
        )
        self.matcher = matcher or JobMatcher(config=config.matcher)
        self.timeout = timeout

    def fetch_jobs(
        self,
        keyword: str,
        location: Optional[str] = None,
        radius_km: int = 50,
        size: int = 25,
        client: Optional[httpx.Client] = None,
    ) -> List[Dict[str, Any]]:
        """Query Bundesagentur für Arbeit REST search."""
        params: Dict[str, Any] = {
            "was": keyword,
            "size": size,
            "angebotsart": 1,  # 1 = Regular employment
        }
        if location and location.lower() not in ["remote", "deutschland", "germany"]:
            params["wo"] = location
            params["umkreis"] = radius_km

        def _do_get(c: httpx.Client) -> List[Dict[str, Any]]:
            try:
                response = c.get(
                    ARBEITSAGENTUR_BASE_URL,
                    params=params,
                    headers=DEFAULT_HEADERS,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("stellenangebote", [])
            except Exception as e:
                logger.warning(
                    f"Arbeitsagentur query failed for was='{keyword}', wo='{location}': {e}"
                )
                return []

        if client:
            return _do_get(client)
        with httpx.Client(timeout=self.timeout) as new_client:
            return _do_get(new_client)

    def parse_job_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalize an Arbeitsagentur raw item into job attributes."""
        refnr = item.get("refnr")
        if not refnr:
            return None

        title = item.get("titel") or item.get("beruf") or "Software Engineering"
        company = item.get("arbeitgeber") or "Unbekannter Arbeitgeber"

        # Resolve location
        arbeitsort = item.get("arbeitsort") or {}
        loc_parts = []
        if isinstance(arbeitsort, dict):
            ort = arbeitsort.get("ort")
            region = arbeitsort.get("region")
            if ort:
                loc_parts.append(ort)
            if region and region != ort:
                loc_parts.append(region)
        location_str = ", ".join(loc_parts) or "Deutschland"

        # Direct official detail landing page
        canonical_url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
        external_url = item.get("externeUrl") or canonical_url

        return {
            "refnr": refnr,
            "title": title.strip(),
            "company": company.strip(),
            "location": location_str,
            "url": external_url.strip(),
            "canonical_url": canonical_url.strip(),
            "published_at": item.get("aktuelleVeroeffentlichungsdatum"),
        }

    def poll(self, client: Optional[httpx.Client] = None) -> List[JobRecord]:
        """Execute complete poll loop across configured keywords and locations."""
        if not self.aa_config.enabled:
            logger.info("Arbeitsagentur ingestion is disabled in config.")
            return []

        logger.info("Starting Arbeitsagentur API poll...")
        discovered: List[JobRecord] = []

        keywords = self.aa_config.keywords or ["backend engineer"]
        locations = self.aa_config.locations or ["Deutschland"]

        for kw in keywords:
            for loc in locations:
                raw_items = self.fetch_jobs(
                    keyword=kw,
                    location=loc,
                    radius_km=self.aa_config.radius_km,
                    client=client,
                )
                for item in raw_items:
                    parsed = self.parse_job_item(item)
                    if not parsed:
                        continue

                    # Filter through heuristic matcher
                    match_res = self.matcher.evaluate(
                        title=parsed["title"],
                        location=parsed["location"],
                    )
                    if not match_res.matched:
                        continue

                    # Deduplication check in SQLite
                    canonical_url = parsed["canonical_url"]
                    if self.db.is_seen(canonical_url):
                        continue

                    # Save to DB
                    job_id, inserted = self.db.save_job(
                        source="arbeitsagentur",
                        title=parsed["title"],
                        company=parsed["company"],
                        location=parsed["location"],
                        url=parsed["url"],
                        canonical_url=canonical_url,
                        status="notified",
                        meta={
                            "refnr": parsed["refnr"],
                            "match_reason": match_res.reason,
                            "matched_inclusions": match_res.matched_inclusions,
                            "published_at": parsed.get("published_at"),
                        },
                    )

                    if not inserted:
                        continue

                    job_record = self.db.get_job(job_id)
                    if not job_record:
                        continue

                    # Telegram notification
                    try:
                        self.notifier.send_job_alert(job_record)
                        logger.info(
                            f"Dispatched Arbeitsagentur alert: '{job_record.title}' @ '{job_record.company}'"
                        )
                    except Exception as err:
                        logger.error(f"Failed to dispatch Telegram alert for {job_id}: {err}")

                    discovered.append(job_record)

        logger.info(f"Arbeitsagentur poll complete. Added {len(discovered)} new job(s).")
        return discovered
