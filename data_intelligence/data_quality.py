"""
Data Quality Checker - Inspects records for URL validity, missing fields,
suspicious patterns. Returns a quality report per record and per run.
"""

from __future__ import annotations
import re
from urllib.parse import urlparse
from typing import List, Dict, Any


URL_REGEX = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
SUSPICIOUS_DOMAINS = ("example.com", "example.org", "localhost", "127.0.0.1", "test.com", "foo.com")


def check_url(url: str) -> Dict[str, Any]:
    """Validate a URL: well-formed, has host, not suspicious."""
    if not url:
        return {"ok": False, "reason": "missing"}
    if not URL_REGEX.match(url):
        return {"ok": False, "reason": "malformed"}
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return {"ok": False, "reason": "no_host"}
        for sus in SUSPICIOUS_DOMAINS:
            if sus in parsed.netloc:
                return {"ok": True, "reason": "ok", "is_mock": True}
        return {"ok": True, "reason": "ok", "is_mock": False}
    except Exception:
        return {"ok": False, "reason": "parse_error"}


def detect_pii(text: str) -> Dict[str, List[str]]:
    """Detect PII patterns in text (best-effort)."""
    if not text:
        return {"emails": [], "phones": []}
    emails = EMAIL_REGEX.findall(text)
    phones = re.findall(r"\+?\d[\d\s\-\(\)]{8,}\d", text)
    # Filter out short digit strings (years, scores)
    phones = [p for p in phones if len(re.sub(r"\D", "", p)) >= 10]
    return {"emails": emails[:5], "phones": phones[:5]}


def quality_report_for_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-record quality assessment + run-level summary."""
    per_record: List[Dict[str, Any]] = []
    ok_urls = 0
    mock_urls = 0
    pii_records = 0
    fields_present = {"title": 0, "description": 0, "url": 0, "company": 0, "skills": 0}

    for r in records:
        issues: List[str] = []
        url_check = check_url(r.get("url") or "")
        if url_check["ok"]:
            ok_urls += 1
            if url_check.get("is_mock"):
                mock_urls += 1
                issues.append("mock_source_url")
        else:
            issues.append(f"url_{url_check['reason']}")

        # Required field checks
        for field in ("title", "description", "url", "company", "skills"):
            v = r.get(field)
            if v and (not isinstance(v, list) or len(v) > 0):
                fields_present[field] += 1
            else:
                if field in ("title", "url"):
                    issues.append(f"missing_{field}")
                elif field in ("description", "company"):
                    issues.append(f"no_{field}")

        # PII check on description + title
        text = (r.get("description") or "") + " " + (r.get("title") or "")
        pii = detect_pii(text)
        if pii["emails"] or pii["phones"]:
            pii_records += 1
            issues.append("pii_detected")

        per_record.append({
            "id": r.get("id"),
            "url_status": url_check,
            "issues": issues,
            "pii": pii,
            "completeness": round(sum(1 for f in ("title", "description", "url", "company")
                                       if r.get(f)) / 4, 2),
        })

    total = max(1, len(records))
    return {
        "total": len(records),
        "ok_urls": ok_urls,
        "mock_urls": mock_urls,
        "real_urls": ok_urls - mock_urls,
        "pii_records": pii_records,
        "fields_present_pct": {k: round(v / total * 100, 1) for k, v in fields_present.items()},
        "completeness_avg": round(
            sum(p["completeness"] for p in per_record) / total, 2),
        "issues_by_type": _count_issues(per_record),
        "per_record": per_record[:200],  # cap for payload size
    }


def _count_issues(per_record: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in per_record:
        for issue in r["issues"]:
            counts[issue] = counts.get(issue, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def source_quality_metrics(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per-source quality: count, avg score, real-url %, completeness."""
    out: Dict[str, Dict[str, Any]] = {}
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        by_source.setdefault(r.get("source") or "unknown", []).append(r)
    for src, recs in by_source.items():
        real = sum(1 for r in recs if not _is_mock_url(r.get("url") or ""))
        scored = [r.get("score") or 0 for r in recs]
        out[src] = {
            "count": len(recs),
            "avg_score": round(sum(scored) / len(scored), 1) if scored else 0,
            "real_url_pct": round(real / len(recs) * 100, 1),
            "completeness": round(
                sum(1 for r in recs if r.get("title") and r.get("url")) / len(recs) * 100, 1),
        }
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["count"]))


def _is_mock_url(url: str) -> bool:
    if not url:
        return True
    for sus in SUSPICIOUS_DOMAINS:
        if sus in url:
            return True
    return False