"""Candidate Profile Manager & CV Document Ingestion for Career-Ops.

Allows viewing, editing, and ingesting CV documents (PDF, Markdown, Text)
and cover letter templates directly from Telegram or CLI.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

logger = logging.getLogger("career_ops.profile")

DEFAULT_PROFILE_PATH = Path("career-ops/config/profile.yaml")
TEMPLATE_PATH = Path("career-ops/config/anschreiben_template.md")

# Known chemical, analytical, and laboratory skills to extract automatically
KNOWN_TAXONOMY_TERMS = [
    "HPLC", "UHPLC", "GC", "GC-MS", "LC-MS", "LC-MS/MS", "UV-Vis", "UV/VIS",
    "NMR", "FTIR", "IR-Spektroskopie", "Titration", "Karl-Fischer", "ICP-MS",
    "ICP-OES", "DC", "Dünnschichtchromatographie", "Rheologie", "Spektroskopie",
    "Photometrie", "Faseranalytik", "REM", "Mikroskopie", "Probenvorbereitung",
    "Synthese", "Organische Synthese", "Aufreinigung", "Formulierung",
    "Stabilitätsprüfung", "Materialprüfung", "LIMS", "Empower", "ChemStation",
    "GMP", "cGMP", "GLP", "GxP", "ISO 9001", "ISO 17025", "ISO 13485",
    "Methodenvalidierung", "Gerätequalifizierung", "SOP", "Prüfanweisung",
    "Qualitätskontrolle", "QC", "Qualitätssicherung", "QA", "REACH", "CLP",
    "Gefahrstoffverordnung", "Arbeitssicherheit", "Chemielaborant", "CTA", "BTA",
    "Chemiker", "Biochemiker"
]


class ProfileManager:
    """Manages reading, modifying, and auto-ingesting candidate CVs and preferences."""

    def __init__(self, profile_path: str | Path = DEFAULT_PROFILE_PATH):
        self.profile_path = Path(profile_path)
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_profile_exists()

    def _ensure_profile_exists(self) -> None:
        if not self.profile_path.exists():
            example_path = self.profile_path.parent / "profile.example.yaml"
            if example_path.exists():
                content = example_path.read_text(encoding="utf-8")
            else:
                content = (
                    "personal:\n"
                    "  name: 'Candidate'\n"
                    "  title: 'Chemiker'\n"
                    "  email: ''\n"
                    "  phone: ''\n"
                    "  location: 'Deutschland'\n"
                    "skills:\n"
                    "  analytical_methods: []\n"
                    "  quality_and_regulations: []\n"
                    "experience: []\n"
                    "education: []\n"
                    "preferences:\n"
                    "  salary_expectation: 'nach Vereinbarung'\n"
                    "  availability: 'ab sofort'\n"
                )
            self.profile_path.write_text(content, encoding="utf-8")

    def load_profile(self) -> Dict[str, Any]:
        """Load current profile dict from YAML."""
        try:
            with open(self.profile_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load profile: {e}")
            return {}

    def save_profile(self, data: Dict[str, Any]) -> None:
        """Persist profile dict back to YAML."""
        with open(self.profile_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    def update_field(self, section: str, key: str, value: Any) -> None:
        """Update a specific field in the profile (e.g. section='personal', key='name')."""
        data = self.load_profile()
        if section not in data or not isinstance(data[section], dict):
            data[section] = {}
        data[section][key] = value
        self.save_profile(data)

    def add_skills(self, skills: List[str], category: str = "analytical_methods") -> List[str]:
        """Add unique skills to a specified category."""
        data = self.load_profile()
        if "skills" not in data or not isinstance(data["skills"], dict):
            data["skills"] = {}
        if category not in data["skills"] or not isinstance(data["skills"][category], list):
            data["skills"][category] = []

        existing = {s.strip().lower() for s in data["skills"][category] if isinstance(s, str)}
        added = []
        for s in skills:
            clean = s.strip()
            if clean and clean.lower() not in existing:
                data["skills"][category].append(clean)
                existing.add(clean.lower())
                added.append(clean)

        self.save_profile(data)
        return added

    def set_skills(self, skills: List[str], category: str = "analytical_methods") -> None:
        """Overwrite skills in a category."""
        data = self.load_profile()
        if "skills" not in data or not isinstance(data["skills"], dict):
            data["skills"] = {}
        data["skills"][category] = [s.strip() for s in skills if s.strip()]
        self.save_profile(data)

    def extract_text_from_file(self, file_path: Path | str) -> str:
        """Extract plain text from PDF, Markdown, or text files."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(str(path))
                text_parts = []
                for idx, page in enumerate(reader.pages):
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
                return "\n".join(text_parts)
            except Exception as e:
                logger.error(f"Error extracting PDF text: {e}")
                raise ValueError(f"Could not extract text from PDF: {e}")

        # Plain text, markdown, yaml, etc.
        return path.read_text(encoding="utf-8", errors="replace")

    def ingest_cv_text(self, text: str, source_filename: Optional[str] = None) -> Dict[str, Any]:
        """Parse raw CV text and merge extracted facts into profile.yaml."""
        data = self.load_profile()
        changes: Dict[str, Any] = {}

        # 1. Extract Email
        email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", text)
        if email_match:
            email = email_match.group(0)
            data.setdefault("personal", {})["email"] = email
            changes["email"] = email

        # 2. Extract Phone
        phone_match = re.search(r"(?:\+49|0049|0)[0-9\s\-\/\(\)]{7,20}", text)
        if phone_match:
            phone = phone_match.group(0).strip()
            data.setdefault("personal", {})["phone"] = phone
            changes["phone"] = phone

        # 3. Extract Name (check first 5 lines for candidate name)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines[:5]:
            # Look for 2-3 capitalized words, avoiding common heading words like "Lebenslauf"
            if re.match(r"^[A-ZÄÖÜ][a-zäöüß]+\s+[A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?$", line):
                if not any(w in line.lower() for w in ["lebenslauf", "curriculum", "resume", "profil", "bewerbung"]):
                    data.setdefault("personal", {})["name"] = line
                    changes["name"] = line
                    break

        # 4. Extract Location / German PLZ & City
        city_match = re.search(r"\b(?:D-)?\d{5}\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)\b", text)
        if city_match:
            city = city_match.group(1).strip()
            data.setdefault("personal", {})["location"] = f"{city}, Deutschland"
            changes["location"] = f"{city}, Deutschland"
        elif any(c in text for c in ["Berlin", "München", "Frankfurt", "Hamburg", "Köln", "Stuttgart"]):
            for c in ["Berlin", "München", "Frankfurt", "Hamburg", "Köln", "Stuttgart"]:
                if c in text:
                    data.setdefault("personal", {})["location"] = f"{c}, Deutschland"
                    changes["location"] = f"{c}, Deutschland"
                    break

        # 5. Extract Skills from domain taxonomy
        text_lower = text.lower()
        extracted_methods = []
        extracted_quality = []
        for term in KNOWN_TAXONOMY_TERMS:
            pattern = rf"\b{re.escape(term.lower())}\b"
            if re.search(pattern, text_lower):
                if term in ["GMP", "GLP", "GxP", "ISO 9001", "ISO 17025", "SOP", "Methodenvalidierung", "Qualitätskontrolle", "REACH"]:
                    extracted_quality.append(term)
                else:
                    extracted_methods.append(term)

        if extracted_methods:
            cur_methods = set(data.setdefault("skills", {}).setdefault("analytical_methods", []))
            for m in extracted_methods:
                cur_methods.add(m)
            data["skills"]["analytical_methods"] = list(cur_methods)
            changes["analytical_methods"] = extracted_methods

        if extracted_quality:
            cur_quality = set(data.setdefault("skills", {}).setdefault("quality_and_regulations", []))
            for q in extracted_quality:
                cur_quality.add(q)
            data["skills"]["quality_and_regulations"] = list(cur_quality)
            changes["quality_and_regulations"] = extracted_quality

        # 6. Save raw copy as reference
        source_dir = self.profile_path.parent
        source_file = source_dir / (source_filename or "uploaded_cv.txt")
        source_file.write_text(text, encoding="utf-8")

        # Save profile
        self.save_profile(data)
        logger.info(f"Ingested CV text. Extracted changes: {list(changes.keys())}")
        return changes

    def save_template(self, template_text: str) -> None:
        """Save custom cover letter template."""
        TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TEMPLATE_PATH.write_text(template_text.strip(), encoding="utf-8")

    def format_summary(self) -> str:
        """Return human-readable summary of profile for Telegram display."""
        p = self.load_profile()
        personal = p.get("personal", {})
        skills = p.get("skills", {})
        pref = p.get("preferences", {})

        methods = ", ".join(skills.get("analytical_methods", [])[:8]) or "Keine hinterlegt"
        quality = ", ".join(skills.get("quality_and_regulations", [])[:5]) or "Keine hinterlegt"

        return (
            "👤 <b>Career-Ops Candidate Profile</b>\n\n"
            f"<b>Name:</b> {personal.get('name', 'Nicht angegeben')}\n"
            f"<b>Titel:</b> {personal.get('title', 'Nicht angegeben')}\n"
            f"<b>E-Mail:</b> {personal.get('email', 'Nicht angegeben')}\n"
            f"<b>Telefon:</b> {personal.get('phone', 'Nicht angegeben')}\n"
            f"<b>Standort:</b> {personal.get('location', 'Nicht angegeben')}\n\n"
            f"🔬 <b>Analytische Methoden:</b>\n{methods}\n\n"
            f"📋 <b>Qualitätsstandards:</b>\n{quality}\n\n"
            f"💰 <b>Gehaltserwartung:</b> {pref.get('salary_expectation', 'nach Vereinbarung')}\n"
            f"⏱ <b>Verfügbarkeit:</b> {pref.get('availability', 'ab sofort')}\n\n"
            "💡 <i>Tipp: Sende eine PDF/Text-Datei deines Lebenslaufs oder nutze /set_name, /set_title, /add_skill, /set_salary um Details anzupassen!</i>"
        )
