"""Career-Ops Bridge: Appends verified job postings into career-ops markdown pipeline."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from src.db import Database, JobRecord

logger = logging.getLogger(__name__)

DEFAULT_HEADER = (
    "| Company | Role | Location | Source | URL | Date Added | Status | Notes |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
)


def _sanitize_cell(text: Optional[str]) -> str:
    """Escape pipe characters and line breaks to prevent breaking markdown tables."""
    if not text:
        return "N/A"
    return str(text).replace("|", "\\|").replace("\n", " ").replace("\r", "").strip()


def append_job_to_pipeline_md(
    job: JobRecord,
    pipeline_path: str | Path,
    notes: str = "Discovered via JobPulse",
) -> Tuple[bool, str]:
    """Append a job posting into the target career-ops markdown pipeline table."""
    path = Path(pipeline_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Format new row
    company = _sanitize_cell(job.company)
    title = _sanitize_cell(job.title)
    location = _sanitize_cell(job.location or "Not specified")
    source = _sanitize_cell(job.source)
    url_link = f"[{source}]({job.canonical_url})"
    status = "Queued"
    safe_notes = _sanitize_cell(notes)

    new_row = f"| {company} | {title} | {location} | {source} | {url_link} | {today} | {status} | {safe_notes} |\n"

    # Check existing file content
    if path.exists():
        content = path.read_text(encoding="utf-8")
        # Check if URL already in markdown table
        if job.canonical_url in content:
            return False, f"Job URL already exists in '{path}'"

        # Ensure table header exists if file was empty or missing headers
        if "| Company |" not in content:
            content = content.rstrip() + "\n\n" + DEFAULT_HEADER

        if not content.endswith("\n"):
            content += "\n"

        content += new_row
        path.write_text(content, encoding="utf-8")
    else:
        # Create new markdown pipeline document
        content = f"# Career-Ops Application Pipeline\n\n{DEFAULT_HEADER}{new_row}"
        path.write_text(content, encoding="utf-8")

    logger.info(f"Successfully appended '{job.title}' @ '{job.company}' into '{path}'")
    return True, f"Appended '{job.title}' to {path}"


def queue_job_to_careerops(
    job_id: str,
    db: Database,
    pipeline_path: str | Path = "career-ops/data/pipeline.md",
) -> Tuple[bool, str]:
    """Retrieve job by ID from SQLite, append to pipeline.md, and update database status."""
    job = db.get_job(job_id)
    if not job:
        return False, f"Job ID '{job_id}' not found in database."

    success, msg = append_job_to_pipeline_md(job, pipeline_path=pipeline_path)
    if success:
        db.update_status(job_id, "queued_career_ops")
        return True, msg
    else:
        # If already in file, update status anyway
        db.update_status(job_id, "queued_career_ops")
        return False, msg
