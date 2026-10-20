"""Tailored German Application Generator (DIN 5008 Anschreiben & Lebenslauf).

Generates customized, professionally styled cover letters and CVs in both
Markdown and print-ready A4 HTML for direct PDF export.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from src.career_ops.jd_scraper import ScrapedJob
from src.career_ops.matcher_scorer import MatchEvaluation

logger = logging.getLogger("career_ops.generator")


def slugify(text: str) -> str:
    """Generate safe directory slug from company and title."""
    clean = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "_", clean)[:60]


class ApplicationGenerator:
    """Produces tailored German cover letters and resumes targeted to specific positions."""

    def __init__(
        self,
        profile_path: str | Path = "career-ops/config/profile.yaml",
        output_dir: str | Path = "career-ops/data/applications",
    ):
        self.profile_path = Path(profile_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.profile = self._load_profile()

    def _load_profile(self) -> Dict[str, Any]:
        if not self.profile_path.exists():
            example_path = self.profile_path.parent / "profile.example.yaml"
            if example_path.exists():
                with open(example_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            return {}
        with open(self.profile_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def generate_application(
        self,
        job: ScrapedJob,
        evaluation: Optional[MatchEvaluation] = None,
    ) -> Path:
        """Generate tailored Anschreiben and Lebenslauf files."""
        slug = f"{slugify(job.company)}_{slugify(job.title)}"
        app_dir = self.output_dir / slug
        app_dir.mkdir(parents=True, exist_ok=True)

        matched_str = ", ".join(evaluation.matched_skills[:5]) if evaluation and evaluation.matched_skills else "HPLC, Qualitätskontrolle, GMP"

        anschreiben_md = self._build_anschreiben_md(job, evaluation, matched_str)
        anschreiben_html = self._build_anschreiben_html(job, evaluation, matched_str)

        with open(app_dir / "anschreiben.md", "w", encoding="utf-8") as f:
            f.write(anschreiben_md)
        with open(app_dir / "anschreiben.html", "w", encoding="utf-8") as f:
            f.write(anschreiben_html)

        lebenslauf_md = self._build_lebenslauf_md(job, evaluation)
        lebenslauf_html = self._build_lebenslauf_html(job, evaluation)

        with open(app_dir / "lebenslauf.md", "w", encoding="utf-8") as f:
            f.write(lebenslauf_md)
        with open(app_dir / "lebenslauf.html", "w", encoding="utf-8") as f:
            f.write(lebenslauf_html)

        logger.info(f"Generated tailored application package in: {app_dir}")
        return app_dir

    def _build_anschreiben_md(
        self,
        job: ScrapedJob,
        evaluation: Optional[MatchEvaluation],
        matched_methods: str,
    ) -> str:
        p = self.profile.get("personal", {})
        pref = self.profile.get("preferences", {})
        today = datetime.now().strftime("%d.%m.%Y")
        city = p.get("location", "Berlin").split(",")[0].strip()

        return f"""# Anschreiben: {job.title} @ {job.company}

**Absender:**  
{p.get('name', 'Hiva Amiri')}  
{p.get('address', 'Musterstraße 12, 10115 Berlin')}  
E-Mail: {p.get('email', '')} | Tel: {p.get('phone', '')}  

---

**Empfänger:**  
{job.company}  
Personalabteilung  
{job.location or 'Deutschland'}  

**{city}, den {today}**

---

### **Bewerbung als {job.title}**
*(Referenz-ID: {job.id[:10]} | Quelle: {job.canonical_url})*

Sehr geehrte Damen und Herren,

mit großem Interesse habe ich Ihre Ausschreibung für die Position als **{job.title}** bei **{job.company}** zur Kenntnis genommen. Als qualifizierter Chemiker mit fundierter Praxis in instrumenteller Analytik, Methodenvalidierung und Qualitätskontrolle nach regulierten Standards (GMP/GLP) reizt mich die Aussicht, meine analytische Präzision und Laborerfahrung gewinnbringend in Ihr Team einzubringen.

In meiner bisherigen Tätigkeit lag mein Schwerpunkt insbesondere auf der Durchführung qualitätsrelevanter Prüfungen und instrumenteller Verfahren wie **{matched_methods}**. Dabei zeichnet mich eine strukturierte, eigenverantwortliche Arbeitsweise sowie ein hohes Qualitätsbewusstsein bei der normgerechten Dokumentation (LIMS) aus. Die von Ihnen genannten Anforderungen an zuverlässige Analysen, Gerätebetreuung und Methodenoptimierung decken sich ideal mit meinen praktischen Kernkompetenzen.

An einer Mitarbeit bei **{job.company}** begeistert mich vor allem das anspruchsvolle Tätigkeitsfeld und Ihr hoher Qualitätsanspruch. Ich freue mich darauf, mich rasch in Ihre spezifischen Laborprozesse einzuarbeiten und einen verlässlichen Beitrag zu Ihrem Unternehmenserfolg zu leisten.

Meine Gehaltsvorstellung liegt bei {pref.get('salary_expectation', 'ca. 65.000 € brutto p.a.')}. Für einen Einstieg stehe ich Ihnen {pref.get('availability', 'ab sofort')} zur Verfügung.

Über die Gelegenheit, mich Ihnen in einem persönlichen Gespräch vorzustellen, freue ich mich sehr.

Mit freundlichen Grüßen

**{p.get('name', 'Hiva Amiri')}**

---
*Anlagen: Lebenslauf, Zeugnisse, Qualifikationsprofil*
"""

    def _build_anschreiben_html(
        self,
        job: ScrapedJob,
        evaluation: Optional[MatchEvaluation],
        matched_methods: str,
    ) -> str:
        p = self.profile.get("personal", {})
        pref = self.profile.get("preferences", {})
        today = datetime.now().strftime("%d.%m.%Y")
        city = p.get("location", "Berlin").split(",")[0].strip()

        return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>Anschreiben - {p.get('name')} - {job.company}</title>
  <style>
    @page {{ size: A4; margin: 25mm 20mm 20mm 20mm; }}
    body {{
      font-family: 'Helvetica Neue', Arial, sans-serif;
      font-size: 11pt;
      line-height: 1.55;
      color: #222;
      margin: 0;
      padding: 0;
    }}
    .sender {{
      text-align: right;
      font-size: 9.5pt;
      color: #555;
      margin-bottom: 30px;
    }}
    .recipient {{
      font-size: 10.5pt;
      margin-bottom: 35px;
      line-height: 1.4;
    }}
    .date {{
      text-align: right;
      margin-bottom: 25px;
      font-size: 10pt;
      color: #444;
    }}
    .subject {{
      font-size: 13pt;
      font-weight: 700;
      color: #111;
      margin-bottom: 20px;
      border-bottom: 1.5px solid #005a9c;
      padding-bottom: 6px;
    }}
    .subject span {{
      font-size: 9.5pt;
      font-weight: normal;
      color: #666;
      display: block;
      margin-top: 3px;
    }}
    p {{
      margin-bottom: 14px;
      text-align: justify;
    }}
    .signature {{
      margin-top: 35px;
    }}
    .annex {{
      margin-top: 40px;
      font-size: 9pt;
      color: #777;
    }}
  </style>
</head>
<body>
  <div class="sender">
    <strong>{p.get('name', 'Hiva Amiri')}</strong><br>
    {p.get('address', 'Musterstraße 12, 10115 Berlin')}<br>
    Tel: {p.get('phone', '')} | E-Mail: {p.get('email', '')}
  </div>

  <div class="recipient">
    <strong>{job.company}</strong><br>
    Personalabteilung<br>
    {job.location or 'Deutschland'}
  </div>

  <div class="date">{city}, den {today}</div>

  <div class="subject">
    Bewerbung als {job.title}
    <span>Referenz-ID: {job.id[:10]} | Online-Ausschreibung: {job.canonical_url}</span>
  </div>

  <p>Sehr geehrte Damen und Herren,</p>

  <p>
    mit großem Interesse bewerbe ich mich auf die von Ihnen ausgeschriebene Position als <strong>{job.title}</strong> bei <strong>{job.company}</strong>. Als qualifizierter Chemiker mit fundierter Praxis in instrumenteller Analytik, Methodenvalidierung und Qualitätskontrolle nach regulierten Standards (GMP/GLP) reizt mich die Aussicht, meine analytische Präzision und Laborerfahrung gewinnbringend in Ihr Team einzubringen.
  </p>

  <p>
    In meiner bisherigen Laborpraxis lag mein Schwerpunkt insbesondere auf der Durchführung qualitätsrelevanter Prüfungen und instrumenteller Verfahren wie <strong>{matched_methods}</strong>. Dabei zeichnet mich eine strukturierte, eigenverantwortliche Arbeitsweise sowie ein hohes Qualitätsbewusstsein bei der normgerechten Dokumentation (LIMS) aus. Die von Ihnen genannten Anforderungen an zuverlässige Analysen, Gerätebetreuung und Methodenoptimierung decken sich ideal mit meinen praktischen Kernkompetenzen.
  </p>

  <p>
    An einer Mitarbeit bei <strong>{job.company}</strong> begeistert mich vor allem das anspruchsvolle Tätigkeitsfeld und Ihr hoher Qualitätsanspruch. Ich freue mich darauf, mich rasch in Ihre spezifischen Laborprozesse einzuarbeiten und einen verlässlichen Beitrag zu Ihrem Unternehmenserfolg zu leisten.
  </p>

  <p>
    Meine Gehaltsvorstellung liegt bei {pref.get('salary_expectation', 'ca. 65.000 € brutto p.a.')}. Für einen Einstieg stehe ich Ihnen {pref.get('availability', 'ab sofort')} zur Verfügung.
  </p>

  <p>Über die Gelegenheit, mich Ihnen in einem persönlichen Gespräch vorzustellen, freue ich mich sehr.</p>

  <div class="signature">
    Mit freundlichen Grüßen<br><br>
    <strong>{p.get('name', 'Hiva Amiri')}</strong>
  </div>

  <div class="annex">
    Anlagen: Lebenslauf, Zeugnisse, Qualifikationsübersicht
  </div>
</body>
</html>
"""

    def _build_lebenslauf_md(
        self,
        job: ScrapedJob,
        evaluation: Optional[MatchEvaluation],
    ) -> str:
        p = self.profile.get("personal", {})
        skills = self.profile.get("skills", {})
        experience = self.profile.get("experience", [])
        education = self.profile.get("education", [])

        methods = ", ".join(skills.get("analytical_methods", []))
        quality = ", ".join(skills.get("quality_and_regulations", []))
        software = ", ".join(skills.get("software", []))

        exp_md = ""
        for e in experience:
            tasks = "\n".join([f"  - {t}" for t in e.get("tasks", [])])
            exp_md += f"### {e.get('title')}  \n**{e.get('company')}**, {e.get('location')} ({e.get('period')})  \n{tasks}\n\n"

        edu_md = ""
        for ed in education:
            edu_md += f"### {ed.get('degree')}  \n**{ed.get('institution')}** ({ed.get('period')})  \n*{ed.get('focus', '')}*\n\n"

        return f"""# Lebenslauf: {p.get('name')}

**{p.get('title')}**  
{p.get('address')} | Tel: {p.get('phone')} | E-Mail: {p.get('email')}  
LinkedIn: [{p.get('linkedin')}]({p.get('linkedin')})  

---

## 🎯 Profil & Zielposition
Erfahrener Chemiker mit fundierter Expertise in analytischer Chemie, instrumenteller Analytik (HPLC, GC-MS, UV-Vis), Qualitätskontrolle (GMP/GLP) und Methodenvalidierung.

---

## 🔬 Kernkompetenzen & Methoden
* **Analytische Methoden:** {methods}
* **Qualitätsstandards:** {quality}
* **Labor-Software:** {software}

---

## 💼 Berufliche Erfahrung
{exp_md}
---

## 🎓 Ausbildung
{edu_md}
"""

    def _build_lebenslauf_html(
        self,
        job: ScrapedJob,
        evaluation: Optional[MatchEvaluation],
    ) -> str:
        p = self.profile.get("personal", {})
        skills = self.profile.get("skills", {})
        experience = self.profile.get("experience", [])
        education = self.profile.get("education", [])

        methods = ", ".join(skills.get("analytical_methods", []))
        quality = ", ".join(skills.get("quality_and_regulations", []))
        software = ", ".join(skills.get("software", []))

        exp_html = ""
        for e in experience:
            tasks_li = "".join([f"<li>{t}</li>" for t in e.get("tasks", [])])
            exp_html += f"""
            <div class="item">
              <div class="item-header">
                <strong>{e.get('title')}</strong>
                <span class="period">{e.get('period')}</span>
              </div>
              <div class="company">{e.get('company')} | {e.get('location')}</div>
              <ul>{tasks_li}</ul>
            </div>
            """

        edu_html = ""
        for ed in education:
            edu_html += f"""
            <div class="item">
              <div class="item-header">
                <strong>{ed.get('degree')}</strong>
                <span class="period">{ed.get('period')}</span>
              </div>
              <div class="company">{ed.get('institution')}</div>
              <p class="focus">{ed.get('focus', '')}</p>
            </div>
            """

        return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>Lebenslauf - {p.get('name')}</title>
  <style>
    @page {{ size: A4; margin: 18mm; }}
    body {{
      font-family: 'Helvetica Neue', Arial, sans-serif;
      font-size: 10pt;
      line-height: 1.5;
      color: #222;
      margin: 0;
      padding: 0;
    }}
    .header {{
      border-bottom: 2px solid #005a9c;
      padding-bottom: 12px;
      margin-bottom: 18px;
    }}
    .name {{
      font-size: 20pt;
      font-weight: 700;
      color: #005a9c;
      margin: 0 0 4px 0;
    }}
    .title {{
      font-size: 12pt;
      color: #555;
      margin: 0 0 8px 0;
    }}
    .contact {{
      font-size: 9pt;
      color: #666;
    }}
    h2 {{
      font-size: 12pt;
      color: #005a9c;
      border-bottom: 1px solid #ddd;
      padding-bottom: 4px;
      margin-top: 16px;
      margin-bottom: 10px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .skills-grid {{
      display: grid;
      grid-template-columns: 140px 1fr;
      row-gap: 6px;
      margin-bottom: 15px;
      font-size: 9.5pt;
    }}
    .skills-label {{
      font-weight: bold;
      color: #444;
    }}
    .item {{
      margin-bottom: 14px;
    }}
    .item-header {{
      display: flex;
      justify-content: space-between;
      font-size: 10.5pt;
    }}
    .company {{
      font-size: 9.5pt;
      color: #005a9c;
      font-weight: 500;
      margin-bottom: 4px;
    }}
    .period {{
      font-size: 9pt;
      color: #777;
    }}
    ul {{
      margin: 4px 0 0 18px;
      padding: 0;
    }}
    li {{
      margin-bottom: 3px;
    }}
    .focus {{
      font-size: 9pt;
      color: #555;
      margin: 2px 0 0 0;
      font-style: italic;
    }}
  </style>
</head>
<body>
  <div class="header">
    <h1 class="name">{p.get('name', 'Hiva Amiri')}</h1>
    <div class="title">{p.get('title', 'Chemiker')}</div>
    <div class="contact">
      {p.get('address')} | Tel: {p.get('phone')} | E-Mail: {p.get('email')}
    </div>
  </div>

  <h2>Kompetenzen & Methoden</h2>
  <div class="skills-grid">
    <div class="skills-label">Analytik:</div>
    <div>{methods}</div>
    <div class="skills-label">Standards:</div>
    <div>{quality}</div>
    <div class="skills-label">Software:</div>
    <div>{software}</div>
  </div>

  <h2>Berufliche Erfahrung</h2>
  {exp_html}

  <h2>Ausbildung</h2>
  {edu_html}
</body>
</html>
"""
