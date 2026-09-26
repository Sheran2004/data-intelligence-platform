"""
AI Summarizer - Generates a natural-language summary of a run's records.

This isn't a full LLM call (no external dependency), but uses statistical
analysis on the records + intent to produce a useful narrative summary.
"""

from __future__ import annotations
import re
from collections import Counter
from typing import Dict, Any, List, Optional
from datetime import datetime


def summarize_run(run_meta: Dict[str, Any], records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a summary dict with narrative + computed insights."""
    intent = run_meta.get("intent") or {}
    total = len(records)
    if total == 0:
        return {
            "narrative": "No records were collected. Try a different prompt or check source availability.",
            "insights": [],
            "patterns": [],
            "highlights": [],
        }

    data_type = intent.get("data_type", "data")

    # Source distribution
    source_counts: Counter = Counter(r.get("source") for r in records)
    primary_source = source_counts.most_common(1)[0]

    # Score stats
    scores = [r.get("score") or 0 for r in records]
    avg_score = round(sum(scores) / len(scores), 1)
    top_score = max(scores)
    high_quality = sum(1 for s in scores if s >= 70)

    # Skills / industries distribution
    all_skills: List[str] = []
    all_industries: List[str] = []
    locations: List[str] = []
    companies: List[str] = []
    for r in records:
        all_skills.extend(r.get("skills") or [])
        all_industries.extend(r.get("industries") or [])
        if r.get("location"):
            locations.append(r["location"])
        if r.get("company"):
            companies.append(r["company"])

    skill_freq = Counter(all_skills).most_common(5)
    industry_freq = Counter(all_industries).most_common(3)
    location_freq = Counter(locations).most_common(3)

    # Freshness
    recent = 0
    for r in records:
        pub = r.get("published_at")
        if pub:
            try:
                d = datetime.fromisoformat(pub.replace("Z", "+00:00")).replace(tzinfo=None)
                if (datetime.utcnow() - d).days <= 7:
                    recent += 1
            except Exception:
                pass

    # Has-URL ratio (source-backed)
    with_url = sum(1 for r in records if r.get("url"))

    # ---- Build narrative ----
    plural = {
        "job": "jobs", "lead": "leads", "sponsor": "sponsors",
        "market": "market data points", "news": "news items",
        "repo": "repositories", "company": "companies",
    }.get(data_type, "records")

    narrative_parts = [
        f"Collected <strong>{total} {plural}</strong>",
    ]
    if intent.get("skills"):
        narrative_parts.append(f"focused on <strong>{', '.join(intent['skills'][:3])}</strong>")
    if intent.get("industries"):
        narrative_parts.append(f"in <strong>{', '.join(intent['industries'])}</strong>")
    if intent.get("locations"):
        narrative_parts.append(f"from <strong>{', '.join(intent['locations'])}</strong>")

    narrative = " ".join(narrative_parts) + "."
    narrative += f" The collection drew from <strong>{len(source_counts)}</strong> source(s); <strong>{primary_source[0]}</strong> contributed the most records ({primary_source[1]})."
    narrative += f" Average relevance score: <strong>{avg_score}</strong>; <strong>{high_quality}</strong> record(s) scored above 70."

    if recent:
        narrative += f" <strong>{recent}</strong> record(s) are from the past 7 days."
    if with_url:
        narrative += f" <strong>{with_url}</strong> record(s) are source-backed with a verifiable URL."

    if skill_freq:
        skill_str = ", ".join(s for s, _ in skill_freq[:3])
        narrative += f" Top skills mentioned: <strong>{skill_str}</strong>."

    # ---- Patterns ----
    patterns: List[str] = []
    if industry_freq:
        top_ind = industry_freq[0]
        patterns.append(f"{top_ind[0].title()} is the dominant industry ({top_ind[1]} mentions)")
    if location_freq:
        top_loc = location_freq[0]
        patterns.append(f"{top_loc[0].title()} appears in {top_loc[1]} record(s)")
    if with_url / total >= 0.8:
        patterns.append(f"Excellent source coverage ({int(with_url/total*100)}% of records have URLs)")

    # ---- Highlights (top 3 records) ----
    highlights: List[Dict[str, Any]] = []
    sorted_records = sorted(records, key=lambda r: r.get("score") or 0, reverse=True)[:3]
    for r in sorted_records:
        highlights.append({
            "title": r.get("title"),
            "score": r.get("score"),
            "source": r.get("source"),
            "company": r.get("company"),
            "url": r.get("url"),
        })

    # ---- Insights ----
    insights = [
        {"label": "Records collected", "value": str(total)},
        {"label": "Avg relevance", "value": str(avg_score)},
        {"label": "Top score", "value": str(top_score)},
        {"label": "Sources used", "value": str(len(source_counts))},
        {"label": "Source-backed %", "value": f"{int(with_url/total*100)}%"},
        {"label": "From last 7 days", "value": str(recent)},
    ]

    return {
        "narrative": narrative,
        "insights": insights,
        "patterns": patterns,
        "highlights": highlights,
        "source_distribution": dict(source_counts),
        "skill_distribution": dict(Counter(all_skills)),
    }