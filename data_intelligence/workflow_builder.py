"""
Workflow Builder - Dynamically designs executable data-collection workflows.

Given an Intent from the AI engine, this module produces a Workflow
(a sequence of Steps). Each Step has:
  - id
  - type: collect | process | validate | dedupe | enrich
  - source: which data source to use (only for collect)
  - params: step-specific config
  - status: pending | running | done | failed | skipped
"""

from __future__ import annotations
import uuid
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from .ai_engine import Intent


# ----------------------------------------------------------------------
# Source registry - whitelisted, permitted sources per data type
# ----------------------------------------------------------------------

PERMITTED_SOURCES: Dict[str, List[str]] = {
    "job": [
        "hn_jobs",         # Hacker News "Who is hiring" via Algolia
        "remoteok",        # RemoteOK public API
        "jobmock",         # Curated job dataset (offline fallback)
    ],
    "lead": [
        "github_orgs",     # Discover companies via GitHub org search
        "hn_show",         # Hacker News Show HN -> startup leads
        "leadmock",        # Curated lead dataset
    ],
    "sponsor": [
        "hn_show",         # Show HN often features funded startups
        "github_orgs",     # Org info for sponsorship/contact discovery
        "sponsormock",     # Curated sponsor dataset
    ],
    "market": [
        "github_trending", # Trending repos as market sentiment signal
        "hn_top",          # Top HN stories as tech market signal
        "marketmock",      # Curated market dataset
    ],
    "news": [
        "hn_top",          # Top stories
        "hn_search",       # Algolia HN search
        "newsmock",        # Curated news dataset
    ],
    "repo": [
        "github_search",   # GitHub repo search
        "github_trending", # Trending
        "repomock",        # Curated repo dataset
    ],
    "company": [
        "github_orgs",
        "hn_show",
        "leadmock",
    ],
}


# ----------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------

@dataclass
class Step:
    id: str
    name: str
    type: str  # collect | process | validate | dedupe | enrich
    source: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | running | done | failed | skipped
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    records_in: int = 0
    records_out: int = 0
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Workflow:
    id: str
    name: str
    intent: Dict[str, Any]
    steps: List[Step] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending | running | done | failed | partial
    total_records: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "intent": self.intent,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "status": self.status,
            "total_records": self.total_records,
        }


# ----------------------------------------------------------------------
# Builder
# ----------------------------------------------------------------------

class WorkflowBuilder:
    """Creates a workflow plan from an Intent."""

    def __init__(self) -> None:
        pass

    def build(self, intent: Intent) -> Workflow:
        sources = PERMITTED_SOURCES.get(intent.data_type, PERMITTED_SOURCES["job"])
        wf = Workflow(
            id=str(uuid.uuid4())[:8],
            name=f"{intent.data_type.title()} collection - {intent.summary[:60]}",
            intent=intent.to_dict(),
        )

        # Step 1: collection per source (parallel-safe; we'll execute sequentially
        # but each can be skipped based on intent constraints)
        for src in sources:
            params = self._build_params(intent, src)
            wf.steps.append(Step(
                id=str(uuid.uuid4())[:8],
                name=f"Collect from {src}",
                type="collect",
                source=src,
                params=params,
            ))

        # Step 2: normalize / merge
        wf.steps.append(Step(
            id=str(uuid.uuid4())[:8],
            name="Normalize & merge results",
            type="process",
            params={"operation": "normalize"},
        ))

        # Step 3: validate
        wf.steps.append(Step(
            id=str(uuid.uuid4())[:8],
            name="Validate records (schema + quality)",
            type="validate",
            params={"schema": "standard"},
        ))

        # Step 4: dedupe
        wf.steps.append(Step(
            id=str(uuid.uuid4())[:8],
            name="Deduplicate records",
            type="dedupe",
            params={"key": "auto"},
        ))

        # Step 5: enrich with computed signals (score)
        wf.steps.append(Step(
            id=str(uuid.uuid4())[:8],
            name="Enrich with quality & relevance score",
            type="enrich",
            params={"scorer": "default"},
        ))

        return wf

    @staticmethod
    def _build_params(intent: Intent, source: str) -> Dict[str, Any]:
        base = {
            "query": " ".join(intent.keywords) or intent.data_type,
            "skills": intent.skills,
            "locations": intent.locations,
            "industries": intent.industries,
            "company_sizes": intent.company_sizes,
            "time_window_hours": intent.time_window_hours,
            "max_results": intent.max_results,
            "freshness": intent.freshness,
        }
        if source in ("remoteok", "hn_jobs"):
            base["tags"] = intent.skills + intent.industries
        if source in ("github_search", "github_trending"):
            base["language"] = intent.skills[0] if intent.skills else None
            base["topic"] = intent.industries[0] if intent.industries else None
        if source in ("hn_search", "hn_top", "hn_show"):
            base["query"] = " ".join(intent.keywords) or intent.data_type
        return base