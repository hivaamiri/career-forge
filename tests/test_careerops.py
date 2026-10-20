"""Unit tests for Career-Ops Engine (Scraper, Scorer, Generator, PipelineManager)."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.career_ops.generator import ApplicationGenerator
from src.career_ops.jd_scraper import JobDescriptionScraper, ScrapedJob
from src.career_ops.matcher_scorer import MatchScorer
from src.career_ops.pipeline_manager import PipelineEntry, PipelineManager


def test_jd_scraper_caching():
    with tempfile.TemporaryDirectory() as tmp_dir:
        scraper = JobDescriptionScraper(cache_dir=tmp_dir)

        sample_job = ScrapedJob(
            id="test123hash",
            title="Chemielaborant QC",
            company="PharmaLab GmbH",
            location="Berlin",
            url="https://example.com/job/123",
            canonical_url="https://example.com/job/123",
            description="Aufgaben: Durchführung von HPLC und GC Analysen nach GMP.\nAnforderungen: Ausbildung als Chemielaborant oder CTA.",
            tasks=["Durchführung von HPLC und GC Analysen nach GMP"],
            requirements=["Ausbildung als Chemielaborant oder CTA"],
        )

        scraper.save_cache(sample_job)

        # Retrieve from cache
        cached = scraper.get_cached("test123hash")
        assert cached is not None
        assert cached.title == "Chemielaborant QC"
        assert cached.company == "PharmaLab GmbH"
        assert "HPLC" in cached.description

        # Check markdown file was also generated
        md_file = Path(tmp_dir) / "test123hash.md"
        assert md_file.exists()
        assert "Chemielaborant QC" in md_file.read_text(encoding="utf-8")


def test_matcher_scorer():
    with tempfile.TemporaryDirectory() as tmp_dir:
        profile_path = Path(tmp_dir) / "profile.yaml"
        profile_content = """
personal:
  name: "Dr. Max Mustermann"
skills:
  analytical_methods:
    - "HPLC"
    - "GC-MS"
    - "Titration"
  quality_and_regulations:
    - "GMP"
    - "GLP"
    - "SOP"
  qualifications:
    - "Chemiker"
experience:
  - tasks:
      - "Methodenvalidierung von HPLC Systemen."
"""
        profile_path.write_text(profile_content, encoding="utf-8")

        scorer = MatchScorer(profile_path=profile_path)

        # High match job
        job_high = ScrapedJob(
            id="job1",
            title="Analytischer Chemiker (HPLC / GC-MS)",
            company="Eurofins",
            url="https://example.com/1",
            canonical_url="https://example.com/1",
            description="Wir suchen einen Chemiker für HPLC und GC-MS Prüfungen unter GMP Richtlinien. SOP Erstellung.",
        )
        eval_high = scorer.evaluate(job_high)
        assert eval_high.overall_score >= 70
        assert "HPLC" in eval_high.matched_skills
        assert "GMP" in eval_high.matched_skills
        assert "High Match" in eval_high.classification

        # Low match job
        job_low = ScrapedJob(
            id="job2",
            title="Bauleiter Tiefbau",
            company="Bau AG",
            url="https://example.com/2",
            canonical_url="https://example.com/2",
            description="Koordination von Erdarbeiten und Tiefbauprojekten auf Baustellen.",
        )
        eval_low = scorer.evaluate(job_low)
        assert eval_low.overall_score < 70


def test_application_generator():
    with tempfile.TemporaryDirectory() as tmp_dir:
        profile_path = Path(tmp_dir) / "profile.yaml"
        profile_content = """
personal:
  name: "Hiva Amiri"
  address: "Musterstraße 12, Berlin"
  email: "hiva@example.com"
  phone: "+49 170 123456"
  location: "Berlin"
  title: "Chemiker"
preferences:
  salary_expectation: "ca. 65.000 €"
  availability: "ab sofort"
skills:
  analytical_methods: ["HPLC", "GC"]
  quality_and_regulations: ["GMP"]
experience:
  - title: "Chemiker"
    company: "Labor AG"
    period: "2023 - Heute"
    tasks: ["HPLC Analytik"]
education:
  - degree: "M.Sc. Chemie"
    institution: "TU Berlin"
"""
        profile_path.write_text(profile_content, encoding="utf-8")
        out_dir = Path(tmp_dir) / "apps"

        generator = ApplicationGenerator(profile_path=profile_path, output_dir=out_dir)

        job = ScrapedJob(
            id="job100",
            title="Analytiker Qualitätskontrolle",
            company="BioChem Solutions",
            url="https://example.com/job100",
            canonical_url="https://example.com/job100",
            description="HPLC und GMP",
        )

        app_dir = generator.generate_application(job)
        assert app_dir.exists()

        # Check generated files
        anschreiben_html = app_dir / "anschreiben.html"
        lebenslauf_html = app_dir / "lebenslauf.html"
        assert anschreiben_html.exists()
        assert lebenslauf_html.exists()

        html_text = anschreiben_html.read_text(encoding="utf-8")
        assert "Bewerbung als Analytiker Qualitätskontrolle" in html_text
        assert "BioChem Solutions" in html_text
        assert "Hiva Amiri" in html_text


def test_pipeline_manager_flow():
    with tempfile.TemporaryDirectory() as tmp_dir:
        pipeline_path = Path(tmp_dir) / "pipeline.md"
        profile_path = Path(tmp_dir) / "profile.yaml"
        cache_dir = Path(tmp_dir) / "jobs"
        apps_dir = Path(tmp_dir) / "apps"

        # Create sample profile
        profile_path.write_text(
            """
personal:
  name: "Hiva Amiri"
skills:
  analytical_methods: ["HPLC", "GC-MS"]
  quality_and_regulations: ["GMP"]
""",
            encoding="utf-8",
        )

        manager = PipelineManager(
            pipeline_path=pipeline_path,
            profile_path=profile_path,
            cache_dir=cache_dir,
            applications_dir=apps_dir,
        )

        # Initial table check
        entries = manager.load_entries()
        assert len(entries) == 0

        # Add mock entry
        entries.append(
            PipelineEntry(
                company="Bayer AG",
                role="Chemielaborant Analytik",
                location="Berlin",
                source="arbeitsagentur",
                url="https://example.com/bayer-job",
                date_added="2026-10-20",
                status="Queued",
                notes="Discovered via JobPulse",
            )
        )
        manager.save_entries(entries)

        loaded = manager.load_entries()
        assert len(loaded) == 1
        assert loaded[0].company == "Bayer AG"

        # Mock scraper to avoid real HTTP in test
        mock_scraped = ScrapedJob(
            id="bayer123",
            title="Chemielaborant Analytik",
            company="Bayer AG",
            url="https://example.com/bayer-job",
            canonical_url="https://example.com/bayer-job",
            description="HPLC Qualitätskontrolle nach GMP Richtlinien.",
        )
        with patch.object(manager.scraper, "scrape", return_value=mock_scraped):
            evals = manager.evaluate_all()
            assert len(evals) == 1
            entry, eval_res = evals[0]
            assert "High" in entry.match_score or "Moderate" in entry.match_score
            assert entry.status == "Evaluated"

            # Test application generation
            app_paths = manager.generate_all_applications()
            assert len(app_paths) == 1
            updated_entries = manager.load_entries()
            assert updated_entries[0].status == "Drafted"
