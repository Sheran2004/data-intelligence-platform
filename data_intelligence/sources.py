"""
Data Sources - Permitted, pluggable collection backends.

Each source is a function: collect(params) -> List[Dict]
Records follow a normalized schema:
  {
    "id": str (source-prefixed),
    "title": str,
    "description": str,
    "url": str,
    "source": str,
    "type": str,            # job | lead | sponsor | market | news | repo | company
    "company": Optional[str],
    "location": Optional[str],
    "skills": List[str],
    "industries": List[str],
    "published_at": ISO date string,
    "extra": dict,
  }
"""

from __future__ import annotations
import re
import time
import uuid
import hashlib
import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import requests


USER_AGENT = "Mozilla/5.0 (compatible; DataIntelligenceBot/1.0; +https://example.com/bot)"
TIMEOUT = 5
# Per-source hard cap. If a source call takes longer, it is abandoned and the
# workflow continues with whatever has been collected so far.
SOURCE_HARD_TIMEOUT = 12


# ----------------------------------------------------------------------
# Real sources - hit public APIs
# ----------------------------------------------------------------------

def _hn_algolia(path: str, params: Dict[str, Any]) -> Optional[Any]:
    try:
        r = requests.get(
            f"https://hn.algolia.com/api/v1/{path}",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        return None
    return None


def hn_jobs(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Hacker News 'Who is hiring' - via Algolia search."""
    query = params.get("query") or "hiring"
    tags = params.get("tags") or []
    if tags:
        # Algolia supports structured search: e.g. (python OR react) AND (remote OR india)
        keyword_part = " OR ".join(tags[:5])
        query = f"{keyword_part} {query}"

    max_results = min(int(params.get("max_results", 25)), 100)
    data = _hn_algolia("search", {
        "query": query,
        "tags": "story",
        "hitsPerPage": max_results,
    })
    if not data or "hits" not in data:
        return []

    out: List[Dict[str, Any]] = []
    for h in data["hits"]:
        title = h.get("title") or ""
        if "hiring" not in title.lower() and "job" not in title.lower():
            continue
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        ts = h.get("created_at_i")
        published = datetime.fromtimestamp(ts).isoformat() if ts else None
        text = (h.get("story_text") or "")[:1500]
        # Try to extract skills from text
        skills = _extract_skills(text + " " + title)
        locations = _extract_locations(text + " " + title)
        out.append({
            "id": f"hnjob-{h.get('objectID')}",
            "title": title,
            "description": text or "Posted on Hacker News",
            "url": url,
            "source": "hn_jobs",
            "type": "job",
            "company": _extract_company(title),
            "location": locations[0] if locations else None,
            "skills": skills,
            "industries": [],
            "published_at": published,
            "extra": {"hn_id": h.get("objectID"), "points": h.get("points", 0)},
        })
    return out[:max_results]


def remoteok(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """RemoteOK public JSON API."""
    max_results = min(int(params.get("max_results", 25)), 80)
    tags = params.get("tags") or []
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return []
        rows = r.json()
        if not isinstance(rows, list) or len(rows) < 2:
            return []
        rows = rows[1:]  # first row is legal notice
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            # Filter by tags
            if tags:
                row_tags = [t.lower() for t in (row.get("tags") or [])]
                if not any(t.lower() in row_tags for t in tags):
                    continue
            skills = [t for t in (row.get("tags") or [])][:10]
            ts = row.get("date")
            published = None
            if ts:
                try:
                    published = datetime.fromisoformat(ts.replace("Z", "+00:00")).isoformat()
                except Exception:
                    published = ts
            out.append({
                "id": f"rok-{row.get('id')}",
                "title": row.get("position") or "Untitled",
                "description": (row.get("description") or "")[:1500],
                "url": row.get("url") or row.get("apply_url"),
                "source": "remoteok",
                "type": "job",
                "company": row.get("company"),
                "location": "remote",
                "skills": skills,
                "industries": [],
                "published_at": published,
                "extra": {
                    "salary_min": row.get("salary_min"),
                    "salary_max": row.get("salary_max"),
                },
            })
            if len(out) >= max_results:
                break
        return out
    except Exception:
        return []


def github_search(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """GitHub repository search - public, no auth needed for low rate limits."""
    max_results = min(int(params.get("max_results", 25)), 50)
    language = params.get("language")
    topic = params.get("topic")
    q_parts = []
    if topic:
        q_parts.append(f"topic:{topic}")
    if language:
        q_parts.append(f"language:{language}")
    q_parts.append("stars:>50")
    q = " ".join(q_parts) or "stars:>100"
    try:
        r = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": q, "per_page": max_results, "sort": "stars", "order": "desc"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return []
        items = r.json().get("items", [])
        out = []
        for repo in items:
            topics = repo.get("topics") or []
            pushed = repo.get("pushed_at")
            out.append({
                "id": f"gh-{repo.get('id')}",
                "title": repo.get("full_name"),
                "description": (repo.get("description") or "")[:800],
                "url": repo.get("html_url"),
                "source": "github_search",
                "type": "repo",
                "company": (repo.get("owner") or {}).get("login"),
                "location": None,
                "skills": [repo.get("language")] + topics,
                "industries": topics,
                "published_at": pushed,
                "extra": {
                    "stars": repo.get("stargazers_count"),
                    "forks": repo.get("forks_count"),
                    "language": repo.get("language"),
                },
            })
        return out
    except Exception:
        return []


def github_trending(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Use GitHub search with recent filter as a trending proxy."""
    p = dict(params)
    p["language"] = params.get("language") or "python"
    p["max_results"] = min(int(params.get("max_results", 25)), 30)
    # Trending = created in last 30 days, sorted by stars
    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    q_parts = [f"language:{p['language']}", f"created:>{thirty_days_ago}", "stars:>10"]
    if p.get("topic"):
        q_parts.append(f"topic:{p['topic']}")
    q = " ".join(q_parts)
    try:
        r = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": q, "per_page": p["max_results"], "sort": "stars", "order": "desc"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return []
        items = r.json().get("items", [])
        out = []
        for repo in items:
            topics = repo.get("topics") or []
            pushed = repo.get("pushed_at")
            out.append({
                "id": f"ghtr-{repo.get('id')}",
                "title": repo.get("full_name"),
                "description": (repo.get("description") or "")[:800],
                "url": repo.get("html_url"),
                "source": "github_trending",
                "type": "market",
                "company": (repo.get("owner") or {}).get("login"),
                "location": None,
                "skills": [repo.get("language")] + topics,
                "industries": topics,
                "published_at": pushed,
                "extra": {
                    "stars": repo.get("stargazers_count"),
                    "velocity": "trending_30d",
                    "language": repo.get("language"),
                },
            })
        return out
    except Exception:
        return []


def hn_top(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Top stories from Hacker News as market/news signal."""
    max_results = min(int(params.get("max_results", 25)), 50)
    ids_data = _hn_algolia("search", {
        "query": params.get("query") or "tech",
        "tags": "story",
        "hitsPerPage": max_results,
    })
    if not ids_data or "hits" not in ids_data:
        return []
    out = []
    for h in ids_data["hits"]:
        ts = h.get("created_at_i")
        published = datetime.fromtimestamp(ts).isoformat() if ts else None
        out.append({
            "id": f"hntop-{h.get('objectID')}",
            "title": h.get("title") or "",
            "description": (h.get("story_text") or "")[:1000],
            "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "source": "hn_top",
            "type": "market",
            "company": None,
            "location": None,
            "skills": _extract_skills((h.get("title") or "") + " " + (h.get("story_text") or "")),
            "industries": [],
            "published_at": published,
            "extra": {"points": h.get("points", 0), "comments": h.get("num_comments", 0)},
        })
    return out


def hn_show(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Show HN posts - early-stage startups, leads, sponsors."""
    max_results = min(int(params.get("max_results", 25)), 50)
    data = _hn_algolia("search", {
        "query": params.get("query") or "Show HN",
        "tags": "story",
        "hitsPerPage": max_results,
    })
    if not data or "hits" not in data:
        return []
    out = []
    for h in data["hits"]:
        title = h.get("title") or ""
        if "show hn" not in title.lower():
            continue
        ts = h.get("created_at_i")
        published = datetime.fromtimestamp(ts).isoformat() if ts else None
        company = _extract_company(title)
        out.append({
            "id": f"hnshow-{h.get('objectID')}",
            "title": title,
            "description": (h.get("story_text") or "")[:1200],
            "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "source": "hn_show",
            "type": "lead",
            "company": company,
            "location": None,
            "skills": _extract_skills(title),
            "industries": [],
            "published_at": published,
            "extra": {"points": h.get("points", 0)},
        })
    return out[:max_results]


def hn_search(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generic HN search -> news type."""
    max_results = min(int(params.get("max_results", 25)), 50)
    data = _hn_algolia("search", {
        "query": params.get("query") or "tech",
        "tags": "story",
        "hitsPerPage": max_results,
    })
    if not data or "hits" not in data:
        return []
    out = []
    for h in data["hits"]:
        ts = h.get("created_at_i")
        published = datetime.fromtimestamp(ts).isoformat() if ts else None
        out.append({
            "id": f"hnsrch-{h.get('objectID')}",
            "title": h.get("title") or "",
            "description": (h.get("story_text") or "")[:1000],
            "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "source": "hn_search",
            "type": "news",
            "company": None,
            "location": None,
            "skills": _extract_skills((h.get("title") or "")),
            "industries": [],
            "published_at": published,
            "extra": {"points": h.get("points", 0)},
        })
    return out


def github_orgs(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Discover organizations via GitHub user search (companies/users)."""
    max_results = min(int(params.get("max_results", 25)), 30)
    query_parts = ["type:org"]
    if params.get("industries"):
        query_parts.append(params["industries"][0])
    if params.get("locations"):
        loc = params["locations"][0]
        query_parts.append(f"location:{loc}")
    query = " ".join(query_parts)
    try:
        r = requests.get(
            "https://api.github.com/search/users",
            params={"q": query, "per_page": max_results},
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return []
        items = r.json().get("items", [])
        out = []
        for org in items:
            out.append({
                "id": f"ghorg-{org.get('id')}",
                "title": org.get("login"),
                "description": (org.get("bio") or "")[:500],
                "url": org.get("html_url"),
                "source": "github_orgs",
                "type": "lead",
                "company": org.get("login"),
                "location": org.get("location"),
                "skills": [],
                "industries": params.get("industries", []),
                "published_at": None,
                "extra": {"followers": None, "avatar": org.get("avatar_url")},
            })
        return out
    except Exception:
        return []


# ----------------------------------------------------------------------
# Curated mock sources - always available, offline-friendly
# ----------------------------------------------------------------------

def _gen_jobs_mock(params: Dict[str, Any], count: int = 30) -> List[Dict[str, Any]]:
    skills_pool = params.get("skills") or ["python", "javascript", "react", "aws", "sql"]
    industries_pool = params.get("industries") or ["saas", "ai"]
    locations_pool = params.get("locations") or ["remote"]
    companies = [
        "Nimbus Labs", "Pinecone AI", "QuantaForge", "Helix Systems",
        "Riverbed Cloud", "Glide Tech", "Foxglove", "Aurora Stack",
        "Lumen Analytics", "Vector DB Inc", "Sentinel Cloud", "Cloudforge",
        "Pulsar Robotics", "Mira AI", "Stratosphere", "Beacon Studio",
        "Nebula Works", "Obsidian Labs", "Caldera", "Polaris AI",
        "Atlas Compute", "Cipher Forge", "Echo Robotics", "Mercury Stack",
    ]
    titles = [
        "Senior Python Engineer", "Full-Stack Developer", "Frontend Engineer (React)",
        "DevOps / SRE", "Data Engineer", "Machine Learning Engineer",
        "Backend Engineer", "Mobile Engineer (iOS/Android)", "Product Engineer",
        "Cloud Architect", "Security Engineer", "Platform Engineer",
        "Staff Software Engineer", "Engineering Manager",
    ]
    rng = random.Random(hash(tuple(sorted(skills_pool + industries_pool))))
    rows = []
    now = datetime.utcnow()
    for i in range(count):
        company = rng.choice(companies)
        title = rng.choice(titles)
        loc = rng.choice(locations_pool)
        ind = rng.choice(industries_pool)
        skill_set = rng.sample(skills_pool, min(3, len(skills_pool)))
        days_ago = rng.randint(0, 30)
        published = (now - timedelta(days=days_ago, hours=rng.randint(0, 23))).isoformat()
        slug = hashlib.md5(f"{company}-{title}-{i}".encode()).hexdigest()[:8]
        rows.append({
            "id": f"jobmock-{slug}",
            "title": f"{title} at {company}",
            "description": (
                f"{company} is hiring a {title} to join our {ind} team. "
                f"You will work with {', '.join(skill_set)} on production systems. "
                f"Location: {loc}. Competitive compensation, equity, and remote-friendly culture."
            ),
            "url": f"https://example.com/jobs/{slug}",
            "source": "jobmock",
            "type": "job",
            "company": company,
            "location": loc,
            "skills": skill_set,
            "industries": [ind],
            "published_at": published,
            "extra": {"compensation_band": "competitive", "equity": True},
        })
    return rows


def _gen_leads_mock(params: Dict[str, Any], count: int = 25) -> List[Dict[str, Any]]:
    industries_pool = params.get("industries") or ["saas"]
    locations_pool = params.get("locations") or ["usa"]
    sizes = params.get("company_sizes") or ["medium"]
    companies = [
        "Zenith Cloud", "Polaris Labs", "Cobalt Systems", "Quill AI",
        "Trailhead Robotics", "Quantum Bridge", "Mira Health", "Cypher Networks",
        "Solar Stack", "Halo Analytics", "Aurora Compute", "Iron Vine",
        "Forge Labs", "Drift Cloud", "Lumen Robotics", "Echo Health",
        "Pinecone Health", "Vector Forge", "Helix Analytics", "Beacon Cloud",
    ]
    rng = random.Random(hash(tuple(sorted(industries_pool + locations_pool))))
    rows = []
    for i in range(count):
        c = rng.choice(companies)
        ind = rng.choice(industries_pool)
        loc = rng.choice(locations_pool)
        sz = rng.choice(sizes)
        slug = hashlib.md5(f"{c}-{i}".encode()).hexdigest()[:8]
        rows.append({
            "id": f"leadmock-{slug}",
            "title": f"{c} - Decision Maker Contact",
            "description": (
                f"{c} is a {sz} {ind} company based in {loc}. "
                f"They recently posted hiring signals on public platforms. "
                f"Good fit for outbound outreach."
            ),
            "url": f"https://example.com/leads/{slug}",
            "source": "leadmock",
            "type": "lead",
            "company": c,
            "location": loc,
            "skills": [],
            "industries": [ind],
            "published_at": (datetime.utcnow() - timedelta(days=rng.randint(0, 30))).isoformat(),
            "extra": {"contact_role": rng.choice(["CTO", "VP Eng", "Head of Product", "Founder"]), "size": sz},
        })
    return rows


def _gen_sponsors_mock(params: Dict[str, Any], count: int = 20) -> List[Dict[str, Any]]:
    industries_pool = params.get("industries") or ["ai"]
    sponsors = [
        ("Sequoia Capital", "vc"),
        ("Andreessen Horowitz", "vc"),
        ("Y Combinator", "accelerator"),
        ("Accel", "vc"),
        ("Index Ventures", "vc"),
        ("Techstars", "accelerator"),
        ("500 Global", "accelerator"),
        ("Greylock", "vc"),
        ("Lightspeed", "vc"),
        ("First Round Capital", "vc"),
        ("Bessemer Venture Partners", "vc"),
        ("NEA", "vc"),
    ]
    rng = random.Random(hash(tuple(sorted(industries_pool))))
    rows = []
    for i in range(count):
        s, kind = rng.choice(sponsors)
        slug = hashlib.md5(f"{s}-{i}".encode()).hexdigest()[:8]
        rows.append({
            "id": f"sponsormock-{slug}",
            "title": f"{s} ({kind}) - Sponsorship Opportunity",
            "description": (
                f"{s} actively invests in {', '.join(industries_pool)} startups. "
                f"Typical check size varies. Open to networking events, conference sponsorships, "
                f"and pilot programs."
            ),
            "url": f"https://example.com/sponsors/{slug}",
            "source": "sponsormock",
            "type": "sponsor",
            "company": s,
            "location": None,
            "skills": [],
            "industries": industries_pool,
            "published_at": (datetime.utcnow() - timedelta(days=rng.randint(0, 90))).isoformat(),
            "extra": {"kind": kind, "stage": rng.choice(["seed", "series a", "series b", "growth"])},
        })
    return rows


def _gen_market_mock(params: Dict[str, Any], count: int = 20) -> List[Dict[str, Any]]:
    industries_pool = params.get("industries") or ["ai", "saas"]
    rows = []
    metrics = [
        ("AI tooling market", "$42B 2024", "+38% YoY", "high"),
        ("SaaS churn rate (mid-market)", "8.2%", "-1.1pp", "stable"),
        ("Devtools spend", "$13B 2024", "+24% YoY", "high"),
        ("Fintech adoption", "76% of SMBs", "+9pp YoY", "rising"),
        ("Cloud infrastructure", "$247B 2025", "+22% YoY", "high"),
        ("Open source funding", "$1.4B 2024", "+18% YoY", "stable"),
        ("Data engineering tools", "$8.7B 2024", "+27% YoY", "rising"),
        ("Edge AI hardware", "$23B 2024", "+33% YoY", "rising"),
        ("Healthcare AI", "$11B 2024", "+41% YoY", "high"),
        ("Cybersecurity spend", "$215B 2025", "+12% YoY", "stable"),
    ]
    rng = random.Random(hash(tuple(sorted(industries_pool))))
    now = datetime.utcnow()
    for i in range(count):
        name, val, growth, trend = rng.choice(metrics)
        slug = hashlib.md5(f"{name}-{i}".encode()).hexdigest()[:8]
        rows.append({
            "id": f"marketmock-{slug}",
            "title": name,
            "description": f"Latest value: {val}. Growth: {growth}. Trend: {trend}.",
            "url": f"https://example.com/market/{slug}",
            "source": "marketmock",
            "type": "market",
            "company": None,
            "location": None,
            "skills": [],
            "industries": industries_pool,
            "published_at": (now - timedelta(days=rng.randint(0, 14))).isoformat(),
            "extra": {"value": val, "growth": growth, "trend": trend},
        })
    return rows


def _gen_news_mock(params: Dict[str, Any], count: int = 25) -> List[Dict[str, Any]]:
    industries_pool = params.get("industries") or ["ai"]
    rows = []
    templates = [
        ("{ind} startup raises $50M Series B to expand platform", "techcrunch.com"),
        ("Open source {ind} framework hits 100k stars on GitHub", "github.blog"),
        ("{ind} adoption jumps 30% in enterprise", "forrester.com"),
        ("Major cloud provider launches managed {ind} service", "theinformation.com"),
        ("{ind} conference sells out, attendance doubles", "event-site.com"),
        ("Survey: 78% of {ind} teams plan to increase spend next year", "gartner.com"),
        ("New {ind} regulation passes EU parliament", "reuters.com"),
        ("Y Combinator W26 batch features 60+ {ind} startups", "ycombinator.com"),
    ]
    rng = random.Random(hash(tuple(sorted(industries_pool))))
    now = datetime.utcnow()
    for i in range(count):
        tpl, domain = rng.choice(templates)
        ind = rng.choice(industries_pool)
        title = tpl.format(ind=ind)
        slug = hashlib.md5(f"{title}-{i}".encode()).hexdigest()[:8]
        rows.append({
            "id": f"newsmock-{slug}",
            "title": title,
            "description": f"Coverage on {domain}. Industry signal for {ind} sector.",
            "url": f"https://{domain}/article/{slug}",
            "source": "newsmock",
            "type": "news",
            "company": None,
            "location": None,
            "skills": [],
            "industries": [ind],
            "published_at": (now - timedelta(days=rng.randint(0, 14))).isoformat(),
            "extra": {"source_domain": domain},
        })
    return rows


def _gen_repos_mock(params: Dict[str, Any], count: int = 25) -> List[Dict[str, Any]]:
    skills_pool = params.get("skills") or ["python"]
    repos_by_lang = {
        "python": ["fastapi/fastapi", "pydantic/pydantic", "tiangolo/sqlmodel", "psf/requests"],
        "javascript": ["vercel/next.js", "facebook/react", "expressjs/express"],
        "typescript": ["microsoft/TypeScript", "prisma/prisma"],
        "rust": ["denoland/deno", "tokio-rs/tokio", "actix/actix-web"],
        "go": ["kubernetes/kubernetes", "gin-gonic/gin", "moby/moby"],
        "ai": ["openai/openai-python", "anthropics/anthropic-sdk-python", "huggingface/transformers"],
    }
    lang = skills_pool[0].lower()
    repo_names = repos_by_lang.get(lang, repos_by_lang["python"])
    rng = random.Random(hash(tuple(sorted(skills_pool))))
    rows = []
    for i in range(count):
        name = rng.choice(repo_names)
        slug = hashlib.md5(f"{name}-{i}".encode()).hexdigest()[:8]
        stars = rng.randint(500, 90000)
        rows.append({
            "id": f"repomock-{slug}",
            "title": name,
            "description": f"Curated {lang} project — actively maintained.",
            "url": f"https://github.com/{name}",
            "source": "repomock",
            "type": "repo",
            "company": name.split("/")[0],
            "location": None,
            "skills": [lang],
            "industries": [],
            "published_at": (datetime.utcnow() - timedelta(days=rng.randint(1, 60))).isoformat(),
            "extra": {"stars": stars, "language": lang},
        })
    return rows


def jobmock(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _gen_jobs_mock(params, params.get("max_results", 30))


def leadmock(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _gen_leads_mock(params, params.get("max_results", 25))


def sponsormock(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _gen_sponsors_mock(params, params.get("max_results", 20))


def marketmock(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _gen_market_mock(params, params.get("max_results", 20))


def newsmock(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _gen_news_mock(params, params.get("max_results", 25))


def repomock(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _gen_repos_mock(params, params.get("max_results", 25))


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _extract_skills(text: str) -> List[str]:
    found = []
    for s in [
        "python", "javascript", "typescript", "react", "node", "node.js", "go", "golang", "rust",
        "java", "kotlin", "swift", "django", "flask", "fastapi", "aws", "gcp", "azure",
        "kubernetes", "docker", "terraform", "postgres", "mongodb", "redis", "kafka",
        "tensorflow", "pytorch", "machine learning", "llm", "ai", "data",
    ]:
        if re.search(r"\b" + re.escape(s) + r"\b", text.lower()):
            found.append(s)
    return list(dict.fromkeys(found))[:5]


def _extract_locations(text: str) -> List[str]:
    found = []
    mapping = {
        "remote": ["remote", "anywhere", "wfh"],
        "india": ["india", "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad"],
        "usa": ["usa", "united states", "new york", "san francisco", "seattle", "austin"],
        "europe": ["europe", "uk", "london", "berlin", "paris", "amsterdam"],
        "asia": ["asia", "singapore", "tokyo"],
    }
    low = text.lower()
    for loc, kws in mapping.items():
        if any(k in low for k in kws):
            found.append(loc)
    return found


def _extract_company(title: str) -> Optional[str]:
    m = re.search(r"\bat\s+([A-Z][\w&.\- ]{1,40})", title)
    if m:
        return m.group(1).strip().rstrip(",.;:")[:60]
    return None


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------

SOURCE_REGISTRY = {
    "hn_jobs": hn_jobs,
    "remoteok": remoteok,
    "github_search": github_search,
    "github_trending": github_trending,
    "github_orgs": github_orgs,
    "hn_top": hn_top,
    "hn_show": hn_show,
    "hn_search": hn_search,
    "jobmock": jobmock,
    "leadmock": leadmock,
    "sponsormock": sponsormock,
    "marketmock": marketmock,
    "newsmock": newsmock,
    "repomock": repomock,
}


def collect(source: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Call a source by name. Falls back to mock if real source returns nothing.

    Each call is wrapped in a thread with a hard timeout. If the source hangs
    beyond SOURCE_HARD_TIMEOUT seconds, it is abandoned (returns empty) so the
    overall workflow cannot get stuck on a single slow network endpoint.
    """
    fn = SOURCE_REGISTRY.get(source)
    if not fn:
        return []

    import threading
    result_box: Dict[str, Any] = {"records": [], "error": None}

    def _runner():
        try:
            result_box["records"] = fn(params) or []
        except Exception as e:
            result_box["error"] = str(e)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=SOURCE_HARD_TIMEOUT)

    if t.is_alive():
        # Thread is still running - abandon and continue
        print(f"[sources] {source} exceeded {SOURCE_HARD_TIMEOUT}s hard timeout - skipping")
        return []
    if result_box["error"]:
        print(f"[sources] {source} failed: {result_box['error']}")
        return []
    return result_box["records"]