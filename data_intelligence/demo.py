"""
Demo seeder - Generates a curated set of pre-canned runs so judges can
explore the platform instantly without waiting for live APIs.
"""

from __future__ import annotations
import uuid
import time
from typing import List, Dict, Any
from . import database as db
from . import sources as source_mod
from . import data_processor as dp
from .workflow_builder import WorkflowBuilder
from .ai_engine import get_engine


DEMO_PROMPTS = [
    "Find me remote Python developer jobs in AI startups, posted in the last 7 days",
    "Collect SaaS leads in fintech from USA, top 30 companies",
    "Get sponsorship opportunities for AI conferences, give me 15 results",
    "Find trending Rust open source repos with more than 100 stars",
    "Find me top 20 market data points for cybersecurity spend growth",
    "Collect news about LLM and GenAI from this week",
]


def _build_demo_records(prompt: str, intent_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run real sources (fast mock fallback) + the full pipeline."""
    engine = get_engine()
    intent = engine.parse(prompt)

    builder = WorkflowBuilder()
    workflow = builder.build(intent)

    # Execute steps synchronously (small payload)
    all_records = []
    for step in workflow.steps:
        if step.type != "collect":
            continue
        try:
            recs = source_mod.collect(step.source, step.params)
            recs = recs[: step.params.get("max_results", 25)]
            all_records.extend(recs)
        except Exception:
            pass

    if not all_records:
        # Pure fallback - hit only mocks to ensure we always have something
        for src in [s for s in intent_data.get("_fallback_sources", [])]:
            try:
                all_records.extend(source_mod.collect(src, intent_data.get("_fallback_params", {})))
            except Exception:
                pass

    # Pipeline
    all_records = dp.normalize(all_records)
    valid, _ = dp.validate(all_records)
    unique, _ = dp.dedupe(valid)
    scored = dp.enrich(unique, intent.to_dict())
    sorted_recs = dp.sort_by_relevance(scored)
    return sorted_recs[: intent.max_results]


def seed_demo_runs() -> List[str]:
    """Create demo runs and return their IDs. Idempotent: skips if any exist."""
    existing = db.list_runs()
    if existing:
        return [r["id"] for r in existing[: len(DEMO_PROMPTS)]]

    engine = get_engine()
    run_ids: List[str] = []
    for prompt in DEMO_PROMPTS:
        intent = engine.parse(prompt)
        records = _build_demo_records(prompt, {})
        # Force a minimum count by padding with mock fallback
        if len(records) < 8:
            from . import sources as src_mod
            fallback = f"{intent.data_type}mock"
            try:
                extra = src_mod.collect(fallback, {
                    "skills": intent.skills,
                    "industries": intent.industries,
                    "locations": intent.locations,
                    "company_sizes": intent.company_sizes,
                    "max_results": 20,
                })
                records.extend(extra)
            except Exception:
                pass
            records = dp.sort_by_relevance(dp.dedupe(dp.normalize(records))[0])[: intent.max_results]

        run_id = uuid.uuid4().hex[:8]
        builder = WorkflowBuilder()
        workflow = builder.build(intent)
        # Mark all workflow steps as done (since we already executed them above)
        for s in workflow.steps:
            s.status = "done"
            s.message = "Demo run - completed offline"
        workflow.status = "done"
        workflow.total_records = len(records)

        db.create_run(run_id, prompt)
        db.save_run({
            "id": run_id,
            "prompt": prompt,
            "intent": intent.to_dict(),
            "workflow": workflow.to_dict(),
            "status": "done",
            "total_records": len(records),
            "created_at": time.time() - 600,  # 10 min ago
            "finished_at": time.time() - 590,
        }, records)
        run_ids.append(run_id)

    return run_ids