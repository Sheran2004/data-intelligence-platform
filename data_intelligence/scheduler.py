"""
Scheduler - Background thread that polls for due schedules and re-runs them.
"""

from __future__ import annotations
import threading
import time
import uuid
from typing import Callable, Optional
from . import database as db
from .orchestrator import execute_run


_scheduler_thread: Optional[threading.Thread] = None
_scheduler_stop = threading.Event()


def _scheduler_loop() -> None:
    while not _scheduler_stop.is_set():
        try:
            now = time.time()
            due = db.get_due_schedules(now)
            for sch in due:
                try:
                    run_id = uuid.uuid4().hex[:8]
                    db.create_run(run_id, sch["prompt"])

                    def _persist(run_meta, records, sid=sch["id"]):
                        db.save_run(run_meta, records)
                        db.update_run_status(run_id, run_meta["status"])
                        # Notify webhooks
                        _notify_webhooks(run_meta)
                        # Mark schedule as run; schedule next
                        next_at = time.time() + sch["interval_seconds"]
                        db.update_schedule_after_run(sid, run_id, next_at)

                    execute_run(run_id, sch["prompt"], persist_fn=_persist)
                except Exception as e:
                    print(f"[scheduler] error running schedule {sch.get('id')}: {e}")
        except Exception as e:
            print(f"[scheduler] loop error: {e}")

        _scheduler_stop.wait(2)  # poll every 2 seconds


def _notify_webhooks(run_meta: Dict) -> None:
    """Fire webhooks for the run_done event."""
    import requests as _req
    event = "run_done" if run_meta.get("status") == "done" else "run_failed"
    hooks = db.get_active_webhooks(event)
    for h in hooks:
        try:
            payload = {
                "event": event,
                "run_id": run_meta.get("id"),
                "prompt": run_meta.get("prompt"),
                "total_records": run_meta.get("total_records"),
                "status": run_meta.get("status"),
                "finished_at": run_meta.get("finished_at"),
            }
            if h["type"] == "slack":
                text = (
                    f":rocket: *Data Intelligence Platform* - Run `{run_meta.get('id')}` {event.replace('_', ' ')}!\n"
                    f"*Prompt:* {run_meta.get('prompt')}\n"
                    f"*Records:* {run_meta.get('total_records')}\n"
                    f"*Status:* {run_meta.get('status')}"
                )
                _req.post(h["url"], json={"text": text}, timeout=4)
            elif h["type"] == "discord":
                text = (
                    f"**Data Intelligence Platform** - Run `{run_meta.get('id')}` {event.replace('_', ' ')}!\n"
                    f"**Prompt:** {run_meta.get('prompt')}\n"
                    f"**Records:** {run_meta.get('total_records')}"
                )
                _req.post(h["url"], json={"content": text}, timeout=4)
            else:
                _req.post(h["url"], json=payload, timeout=4)
        except Exception as e:
            print(f"[webhook] failed to fire {h.get('id')}: {e}")


def start() -> None:
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="scheduler")
    _scheduler_thread.start()
    print("[scheduler] started")


def stop() -> None:
    _scheduler_stop.set()