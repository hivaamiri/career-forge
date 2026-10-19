"""SQLite state store and deduplication layer for Job Pulse."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from pydantic import BaseModel, Field


class JobRecord(BaseModel):
    id: str = Field(..., description="SHA-256 hash of canonical_url")
    source: str
    title: str
    company: str
    location: Optional[str] = None
    url: str
    canonical_url: str
    discovered_at: Optional[str] = None
    status: str = "notified"
    meta: Dict[str, Any] = Field(default_factory=dict)


def compute_job_id(canonical_url: str) -> str:
    """Compute deterministic SHA-256 hash from a canonical URL."""
    clean_url = canonical_url.strip().lower()
    return hashlib.sha256(clean_url.encode("utf-8")).hexdigest()


class Database:
    """Thread-safe SQLite database manager for job persistence and deduplication."""

    def __init__(self, db_path: str | Path = "data/jobs.sqlite"):
        self.db_path = Path(db_path)
        self._ensure_parent_dir()
        self.init_schema()

    def _ensure_parent_dir(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
        )
        conn.row_factory = sqlite3.Row
        try:
            # Enable WAL mode for high concurrency and performance
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Initialize tables and indexes if they do not already exist."""
        with self.get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT,
                    url TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'notified',
                    meta_json TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_canonical ON jobs(canonical_url);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def is_seen(self, job_id_or_canonical_url: str) -> bool:
        """Check if a job has already been discovered, either by SHA-256 ID or canonical URL."""
        target = job_id_or_canonical_url.strip()
        # If passed a canonical URL rather than hash, compute hash
        if target.startswith("http://") or target.startswith("https://"):
            job_id = compute_job_id(target)
        else:
            job_id = target

        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM jobs WHERE id = ? LIMIT 1;", (job_id,)
            )
            return cursor.fetchone() is not None

    def save_job(
        self,
        source: str,
        title: str,
        company: str,
        url: str,
        canonical_url: str,
        location: Optional[str] = None,
        status: str = "notified",
        meta: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, bool]:
        """Save a new job posting if not seen before.

        Returns:
            tuple[job_id, was_inserted]: The job ID hash and True if newly inserted, False if already existed.
        """
        job_id = compute_job_id(canonical_url)
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO jobs (
                    id, source, title, company, location, url, canonical_url,
                    discovered_at, status, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    job_id,
                    source,
                    title.strip(),
                    company.strip(),
                    location.strip() if location else None,
                    url.strip(),
                    canonical_url.strip(),
                    now_utc,
                    status,
                    meta_json,
                ),
            )
            inserted = cursor.rowcount > 0

        return job_id, inserted

    def update_status(self, job_id: str, new_status: str) -> bool:
        """Update job lifecycle status (supports full ID or prefix)."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET status = ? WHERE id = ? OR id LIKE ? || '%';",
                (new_status, job_id, job_id),
            )
            return cursor.rowcount > 0

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Fetch a single job record by full ID or prefix."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, source, title, company, location, url, canonical_url,
                       discovered_at, status, meta_json
                FROM jobs WHERE id = ? OR id LIKE ? || '%' LIMIT 1;
                """,
                (job_id, job_id),
            )
            row = cursor.fetchone()
            if not row:
                return None

            meta_data = {}
            if row["meta_json"]:
                try:
                    meta_data = json.loads(row["meta_json"])
                except Exception:
                    meta_data = {}

            return JobRecord(
                id=row["id"],
                source=row["source"],
                title=row["title"],
                company=row["company"],
                location=row["location"],
                url=row["url"],
                canonical_url=row["canonical_url"],
                discovered_at=row["discovered_at"],
                status=row["status"],
                meta=meta_data,
            )

    def list_jobs(
        self, limit: int = 50, status: Optional[str] = None
    ) -> List[JobRecord]:
        """List recent jobs with optional status filtering."""
        with self.get_connection() as conn:
            if status:
                cursor = conn.execute(
                    """
                    SELECT id, source, title, company, location, url, canonical_url,
                           discovered_at, status, meta_json
                    FROM jobs WHERE status = ?
                    ORDER BY discovered_at DESC LIMIT ?;
                    """,
                    (status, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT id, source, title, company, location, url, canonical_url,
                           discovered_at, status, meta_json
                    FROM jobs ORDER BY discovered_at DESC LIMIT ?;
                    """,
                    (limit,),
                )

            records: List[JobRecord] = []
            for row in cursor.fetchall():
                meta_data = {}
                if row["meta_json"]:
                    try:
                        meta_data = json.loads(row["meta_json"])
                    except Exception:
                        meta_data = {}

                records.append(
                    JobRecord(
                        id=row["id"],
                        source=row["source"],
                        title=row["title"],
                        company=row["company"],
                        location=row["location"],
                        url=row["url"],
                        canonical_url=row["canonical_url"],
                        discovered_at=row["discovered_at"],
                        status=row["status"],
                        meta=meta_data,
                    )
                )
            return records

    def set_setting(self, key: str, value: Any) -> None:
        """Persist or update dynamic setting in SQLite."""
        val_json = json.dumps(value, ensure_ascii=False)
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (key, val_json),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Fetch setting by key from SQLite, falling back to default."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT value_json FROM settings WHERE key = ? LIMIT 1;", (key,)
            )
            row = cursor.fetchone()
            if not row or row["value_json"] is None:
                return default
            try:
                return json.loads(row["value_json"])
            except Exception:
                return default

    def delete_setting(self, key: str) -> bool:
        """Delete setting override from SQLite."""
        with self.get_connection() as conn:
            cursor = conn.execute("DELETE FROM settings WHERE key = ?;", (key,))
            return cursor.rowcount > 0

    def list_settings(self) -> Dict[str, Any]:
        """List all active setting overrides."""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT key, value_json FROM settings;")
            results: Dict[str, Any] = {}
            for row in cursor.fetchall():
                try:
                    results[row["key"]] = json.loads(row["value_json"])
                except Exception:
                    results[row["key"]] = row["value_json"]
            return results
