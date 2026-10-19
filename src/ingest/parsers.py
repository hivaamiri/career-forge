"""HTML Email Parsers for StepStone, LinkedIn, and XING job alert notifications."""

from __future__ import annotations

import logging
import re
from typing import List, Optional
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ParsedEmailJob(BaseModel):
    source: str
    title: str
    company: str
    location: Optional[str] = None
    raw_url: str
    snippet: Optional[str] = None


def _clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    # Normalize excessive whitespace and linebreaks
    return " ".join(text.split()).strip()


def parse_stepstone_email(html_content: str) -> List[ParsedEmailJob]:
    """Parse StepStone job alert notification emails."""
    soup = BeautifulSoup(html_content, "html.parser")
    jobs: List[ParsedEmailJob] = []

    # StepStone alert emails typically use anchor links pointing to job offers
    # Patterns: /stellenangebote-- or /jobs/ or click.stepstone
    anchors = soup.find_all("a", href=True)
    seen_urls = set()

    for a in anchors:
        href = a["href"].strip()
        if not href or href in seen_urls:
            continue

        is_stepstone_job = any(
            kw in href.lower()
            for kw in ["stellenangebote", "job-detail", "/job/", "click.stepstone"]
        )
        if not is_stepstone_job:
            continue

        title = _clean_text(a.get_text())
        if len(title) < 4 or any(
            skip in title.lower()
            for skip in ["abmelden", "ansicht", "hilfe", "stepstone", "profil", "jetzt bewerben"]
        ):
            continue

        seen_urls.add(href)

        # Look in ancestor container or next sibling for company and location
        container = a.find_parent(["td", "div", "li", "tr"]) or a.parent
        company = "StepStone Match"
        location = None
        snippet = None

        if container:
            text_lines = [
                _clean_text(line)
                for line in container.stripped_strings
                if _clean_text(line) and _clean_text(line) != title
            ]
            if len(text_lines) >= 1:
                company = text_lines[0]
            if len(text_lines) >= 2:
                location = text_lines[1]
            if len(text_lines) >= 3:
                snippet = " | ".join(text_lines[2:5])

        jobs.append(
            ParsedEmailJob(
                source="stepstone",
                title=title,
                company=company,
                location=location,
                raw_url=href,
                snippet=snippet,
            )
        )

    return jobs


def parse_linkedin_email(html_content: str) -> List[ParsedEmailJob]:
    """Parse LinkedIn job alert notification emails."""
    soup = BeautifulSoup(html_content, "html.parser")
    jobs: List[ParsedEmailJob] = []
    seen_urls = set()

    anchors = soup.find_all("a", href=True)
    for a in anchors:
        href = a["href"].strip()
        if not href or href in seen_urls:
            continue

        # LinkedIn job alert URLs: linkedin.com/comm/jobs/view or linkedin.com/jobs/view
        if not re.search(r"linkedin\.com/(?:comm/)?jobs/view/", href, re.IGNORECASE):
            continue

        title = _clean_text(a.get_text())
        if len(title) < 3 or any(
            skip in title.lower()
            for skip in ["job alert", "view job", "unsubscribe", "manage", "see all", "bewerben"]
        ):
            continue

        seen_urls.add(href)

        container = a.find_parent(["td", "div", "li", "table"]) or a.parent
        company = "LinkedIn Match"
        location = None
        snippet = None

        if container:
            lines = [
                _clean_text(line)
                for line in container.stripped_strings
                if _clean_text(line) and _clean_text(line) != title
            ]
            if len(lines) >= 1:
                company = lines[0]
            if len(lines) >= 2:
                location = lines[1]
            if len(lines) >= 3:
                snippet = " | ".join(lines[2:4])

        jobs.append(
            ParsedEmailJob(
                source="linkedin",
                title=title,
                company=company,
                location=location,
                raw_url=href,
                snippet=snippet,
            )
        )

    return jobs


def parse_xing_email(html_content: str) -> List[ParsedEmailJob]:
    """Parse XING job alert notification emails."""
    soup = BeautifulSoup(html_content, "html.parser")
    jobs: List[ParsedEmailJob] = []
    seen_urls = set()

    anchors = soup.find_all("a", href=True)
    for a in anchors:
        href = a["href"].strip()
        if not href or href in seen_urls:
            continue

        if not re.search(r"xing\.com/jobs/(?:de/)?", href, re.IGNORECASE):
            continue

        title = _clean_text(a.get_text())
        if len(title) < 4 or any(
            skip in title.lower()
            for skip in ["jobempfehlungen", "einstellungen", "abmelden", "profil", "details"]
        ):
            continue

        seen_urls.add(href)

        container = a.find_parent(["td", "div", "li"]) or a.parent
        company = "XING Match"
        location = None
        snippet = None

        if container:
            lines = [
                _clean_text(line)
                for line in container.stripped_strings
                if _clean_text(line) and _clean_text(line) != title
            ]
            if len(lines) >= 1:
                company = lines[0]
            if len(lines) >= 2:
                location = lines[1]
            if len(lines) >= 3:
                snippet = " | ".join(lines[2:4])

        jobs.append(
            ParsedEmailJob(
                source="xing",
                title=title,
                company=company,
                location=location,
                raw_url=href,
                snippet=snippet,
            )
        )

    return jobs


def parse_email_message(
    sender: str,
    subject: str,
    html_content: str,
) -> List[ParsedEmailJob]:
    """Identify the email source provider and parse all candidate job listings."""
    sender_lower = sender.lower()
    subject_lower = subject.lower()

    if "stepstone" in sender_lower or "stepstone" in subject_lower:
        return parse_stepstone_email(html_content)
    elif "linkedin" in sender_lower or "linkedin" in subject_lower:
        return parse_linkedin_email(html_content)
    elif "xing" in sender_lower or "xing" in subject_lower:
        return parse_xing_email(html_content)

    # If sender did not match known domains, try parsing each format
    results = parse_stepstone_email(html_content)
    if results:
        return results
    results = parse_linkedin_email(html_content)
    if results:
        return results
    results = parse_xing_email(html_content)
    if results:
        return results

    return []
