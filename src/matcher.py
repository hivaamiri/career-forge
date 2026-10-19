"""Heuristic Matcher for filtering job postings by role, technology, exclusions, and location."""

from __future__ import annotations

import re
from typing import List, Optional
from pydantic import BaseModel, Field

from src.config import MatcherConfig


class JobMatchResult(BaseModel):
    matched: bool
    matched_inclusions: List[str] = Field(default_factory=list)
    matched_exclusions: List[str] = Field(default_factory=list)
    matched_locations: List[str] = Field(default_factory=list)
    reason: str = ""


class JobMatcher:
    """Evaluates job titles, descriptions, and locations against inclusion/exclusion rules."""

    def __init__(self, config: Optional[MatcherConfig] = None):
        cfg = config or MatcherConfig()

        self.inclusion_patterns: List[re.Pattern] = [
            re.compile(p, re.IGNORECASE) for p in cfg.inclusion_patterns
        ]
        self.exclusion_patterns: List[re.Pattern] = [
            re.compile(p, re.IGNORECASE) for p in cfg.exclusion_patterns
        ]

        # Location regexes: match city names, Germany/Deutschland, or Remote
        self.location_patterns: List[re.Pattern] = []
        for loc in cfg.locations:
            clean = loc.strip()
            if clean:
                self.location_patterns.append(
                    re.compile(rf"\b{re.escape(clean)}\b", re.IGNORECASE)
                )

    def update_rules(
        self,
        inclusion_patterns: Optional[List[str]] = None,
        locations: Optional[List[str]] = None,
    ) -> None:
        """Update active matching rules dynamically at runtime."""
        if inclusion_patterns is not None:
            self.inclusion_patterns = [
                re.compile(p, re.IGNORECASE) for p in inclusion_patterns if p.strip()
            ]
        if locations is not None:
            self.location_patterns = [
                re.compile(rf"\b{re.escape(loc.strip())}\b", re.IGNORECASE)
                for loc in locations
                if loc.strip()
            ]

    def evaluate(
        self,
        title: str,
        location: Optional[str] = None,
        snippet: Optional[str] = None,
    ) -> JobMatchResult:
        """Evaluate a job posting candidate.

        1. Check exclusions on title & snippet: If matched -> REJECT.
        2. Check inclusions on title & snippet: Must match at least one inclusion -> if not -> REJECT.
        3. Check location if location filter is active and location is provided.
        """
        combined_text = f"{title} {snippet or ''}".strip()

        # 1. Check exclusions
        matched_exclusions: List[str] = []
        for pattern in self.exclusion_patterns:
            matches = pattern.findall(combined_text)
            if matches:
                matched_exclusions.extend(
                    [m if isinstance(m, str) else m[0] for m in matches]
                )

        if matched_exclusions:
            return JobMatchResult(
                matched=False,
                matched_exclusions=matched_exclusions,
                reason=f"Matched exclusion patterns: {', '.join(set(matched_exclusions))}",
            )

        # 2. Check inclusions
        matched_inclusions: List[str] = []
        for pattern in self.inclusion_patterns:
            matches = pattern.findall(combined_text)
            if matches:
                matched_inclusions.extend(
                    [m if isinstance(m, str) else m[0] for m in matches]
                )

        if not matched_inclusions:
            return JobMatchResult(
                matched=False,
                reason="No inclusion patterns matched the title or description",
            )

        # 3. Check locations (if locations are specified in config)
        matched_locations: List[str] = []
        loc_text = f"{location or ''} {combined_text}".strip()
        if self.location_patterns:
            for pattern in self.location_patterns:
                if pattern.search(loc_text):
                    matched_locations.append(pattern.pattern)

            # If location was explicitly provided and does not match any allowed location, reject
            if location and not matched_locations:
                return JobMatchResult(
                    matched=False,
                    matched_inclusions=matched_inclusions,
                    reason=f"Location '{location}' did not match allowed target locations",
                )

        return JobMatchResult(
            matched=True,
            matched_inclusions=list(set(matched_inclusions)),
            matched_locations=matched_locations,
            reason="Matched inclusion criteria without triggering exclusions",
        )
