"""
Data Processor - Cleaning, validation, deduplication, and enrichment.

Stage 1 - normalize: lowercases, strips junk, ensures required keys
Stage 2 - validate: schema check, drops records missing critical fields
Stage 3 - dedupe: by canonical key (url + title)
Stage 4 - enrich: adds a quality/relevance score
"""

from __future__ import annotations
import re
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Tuple
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


REQUIRED_FIELDS = ("id", "title", "source", "type")


def _normalize_record(r: Dict[str, Any]) -> Dict[str, Any]:
    """Tidy up a single record into a stable shape."""
    out = dict(r)
    out["title"] = (out.get("title") or "").strip() or "Untitled"
    out["description"] = (out.get("description") or "").strip()
    out["url"] = (out.get("url") or "").strip()
    out["source"] = (out.get("source") or "unknown").strip()
    out["type"] = (out.get("type") or "unknown").strip()
    out["company"] = (out.get("company") or None)
    out["location"] = (out.get("location") or None)
    out["skills"] = list(dict.fromkeys(out.get("skills") or []))
    out["industries"] = list(dict.fromkeys(out.get("industries") or []))
    out["extra"] = dict(out.get("extra") or {})
    if "published_at" not in out:
        out["published_at"] = None
    return out


def normalize(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_normalize_record(r) for r in records]


def validate(records: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (valid, invalid). Drops records missing critical fields."""
    valid, invalid = [], []
    for r in records:
        miss = [f for f in REQUIRED_FIELDS if not r.get(f)]
        if miss:
            invalid.append({"record": r, "missing": miss})
            continue
        if not r.get("url") and not r.get("description"):
            invalid.append({"record": r, "missing": ["url_or_description"]})
            continue
        valid.append(r)
    return valid, invalid


def _canonical_url(url: str) -> str:
    """Strip tracking query params and fragment."""
    try:
        u = urlparse(url)
        # Drop common tracking params
        bad = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid", "gclid"}
        q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k not in bad]
        return urlunparse((u.scheme, u.netloc.lower(), u.path.rstrip("/"), u.params, urlencode(q), ""))
    except Exception:
        return url


def _fingerprint(r: Dict[str, Any]) -> str:
    title = (r.get("title") or "").lower()
    title = re.sub(r"\s+", " ", title).strip()
    company = (r.get("company") or "").lower() if r.get("company") else ""
    url = _canonical_url(r.get("url") or "")
    base = f"{title}|{company}|{url}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def dedupe(records: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Deduplicate by URL+title fingerprint. Returns (unique, removed_count)."""
    seen = set()
    out = []
    for r in records:
        fp = _fingerprint(r)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(r)
    return out, len(records) - len(out)


def _score_record(r: Dict[str, Any], intent: Dict[str, Any]) -> int:
    """Heuristic 0-100 relevance + quality score."""
    score = 50
    title = (r.get("title") or "").lower()
    desc = (r.get("description") or "").lower()
    blob = f"{title} {desc}"

    # Skill matches
    skills = intent.get("skills") or []
    matches = sum(1 for s in skills if re.search(r"\b" + re.escape(s.lower()) + r"\b", blob))
    score += min(matches * 6, 30)

    # Industry matches
    for ind in (intent.get("industries") or []):
        if ind.lower() in blob:
            score += 6

    # Location matches
    for loc in (intent.get("locations") or []):
        if loc.lower() in blob or r.get("location") == loc:
            score += 4

    # Freshness bonus
    pub = r.get("published_at")
    if pub:
        try:
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            days = (datetime.utcnow() - dt.replace(tzinfo=None)).days
            if days <= 1:
                score += 10
            elif days <= 7:
                score += 6
            elif days <= 30:
                score += 3
        except Exception:
            pass

    # Quality signals
    if r.get("url"):
        score += 3
    if len(r.get("description") or "") > 200:
        score += 4
    if r.get("company"):
        score += 2

    return max(0, min(100, score))


def enrich(records: List[Dict[str, Any]], intent: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Add `score` field and a few derived attributes."""
    for r in records:
        r["score"] = _score_record(r, intent)
    return records


def sort_by_relevance(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(records, key=lambda r: r.get("score", 0), reverse=True)