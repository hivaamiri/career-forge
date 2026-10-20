"""Job Description Scraper for Career-Ops.

Extracts rich job details, requirements, tasks, and context from
Arbeitsagentur, StepStone, LinkedIn, Personio, and general job boards.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger("career_ops.scraper")


class ScrapedJob(BaseModel):
    id: str = Field(..., description="Deterministic hash of the canonical URL")
    title: str
    company: str
    location: Optional[str] = None
    url: str
    canonical_url: str
    description: str = ""
    tasks: List[str] = Field(default_factory=list)
    requirements: List[str] = Field(default_factory=list)
    benefits: List[str] = Field(default_factory=list)
    raw_html: Optional[str] = None
    scraped_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def compute_job_id(url: str) -> str:
    """Compute SHA-256 hash for consistent caching."""
    clean = url.strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


class JobDescriptionScraper:
    """Scrapes, extracts, and caches full job descriptions."""

    def __init__(self, cache_dir: str | Path = "career-ops/data/jobs"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def get_cached(self, job_id_or_url: str) -> Optional[ScrapedJob]:
        """Retrieve previously scraped job from disk cache."""
        if job_id_or_url.startswith("http://") or job_id_or_url.startswith("https://"):
            job_id = compute_job_id(job_id_or_url)
        else:
            job_id = job_id_or_url

        json_path = self.cache_dir / f"{job_id}.json"
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return ScrapedJob.model_validate(data)
            except Exception as e:
                logger.warning(f"Failed to read cache for {job_id}: {e}")
        return None

    def save_cache(self, job: ScrapedJob) -> None:
        """Persist scraped job to JSON and human-readable Markdown."""
        json_path = self.cache_dir / f"{job.id}.json"
        md_path = self.cache_dir / f"{job.id}.md"

        # 1. Save JSON (without massive raw_html to keep it light)
        data = job.model_dump()
        data.pop("raw_html", None)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 2. Save human-readable Markdown
        tasks_md = "\n".join([f"- {t}" for t in job.tasks]) or "*(Keine Aufgaben separat extrahiert)*"
        reqs_md = "\n".join([f"- {r}" for r in job.requirements]) or "*(Keine Anforderungen separat extrahiert)*"
        benefits_md = "\n".join([f"- {b}" for b in job.benefits]) or "*(Keine Benefits separat extrahiert)*"

        content = f"""# {job.title}
**Unternehmen:** {job.company}  
**Standort:** {job.location or 'Nicht angegeben'}  
**URL:** [{job.canonical_url}]({job.canonical_url})  
**Erfasst am:** {job.scraped_at}  

---

## 📋 Aufgaben & Verantwortlichkeiten
{tasks_md}

## 🎯 Anforderungen & Qualifikationen
{reqs_md}

## 🎁 Benefits & Angebot
{benefits_md}

---

## 📄 Vollständige Stellenbeschreibung
{job.description}
"""
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)

    def scrape(
        self,
        url: str,
        title: str = "",
        company: str = "",
        location: Optional[str] = None,
        force_refresh: bool = False,
    ) -> ScrapedJob:
        """Fetch and extract job details from the target URL."""
        job_id = compute_job_id(url)
        if not force_refresh:
            cached = self.get_cached(job_id)
            if cached:
                logger.info(f"Loaded cached job description for {url} ({job_id})")
                return cached

        logger.info(f"Fetching job description from {url}...")
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(url, headers=self.headers)
                resp.raise_for_status()
                html_text = resp.text
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            fallback_job = ScrapedJob(
                id=job_id,
                title=title or "Unbekannte Position",
                company=company or "Unbekanntes Unternehmen",
                location=location,
                url=url,
                canonical_url=url,
                description=f"Automatischer Abruf fehlgeschlagen: {e}",
            )
            self.save_cache(fallback_job)
            return fallback_job

        soup = BeautifulSoup(html_text, "html.parser")

        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)
            elif soup.title:
                title = soup.title.get_text(strip=True).split("|")[0].split("-")[0].strip()

        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
            tag.decompose()

        main_container = (
            soup.find("main")
            or soup.find("article")
            or soup.find(id=re.compile(r"job|content|detail", re.I))
            or soup.find(class_=re.compile(r"job[-_]?description|job[-_]?detail|stellenbeschreibung", re.I))
            or soup.body
        )

        full_text = ""
        tasks: List[str] = []
        requirements: List[str] = []
        benefits: List[str] = []

        if main_container:
            full_text = main_container.get_text(separator="\n", strip=True)
            tasks, requirements, benefits = self._extract_sections(main_container)

        scraped = ScrapedJob(
            id=job_id,
            title=title or "Chemie Position",
            company=company or "Unternehmen",
            location=location,
            url=url,
            canonical_url=url,
            description=full_text,
            tasks=tasks,
            requirements=requirements,
            benefits=benefits,
        )

        self.save_cache(scraped)
        return scraped

    def _extract_sections(self, container: BeautifulSoup) -> tuple[List[str], List[str], List[str]]:
        tasks: List[str] = []
        requirements: List[str] = []
        benefits: List[str] = []

        headings = container.find_all(re.compile(r"^(h2|h3|h4|h5|strong|b)$"))
        for h in headings:
            heading_text = h.get_text(strip=True).lower()
            target_list = None
            if any(k in heading_text for k in ["aufgabe", "verantwortung", "ihr job", "deine aufgaben", "ihre aufgaben", "was sie erwartet"]):
                target_list = tasks
            elif any(k in heading_text for k in ["anforderung", "profil", "qualifikation", "voraussetzung", "das bringen sie mit", "ihr profil", "ihre qualifikationen"]):
                target_list = requirements
            elif any(k in heading_text for k in ["wir bieten", "benefit", "vorteile", "unser angebot", "das bieten wir"]):
                target_list = benefits

            if target_list is not None:
                sibling = h.find_next_sibling()
                while sibling and sibling.name in ["p", "div", "ul", "ol"]:
                    if sibling.name in ["ul", "ol"]:
                        for li in sibling.find_all("li"):
                            txt = li.get_text(strip=True)
                            if txt and len(txt) > 5 and txt not in target_list:
                                target_list.append(txt)
                        break
                    elif sibling.name == "p":
                        txt = sibling.get_text(strip=True)
                        if txt and len(txt) > 10 and txt not in target_list:
                            target_list.append(txt)
                    sibling = sibling.find_next_sibling()

        return tasks[:15], requirements[:15], benefits[:10]
