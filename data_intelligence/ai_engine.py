"""
AI Engine - Understands natural language data requirements.

This module parses user prompts like:
  - "Find me remote Python developer jobs posted in the last 7 days"
  - "Collect SaaS leads in fintech from Europe"
  - "Get me tech sponsorship opportunities for AI conferences"

It produces a structured intent object with:
  - data_type (job, lead, sponsor, market, repo, news, etc.)
  - entities (skills, locations, industries, time windows, counts)
  - filters
  - suggested sources (whitelisted)
  - workflow plan
"""

from __future__ import annotations
import re
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta


# ----------------------------------------------------------------------
# Domain knowledge
# ----------------------------------------------------------------------

DATA_TYPE_KEYWORDS = {
    "job": [
        "job", "jobs", "hiring", "position", "positions", "career", "careers",
        "opening", "openings", "vacancy", "vacancies", "role", "roles",
        "employment", "work", "recruit", "recruitment", "talented", "talent",
        # Hinglish / Hindi
        "naukri", "kaam", "karya", "rojgar",
    ],
    "lead": [
        "lead", "leads", "prospect", "prospects", "customer", "customers",
        "client", "clients", "buyer", "buyers", "decision maker", "b2b",
        "contact", "contacts", "outreach",
        # Hinglish
        "graahak", "grahak",
    ],
    "sponsor": [
        "sponsor", "sponsorship", "sponsors", "partnership", "partner",
        "backed by", "investor", "investors", "funding", "grant", "grants",
        "patron",
        # Hinglish
        "niveshak", "nivesh", "vittiya",
    ],
    "market": [
        "market", "market data", "price", "prices", "stock", "stocks",
        "trends", "forecast", "metrics", "analytics", "statistics", "stat",
        "stats", "kpi", "kpis", "revenue",
        # Hinglish
        "bazaar", "maan", "trends",
    ],
    "news": [
        "news", "article", "articles", "press release", "headlines",
        "coverage", "blog post", "blog", "stories", "report", "reports",
        # Hinglish
        "samachar", "khabar", "sootr",
    ],
    "repo": [
        "repository", "repositories", "repo", "github", "open source",
        "open-source", "library", "libraries", "framework", "package",
        # Hinglish
        "koda",
    ],
    "company": [
        "company", "companies", "startup", "startups", "firm", "firms",
        "organization", "organizations", "org", "enterprise",
        # Hinglish
        "kampani", "karyaalay",
    ],
}

INDUSTRY_KEYWORDS = {
    "fintech": ["fintech", "finance", "financial", "banking", "bank", "trading", "crypto", "defi", "payments"],
    "healthcare": ["healthcare", "health tech", "medical", "pharma", "biotech", "hospital", "clinical", "telemedicine"],
    "edtech": ["edtech", "education", "learning", "academic", "school", "university", "mooc"],
    "ai": ["ai startup", "ai company", "ai startups", "artificial intelligence", "machine learning", "llm", "deep learning", "genai"],
    "saas": ["saas", "software as a service", "b2b software", "cloud software"],
    "ecommerce": ["ecommerce", "e-commerce", "retail", "shopify", "marketplace"],
    "cybersecurity": ["cybersecurity", "security firm", "infosec", "cyber security"],
    "devtools": ["devtools", "developer tools", "ide", "cli tool"],
    "iot": ["iot", "internet of things", "embedded", "hardware", "robotics"],
    "media": ["media company", "entertainment", "gaming", "streaming", "video platform"],
}

LOCATION_KEYWORDS = {
    "remote": ["remote", "anywhere", "wfh", "work from home", "distributed"],
    "india": ["india", "indian", "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai", "pune", "kolkata", "bharat", "desi"],
    "usa": ["usa", "us", "united states", "america", "american", "new york", "san francisco", "sf", "seattle", "austin", "boston"],
    "europe": ["europe", "european", "eu", "uk", "united kingdom", "london", "berlin", "paris", "amsterdam", "munich"],
    "asia": ["asia", "asian", "singapore", "tokyo", "japan", "china", "hong kong", "seoul"],
    "global": ["global", "worldwide", "international"],
}

SKILL_KEYWORDS = [
    "python", "javascript", "typescript", "react", "node", "node.js", "java",
    "golang", "go", "rust", "c++", "c#", "ruby", "rails", "django", "flask",
    "fastapi", "vue", "angular", "next.js", "nextjs", "kotlin", "swift",
    "aws", "azure", "gcp", "kubernetes", "docker", "terraform", "ansible",
    "sql", "postgres", "postgresql", "mongodb", "redis", "kafka", "spark",
    "tensorflow", "pytorch", "scikit-learn", "pandas", "numpy",
    "figma", "design", "product", "marketing", "sales", "data scientist",
    "data engineer", "data analyst", "devops", "sre", "frontend", "backend",
    "fullstack", "full-stack", "mobile", "ios", "android",
]

SIZE_KEYWORDS = {
    "small": ["small", "early stage", "early-stage", "seed", "tiny", "startup"],
    "medium": ["medium", "mid-size", "midsize", "growth stage", "series a", "series b"],
    "large": ["large", "enterprise", "big", "fortune", "multinational"],
}

TIME_KEYWORDS = {
    "hour": 1, "hours": 1, "day": 24, "days": 24,
    "week": 24 * 7, "weeks": 24 * 7,
    "month": 24 * 30, "months": 24 * 30,
    "year": 24 * 365, "years": 24 * 365,
}

# ----------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------

@dataclass
class Intent:
    data_type: str = "job"  # job | lead | sponsor | market | news | repo | company
    entities: Dict[str, List[str]] = field(default_factory=dict)
    skills: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    industries: List[str] = field(default_factory=list)
    company_sizes: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    time_window_hours: Optional[int] = None
    max_results: int = 25
    freshness: str = "any"  # any | recent | today
    original_prompt: str = ""
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _normalize(text: str) -> str:
    return (text or "").lower().strip()


def _match_any(text: str, terms: List[str]) -> List[str]:
    """Match whole-word occurrences to avoid substring false positives like
    'startup' matching inside 'startups'."""
    found = []
    for t in terms:
        # Always use word boundaries for accurate whole-word matching.
        pattern = r"(?<!\w)" + re.escape(t) + r"(?!\w)"
        if re.search(pattern, text):
            found.append(t)
    return found


def _extract_time_window(text: str) -> Optional[int]:
    """Find phrases like 'last 7 days', 'past 2 weeks', 'in the last 24 hours'."""
    # Patterns: "last/past N unit", "in the last N units"
    pattern = r"\b(?:last|past|previous|recent|in the last|in the past)\s+(\d+)?\s*(hour|hours|day|days|week|weeks|month|months|year|years)\b"
    m = re.search(pattern, text)
    if m:
        n = int(m.group(1)) if m.group(1) else 1
        unit = m.group(2)
        return n * TIME_KEYWORDS.get(unit, 24)
    # Words like "today"
    if re.search(r"\btoday\b", text):
        return 24
    if re.search(r"\bthis week\b", text):
        return 24 * 7
    if re.search(r"\bthis month\b", text):
        return 24 * 30
    return None


def _extract_count(text: str) -> int:
    m = re.search(r"\b(?:top|at least|around|about|approx(?:imately)?|~)?\s*(\d{1,4})\s+(?:results|records|items|leads|jobs|sponsors|companies|posts|articles|repos|repositories)\b", text)
    if m:
        return min(int(m.group(1)), 200)
    m = re.search(r"\b(?:give me|fetch|get|collect|find|i need|i want)\s+(\d{1,4})\b", text)
    if m:
        return min(int(m.group(1)), 200)
    m = re.search(r"\b(?:top|first)\s+(\d{1,3})\b", text)
    if m:
        return min(int(m.group(1)), 200)
    return 25


def _detect_freshness(text: str) -> str:
    if re.search(r"\b(today|just now|latest|recently|this week|past 24 hours?|last 24 hours?)\b", text):
        return "recent"
    if re.search(r"\b(this month|past month|last month|past week|last week)\b", text):
        return "recent"
    return "any"


# ----------------------------------------------------------------------
# Main engine
# ----------------------------------------------------------------------

class AIEngine:
    """Parses user prompts into structured Intent objects."""

    def __init__(self) -> None:
        pass

    def parse(self, prompt: str) -> Intent:
        text = _normalize(prompt)
        intent = Intent(original_prompt=prompt)

        # 1. Data type detection (priority order matters - more specific first)
        scores: Dict[str, int] = {}
        for dtype, kws in DATA_TYPE_KEYWORDS.items():
            matches = _match_any(text, kws)
            scores[dtype] = len(matches)
        # Pick highest; default to "job"
        if scores:
            best = max(scores.items(), key=lambda kv: kv[1])
            if best[1] > 0:
                intent.data_type = best[0]
        # Map company -> lead if no clear job/sponsor/news match
        if intent.data_type == "company" and not _match_any(text, DATA_TYPE_KEYWORDS["company"]):
            intent.data_type = "lead"

        # 2. Locations
        for loc, kws in LOCATION_KEYWORDS.items():
            if _match_any(text, kws):
                intent.locations.append(loc)

        # 3. Industries
        for ind, kws in INDUSTRY_KEYWORDS.items():
            if _match_any(text, kws):
                intent.industries.append(ind)

        # 4. Company sizes
        for sz, kws in SIZE_KEYWORDS.items():
            if _match_any(text, kws):
                intent.company_sizes.append(sz)

        # 5. Skills
        for skill in SKILL_KEYWORDS:
            if re.search(r"\b" + re.escape(skill) + r"\b", text):
                intent.skills.append(skill)

        # 6. Time window + freshness
        intent.time_window_hours = _extract_time_window(text)
        intent.freshness = _detect_freshness(text)

        # 7. Result count
        intent.max_results = _extract_count(text)

        # 8. Generic keywords (nouns that survived filtering)
        intent.keywords = intent.skills + intent.industries

        # 9. Build human-readable summary
        intent.summary = self._summarize(intent)
        return intent

    @staticmethod
    def _summarize(intent: Intent) -> str:
        # Singular/plural handling
        plural = {
            "job": "jobs", "lead": "leads", "sponsor": "sponsors",
            "market": "market data points", "news": "news articles",
            "repo": "repositories", "company": "companies",
        }
        parts = [f"Collecting {plural.get(intent.data_type, intent.data_type + 's')}"]
        if intent.industries:
            parts.append("in " + ", ".join(intent.industries))
        if intent.locations:
            parts.append("from " + ", ".join(intent.locations))
        if intent.skills:
            parts.append("with skills: " + ", ".join(intent.skills[:5]))
        if intent.company_sizes:
            parts.append("size: " + ", ".join(intent.company_sizes))
        if intent.time_window_hours:
            days = round(intent.time_window_hours / 24, 1)
            parts.append(f"within last {days} day(s)")
        parts.append(f"(max {intent.max_results} results)")
        return " ".join(parts)


# ----------------------------------------------------------------------
# Convenience
# ----------------------------------------------------------------------

_engine: Optional[AIEngine] = None


def get_engine() -> AIEngine:
    global _engine
    if _engine is None:
        _engine = AIEngine()
    return _engine