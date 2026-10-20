"""Pipeline Manager for Career-Ops.

Parses, evaluates, generates, and synchronizes job applications in
career-ops/data/pipeline.md.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.career_ops.generator import ApplicationGenerator
from src.career_ops.jd_scraper import JobDescriptionScraper, ScrapedJob
from src.career_ops.matcher_scorer import MatchEvaluation, MatchScorer

logger = logging.getLogger("career_ops.pipeline")


class PipelineEntry(BaseModel):
    company: str
    role: str
    location: str
    source: str
    url: str
    date_added: str
    status: str
    match_score: str = "TBD"
    notes: str = ""


class PipelineManager:
    """Manages parsing, evaluation, and document generation for pipeline.md."""

    def __init__(
        self,
        pipeline_path: str | Path = "career-ops/data/pipeline.md",
        profile_path: str | Path = "career-ops/config/profile.yaml",
        cache_dir: str | Path = "career-ops/data/jobs",
        applications_dir: str | Path = "career-ops/data/applications",
    ):
        self.pipeline_path = Path(pipeline_path)
        self.scraper = JobDescriptionScraper(cache_dir=cache_dir)
        self.scorer = MatchScorer(profile_path=profile_path)
        self.generator = ApplicationGenerator(
            profile_path=profile_path, output_dir=applications_dir
        )
        self._ensure_pipeline_file()

    def _ensure_pipeline_file(self) -> None:
        self.pipeline_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.pipeline_path.exists():
            header = (
                "# Career-Ops Application Pipeline\n\n"
                "| Company | Role | Location | Source | URL | Date Added | Status | Match Score | Notes |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            )
            with open(self.pipeline_path, "w", encoding="utf-8") as f:
                f.write(header)

    def load_entries(self) -> List[PipelineEntry]:
        """Parse markdown table into list of PipelineEntry objects."""
        if not self.pipeline_path.exists():
            return []

        entries: List[PipelineEntry] = []
        with open(self.pipeline_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        table_started = False
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue

            if "Company" in stripped and "Role" in stripped:
                table_started = True
                continue
            if table_started and re.match(r"^\|(\s*:?-+:?\s*\|)+$", stripped):
                continue

            if table_started:
                parts = [p.strip() for p in stripped.split("|")[1:-1]]
                if len(parts) >= 7:
                    raw_url = parts[4]
                    url_match = re.search(r"\((https?://[^\)]+)\)", raw_url)
                    clean_url = url_match.group(1) if url_match else raw_url

                    entry = PipelineEntry(
                        company=parts[0],
                        role=parts[1],
                        location=parts[2],
                        source=parts[3],
                        url=clean_url,
                        date_added=parts[5],
                        status=parts[6],
                        match_score=parts[7] if len(parts) > 7 else "TBD",
                        notes=parts[8] if len(parts) > 8 else (parts[7] if len(parts) == 8 and "%" not in parts[7] else ""),
                    )
                    entries.append(entry)

        return entries

    def save_entries(self, entries: List[PipelineEntry]) -> None:
        """Write structured entries back to pipeline.md."""
        header = (
            "# Career-Ops Application Pipeline\n\n"
            "| Company | Role | Location | Source | URL | Date Added | Status | Match Score | Notes |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        )
        rows: List[str] = []
        for e in entries:
            clean_company = e.company.replace("|", "-")
            clean_role = e.role.replace("|", "-")
            clean_loc = e.location.replace("|", "-")
            url_display = f"[{e.source}]({e.url})" if not e.url.startswith("[") else e.url
            row = (
                f"| {clean_company} | {clean_role} | {clean_loc} | {e.source} | "
                f"{url_display} | {e.date_added} | {e.status} | {e.match_score} | {e.notes} |"
            )
            rows.append(row)

        content = header + "\n".join(rows) + "\n"
        with open(self.pipeline_path, "w", encoding="utf-8") as f:
            f.write(content)

    def evaluate_all(self, force: bool = False) -> List[tuple[PipelineEntry, MatchEvaluation]]:
        """Scrape and score all Queued positions."""
        entries = self.load_entries()
        results = []

        updated = False
        for entry in entries:
            if force or entry.status.lower() in ["queued", "notified"]:
                logger.info(f"Evaluating {entry.role} @ {entry.company}...")
                job = self.scraper.scrape(
                    url=entry.url,
                    title=entry.role,
                    company=entry.company,
                    location=entry.location,
                )
                evaluation = self.scorer.evaluate(job)

                entry.match_score = f"{evaluation.overall_score}% ({evaluation.classification.split(' ')[0]})"
                entry.status = "Evaluated"
                entry.notes = evaluation.summary
                results.append((entry, evaluation))
                updated = True

        if updated:
            self.save_entries(entries)

        return results

    def generate_all_applications(self, min_score: int = 0) -> List[Path]:
        """Generate tailored CV and cover letter for evaluated or queued positions."""
        entries = self.load_entries()
        generated_paths = []
        updated = False

        for entry in entries:
            score_val = 100
            score_match = re.search(r"(\d+)%", entry.match_score)
            if score_match:
                score_val = int(score_match.group(1))

            if score_val >= min_score and entry.status.lower() in ["evaluated", "queued"]:
                job = self.scraper.scrape(
                    url=entry.url,
                    title=entry.role,
                    company=entry.company,
                    location=entry.location,
                )
                evaluation = self.scorer.evaluate(job)
                app_path = self.generator.generate_application(job, evaluation)

                entry.status = "Drafted"
                rel_path = f"data/applications/{app_path.name}/anschreiben.html"
                entry.notes = f"[Bewerbung bereit]({rel_path}) | Score: {entry.match_score}"
                generated_paths.append(app_path)
                updated = True

        if updated:
            self.save_entries(entries)

        return generated_paths
