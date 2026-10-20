"""Match Scorer for evaluating Job Postings against the Candidate Profile."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml
from pydantic import BaseModel, Field

from src.career_ops.jd_scraper import ScrapedJob

logger = logging.getLogger("career_ops.scorer")


class MatchBreakdown(BaseModel):
    category: str
    matched_items: List[str] = Field(default_factory=list)
    missing_items: List[str] = Field(default_factory=list)
    weight: float = 1.0


class MatchEvaluation(BaseModel):
    job_id: str
    job_title: str
    company: str
    overall_score: int = Field(..., description="Calculated match percentage (0-100)")
    classification: str = Field(..., description="High Match | Moderate Match | Low Match")
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    breakdowns: List[MatchBreakdown] = Field(default_factory=list)
    summary: str = ""


DOMAIN_TAXONOMY = {
    "analytical_methods": [
        "HPLC", "UHPLC", "GC", "GC-MS", "LC-MS", "LC-MS/MS", "UV-Vis", "UV/VIS",
        "NMR", "FTIR", "IR-Spektroskopie", "Titration", "Karl-Fischer", "ICP-MS",
        "ICP-OES", "DC", "Dünnschichtchromatographie", "Rheologie", "Spektroskopie",
        "Photometrie", "Fasernanalytik", "REM", "Mikroskopie"
    ],
    "quality_and_regulations": [
        "GMP", "cGMP", "GLP", "GxP", "ISO 9001", "ISO 17025", "ISO 13485",
        "Methodenvalidierung", "Gerätequalifizierung", "SOP", "Prüfanweisung",
        "Qualitätskontrolle", "QC", "Qualitätssicherung", "QA", "REACH", "CLP",
        "Gefahrstoffverordnung", "Arbeitssicherheit"
    ],
    "laboratory_techniques": [
        "Probenvorbereitung", "Synthese", "Organische Synthese", "Aufreinigung",
        "Formulierung", "Stabilitätsprüfung", "Materialprüfung", "LIMS",
        "Laborpraxis", "Freigabeanalytik", "Wareneingangsprüfung", "In-Prozess-Kontrolle"
    ],
    "qualifications": [
        "Chemiker", "Chemikerin", "Chemielaborant", "Chemielaborantin",
        "CTA", "BTA", "Laborant", "Laborantin", "Biochemiker",
        "Master", "Bachelor", "Promotion", "Diplom"
    ],
    "languages": [
        "Deutsch", "Englisch"
    ]
}


class MatchScorer:
    """Evaluates candidate profile alignment against scraped job descriptions."""

    def __init__(self, profile_path: str | Path = "career-ops/config/profile.yaml"):
        self.profile_path = Path(profile_path)
        self.profile = self._load_profile()

    def _load_profile(self) -> Dict[str, Any]:
        """Load candidate profile from YAML."""
        if not self.profile_path.exists():
            example_path = self.profile_path.parent / "profile.example.yaml"
            if example_path.exists():
                with open(example_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            return {}

        with open(self.profile_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _get_profile_skill_set(self) -> Set[str]:
        """Aggregate all skills and keywords from candidate profile."""
        skills = set()
        skills_dict = self.profile.get("skills", {})
        for category, items in skills_dict.items():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str):
                        skills.add(item.strip().lower())
                    elif isinstance(item, dict) and "name" in item:
                        skills.add(item["name"].strip().lower())

        for exp in self.profile.get("experience", []):
            for t in exp.get("tasks", []):
                for word in re.findall(r"\b[A-Za-z0-9\-\/]{3,}\b", t):
                    skills.add(word.lower())

        return skills

    def evaluate(self, job: ScrapedJob) -> MatchEvaluation:
        """Score job against profile using taxonomy-guided keyword analysis."""
        combined_text = f"{job.title}\n{job.description}\n{' '.join(job.requirements)}\n{' '.join(job.tasks)}".lower()
        profile_skills = self._get_profile_skill_set()

        all_matched_skills: List[str] = []
        all_missing_skills: List[str] = []
        breakdowns: List[MatchBreakdown] = []

        total_weight = 0.0
        weighted_score_accum = 0.0

        weights = {
            "analytical_methods": 3.0,
            "quality_and_regulations": 2.5,
            "laboratory_techniques": 2.0,
            "qualifications": 2.0,
            "languages": 1.0,
        }

        for category, terms in DOMAIN_TAXONOMY.items():
            cat_weight = weights.get(category, 1.0)
            matched_in_cat = []
            missing_in_cat = []

            for term in terms:
                pattern = rf"\b{re.escape(term.lower())}\b"
                if re.search(pattern, combined_text):
                    has_skill = any(
                        term.lower() in ps or ps in term.lower()
                        for ps in profile_skills
                    )
                    if has_skill:
                        matched_in_cat.append(term)
                        all_matched_skills.append(term)
                    else:
                        missing_in_cat.append(term)
                        all_missing_skills.append(term)

            demand_count = len(matched_in_cat) + len(missing_in_cat)
            if demand_count > 0:
                cat_ratio = len(matched_in_cat) / demand_count
                weighted_score_accum += cat_ratio * cat_weight
                total_weight += cat_weight

            breakdowns.append(
                MatchBreakdown(
                    category=category,
                    matched_items=matched_in_cat,
                    missing_items=missing_in_cat,
                    weight=cat_weight,
                )
            )

        if total_weight > 0:
            raw_score = int(round((weighted_score_accum / total_weight) * 100))
        else:
            raw_score = 65

        score = max(10, min(98, raw_score))

        if score >= 75:
            classification = "High Match (Bewerbung empfohlen)"
        elif score >= 50:
            classification = "Moderate Match (Gute Passung mit Einarbeitung)"
        else:
            classification = "Low Match (Erhebliche Lücken)"

        summary = (
            f"Passungsquote: {score}%. Kernkompetenzen: "
            f"{', '.join(all_matched_skills[:6]) if all_matched_skills else 'Allgemeine Laborkenntnisse'}. "
            f"Offen: {', '.join(all_missing_skills[:4]) if all_missing_skills else 'Keine wesentlichen Lücken'}."
        )

        return MatchEvaluation(
            job_id=job.id,
            job_title=job.title,
            company=job.company,
            overall_score=score,
            classification=classification,
            matched_skills=list(dict.fromkeys(all_matched_skills)),
            missing_skills=list(dict.fromkeys(all_missing_skills)),
            breakdowns=breakdowns,
            summary=summary,
        )
