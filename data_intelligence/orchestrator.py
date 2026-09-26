"""
Orchestrator - Executes a Workflow end-to-end.

Pipeline:
  1. AI engine parses the prompt into an Intent.
  2. Workflow builder creates a Workflow (steps).
  3. For each collect step: call the source via data_collector.
  4. Process -> validate -> dedupe -> enrich.
  5. Persist run + records via database layer.
"""

from __future__ import annotations
import time
import threading
import traceback
from typing import Dict, Any, List, Optional, Callable
from .ai_engine import get_engine, Intent
from .workflow_builder import WorkflowBuilder, Workflow, Step
from . import sources as source_mod
from . import data_processor as dp


# Global registry of live runs (in-memory mirror of DB status)
_runs_lock = threading.Lock()
_runs: Dict[str, Dict[str, Any]] = {}


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _runs_lock:
        run = _runs.get(run_id)
        return dict(run) if run else None


def _update_run(run_id: str, **kwargs) -> None:
    with _runs_lock:
        if run_id in _runs:
            _runs[run_id].update(kwargs)


def _sync_workflow_snapshot(run_id: str, workflow: Workflow) -> None:
    """Re-serialize the workflow (with the latest step statuses) into the
    in-memory run record so the dashboard can see live progress."""
    with _runs_lock:
        if run_id in _runs:
            _runs[run_id]["workflow"] = workflow.to_dict()


def _record_source_health(source: str, status: str, latency_ms: int, record_count: int) -> None:
    """Persist source health metrics for the dashboard's health card."""
    try:
        from . import database as db
        db.update_source_health(source, status, latency_ms, record_count)
    except Exception:
        pass


def _set_step(run_id: str, step_id: str, **kwargs) -> None:
    with _runs_lock:
        run = _runs.get(run_id)
        if not run:
            return
        for s in run["workflow"]["steps"]:
            if s["id"] == step_id:
                s.update(kwargs)


# ----------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------

def execute_run(
    run_id: str,
    prompt: str,
    persist_fn: Optional[Callable[[Dict[str, Any], List[Dict[str, Any]]], None]] = None,
) -> Dict[str, Any]:
    """Execute a workflow for the given prompt. persist_fn saves results."""
    engine = get_engine()
    intent = engine.parse(prompt)

    builder = WorkflowBuilder()
    workflow = builder.build(intent)

    # Save workflow to in-memory registry
    with _runs_lock:
        _runs[run_id] = {
            "id": run_id,
            "prompt": prompt,
            "intent": intent.to_dict(),
            "workflow": workflow.to_dict(),
            "status": "running",
            "started_at": time.time(),
            "records": [],
            "stats": {"sources_ok": 0, "sources_failed": 0, "deduped": 0, "dropped_invalid": 0},
        }

    all_records: List[Dict[str, Any]] = []
    try:
        # Step 1: Execute each "collect" step
        for step in workflow.steps:
            if step.type != "collect":
                continue
            step.status = "running"
            step.started_at = time.time()
            _sync_workflow_snapshot(run_id, workflow)

            try:
                t0 = time.time()
                recs = source_mod.collect(step.source, step.params)
                latency_ms = int((time.time() - t0) * 1000)
                recs = recs[: step.params.get("max_results", 25)]
                step.records_out = len(recs)
                step.latency_ms = latency_ms
                step.status = "done"
                step.message = f"Collected {len(recs)} record(s) in {latency_ms}ms"
                all_records.extend(recs)
                _update_run(run_id, stats={**_runs[run_id]["stats"], "sources_ok": _runs[run_id]["stats"]["sources_ok"] + 1})
                # Record source health
                _record_source_health(step.source, "ok", latency_ms, len(recs))
            except Exception as e:
                step.status = "failed"
                step.error = str(e)
                step.message = f"Source error: {e}"
                _update_run(run_id, stats={**_runs[run_id]["stats"], "sources_failed": _runs[run_id]["stats"]["sources_failed"] + 1})
                _record_source_health(step.source, "fail", 0, 0)
            finally:
                step.finished_at = time.time()
                _sync_workflow_snapshot(run_id, workflow)

        # Step 2-5: process steps in order
        for step in workflow.steps:
            if step.type == "collect":
                continue
            step.status = "running"
            step.started_at = time.time()
            step.records_in = len(all_records)
            _sync_workflow_snapshot(run_id, workflow)

            try:
                if step.type == "process":
                    all_records = dp.normalize(all_records)
                    step.message = "Records normalized"
                elif step.type == "validate":
                    valid, invalid = dp.validate(all_records)
                    all_records = valid
                    _update_run(run_id, stats={**_runs[run_id]["stats"], "dropped_invalid": len(invalid)})
                    step.message = f"{len(valid)} kept, {len(invalid)} dropped"
                elif step.type == "dedupe":
                    unique, removed = dp.dedupe(all_records)
                    all_records = unique
                    _update_run(run_id, stats={**_runs[run_id]["stats"], "deduped": removed})
                    step.message = f"{removed} duplicates removed"
                elif step.type == "enrich":
                    all_records = dp.enrich(all_records, intent.to_dict())
                    step.message = "Records scored"
                step.records_out = len(all_records)
                step.status = "done"
            except Exception as e:
                step.status = "failed"
                step.error = str(e)
                step.message = f"Error: {e}"
                traceback.print_exc()
            finally:
                step.finished_at = time.time()
                _sync_workflow_snapshot(run_id, workflow)

        # Sort by relevance
        all_records = dp.sort_by_relevance(all_records)

        # Trim to max_results
        max_n = intent.max_results or 25
        if len(all_records) > max_n:
            all_records = all_records[:max_n]

        workflow.status = "done"
        workflow.total_records = len(all_records)

        # Persist if a persistence callback is provided
        if persist_fn is not None:
            persist_fn(
                {
                    "id": run_id,
                    "prompt": prompt,
                    "intent": intent.to_dict(),
                    "workflow": workflow.to_dict(),
                    "status": "done",
                    "total_records": len(all_records),
                    "finished_at": time.time(),
                },
                all_records,
            )

        _update_run(
            run_id,
            workflow=_runs[run_id]["workflow"],
            status="done",
            finished_at=time.time(),
            records=all_records,
        )

        return {
            "run_id": run_id,
            "intent": intent.to_dict(),
            "workflow": workflow.to_dict(),
            "records": all_records,
            "total_records": len(all_records),
            "status": "done",
        }

    except Exception as e:
        traceback.print_exc()
        workflow.status = "failed"
        _update_run(run_id, status="failed", error=str(e))
        return {"run_id": run_id, "status": "failed", "error": str(e)}


def execute_async(run_id: str, prompt: str, persist_fn: Callable) -> threading.Thread:
    """Run the workflow in a background thread. Returns the Thread."""
    t = threading.Thread(
        target=execute_run,
        args=(run_id, prompt, persist_fn),
        daemon=True,
    )
    t.start()
    return t