"""
Flask API for the AI-Powered Data Intelligence Platform.

Endpoints:
  GET  /                       -> dashboard
  POST /api/runs               -> start a new collection run from a prompt
  GET  /api/runs               -> list runs
  GET  /api/runs/<id>          -> get a single run (workflow + intent)
  GET  /api/runs/<id>/records  -> list records for a run (filter/sort)
  GET  /api/runs/<id>/export   -> export dataset (csv/json)
  GET  /api/runs/<id>/live     -> live status of an in-flight run
  POST /api/runs/<id>/replay   -> re-run with the same prompt
  DELETE /api/runs/<id>        -> delete a run
  GET  /api/stats              -> global platform stats
  POST /api/preview            -> preview parsed intent for a prompt (no execution)
"""

from __future__ import annotations
import io
import csv
import json
import time
import uuid
import socket
import secrets
import threading
from typing import Any, Dict, List

# Global socket-level safety net: no outbound HTTP call can hang beyond this,
# even if a specific requests.get call forgets to set a timeout.
socket.setdefaulttimeout(10)

from flask import Flask, jsonify, request, send_file, render_template, abort
from flask_cors import CORS

from data_intelligence import database as db
from data_intelligence import scheduler
from data_intelligence.ai_engine import get_engine
from data_intelligence import orchestrator
from data_intelligence.ai_summarizer import summarize_run
from data_intelligence.demo import seed_demo_runs


app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)
db.init_db()
scheduler.start()


# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------

@app.route("/api/preview", methods=["POST"])
def preview():
    """Parse a prompt without executing it - shows the user what we'd collect."""
    body = request.get_json(force=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    intent = get_engine().parse(prompt)
    return jsonify({"intent": intent.to_dict()})


@app.route("/api/runs", methods=["POST"])
def create_run():
    body = request.get_json(force=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    run_id = uuid.uuid4().hex[:8]
    db.create_run(run_id, prompt)

    # Run async
    def _persist(run_meta: Dict[str, Any], records: List[Dict[str, Any]]):
        db.save_run(run_meta, records)
        db.update_run_status(run_id, run_meta["status"])

    orchestrator.execute_async(run_id, prompt, persist_fn=_persist)
    return jsonify({"run_id": run_id, "status": "running"}), 202


@app.route("/api/runs", methods=["GET"])
def list_runs():
    return jsonify({"runs": db.list_runs()})


@app.route("/api/runs/<run_id>", methods=["GET"])
def get_run(run_id: str):
    detail = db.get_run_detail(run_id)
    if not detail:
        # Maybe still running - fall back to orchestrator's live state
        live = orchestrator.get_run(run_id)
        if live:
            return jsonify({"run": live, "live": True})
        abort(404)
    return jsonify({"run": detail, "live": False})


@app.route("/api/runs/<run_id>/live", methods=["GET"])
def get_run_live(run_id: str):
    live = orchestrator.get_run(run_id)
    if not live:
        # Try DB
        detail = db.get_run_detail(run_id)
        if detail:
            return jsonify({"run": detail, "live": False})
        abort(404)
    return jsonify({"run": live, "live": True})


@app.route("/api/runs/<run_id>/records", methods=["GET"])
def get_run_records(run_id: str):
    q = request.args.get("q")
    source = request.args.get("source")
    min_score = request.args.get("min_score", type=int)
    sort = request.args.get("sort", "score_desc")
    limit = min(int(request.args.get("limit", 200)), 500)
    records = db.list_records(run_id, q=q, source=source, min_score=min_score, sort=sort, limit=limit)
    sources = db.distinct_sources(run_id)
    return jsonify({"records": records, "sources": sources})


@app.route("/api/runs/<run_id>/export", methods=["GET"])
def export_run(run_id: str):
    fmt = (request.args.get("format") or "json").lower()
    records = db.list_records(run_id, limit=500)
    if not records:
        return jsonify({"error": "no records to export"}), 404

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=[
            "id", "type", "source", "title", "company", "location",
            "url", "skills", "industries", "score", "published_at", "description",
        ])
        writer.writeheader()
        for r in records:
            writer.writerow({
                "id": r.get("id"),
                "type": r.get("type"),
                "source": r.get("source"),
                "title": r.get("title"),
                "company": r.get("company"),
                "location": r.get("location"),
                "url": r.get("url"),
                "skills": ", ".join(r.get("skills") or []),
                "industries": ", ".join(r.get("industries") or []),
                "score": r.get("score"),
                "published_at": r.get("published_at"),
                "description": (r.get("description") or "")[:500],
            })
        data = buf.getvalue().encode("utf-8")
        return send_file(
            io.BytesIO(data),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"dataset_{run_id}.csv",
        )

    # default: JSON
    return send_file(
        io.BytesIO(json.dumps(records, indent=2).encode("utf-8")),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"dataset_{run_id}.json",
    )


@app.route("/api/runs/<run_id>/replay", methods=["POST"])
def replay_run(run_id: str):
    detail = db.get_run_detail(run_id)
    if not detail:
        abort(404)
    prompt = detail["prompt"]
    new_id = uuid.uuid4().hex[:8]
    db.create_run(new_id, prompt)

    def _persist(run_meta, records):
        db.save_run(run_meta, records)
        db.update_run_status(new_id, run_meta["status"])

    orchestrator.execute_async(new_id, prompt, persist_fn=_persist)
    return jsonify({"run_id": new_id, "status": "running"}), 202


@app.route("/api/runs/<run_id>", methods=["DELETE"])
def delete_run(run_id: str):
    ok = db.delete_run(run_id)
    return jsonify({"deleted": ok})


@app.route("/api/stats", methods=["GET"])
def stats():
    return jsonify(db.stats())


# ----------------------------------------------------------------------
# New endpoints: demo, summary, source health, schedules, webhooks, share
# ----------------------------------------------------------------------

@app.route("/api/demo/load", methods=["POST"])
def load_demo():
    """Seed demo runs (jobs/leads/sponsors/repos/market/news). Idempotent."""
    run_ids = seed_demo_runs()
    return jsonify({"seeded": run_ids, "count": len(run_ids)})


@app.route("/api/runs/<run_id>/summary", methods=["GET"])
def get_run_summary(run_id: str):
    detail = db.get_run_detail(run_id)
    if not detail:
        abort(404)
    records = db.list_records(run_id, limit=500)
    summary = summarize_run(detail, records)
    return jsonify({"summary": summary})


@app.route("/api/runs/<run_id>/source-health", methods=["GET"])
def get_run_source_health(run_id: str):
    """Per-source metrics for this specific run."""
    detail = db.get_run_detail(run_id)
    if not detail:
        abort(404)
    workflow = detail.get("workflow") or {}
    steps = workflow.get("steps") or []
    out = []
    for s in steps:
        if s.get("type") != "collect":
            continue
        out.append({
            "source": s.get("source"),
            "status": s.get("status"),
            "latency_ms": s.get("latency_ms"),
            "records_out": s.get("records_out"),
            "error": s.get("error"),
        })
    return jsonify({"sources": out})


@app.route("/api/source-health", methods=["GET"])
def list_all_source_health():
    """Global source health across all runs."""
    return jsonify({"sources": db.list_source_health()})


@app.route("/api/schedules", methods=["POST"])
def create_schedule():
    body = request.get_json(force=True) or {}
    prompt = (body.get("prompt") or "").strip()
    interval_seconds = int(body.get("interval_seconds") or 3600)
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    schedule_id = uuid.uuid4().hex[:8]
    next_run_at = time.time() + interval_seconds
    db.create_schedule(schedule_id, prompt, interval_seconds, next_run_at)
    return jsonify({"schedule_id": schedule_id, "next_run_at": next_run_at}), 201


@app.route("/api/schedules", methods=["GET"])
def list_schedules():
    items = db.list_schedules()
    return jsonify({"schedules": items})


@app.route("/api/schedules/<schedule_id>", methods=["DELETE"])
def delete_schedule(schedule_id: str):
    ok = db.delete_schedule(schedule_id)
    return jsonify({"deleted": ok})


@app.route("/api/schedules/<schedule_id>/toggle", methods=["POST"])
def toggle_schedule(schedule_id: str):
    body = request.get_json(force=True) or {}
    enabled = bool(body.get("enabled", True))
    db.toggle_schedule(schedule_id, enabled)
    return jsonify({"enabled": enabled})


@app.route("/api/webhooks", methods=["POST"])
def create_webhook():
    body = request.get_json(force=True) or {}
    url = (body.get("url") or "").strip()
    type_ = body.get("type") or "generic"
    event = body.get("event") or "run_done"
    if not url:
        return jsonify({"error": "url required"}), 400
    webhook_id = uuid.uuid4().hex[:8]
    db.create_webhook(webhook_id, url, type_, event)
    return jsonify({"webhook_id": webhook_id}), 201


@app.route("/api/webhooks", methods=["GET"])
def list_webhooks():
    return jsonify({"webhooks": db.list_webhooks()})


@app.route("/api/webhooks/<webhook_id>", methods=["DELETE"])
def delete_webhook(webhook_id: str):
    ok = db.delete_webhook(webhook_id)
    return jsonify({"deleted": ok})


@app.route("/api/runs/<run_id>/share", methods=["POST"])
def create_share(run_id: str):
    detail = db.get_run_detail(run_id)
    if not detail:
        abort(404)
    token = secrets.token_urlsafe(12)
    db.create_share_link(token, run_id)
    return jsonify({"token": token, "url": f"/share/{token}"})


@app.route("/api/share/<token>", methods=["GET"])
def view_share(token: str):
    run = db.get_run_by_share_token(token)
    if not run:
        abort(404)
    records = db.list_records(run["id"], limit=200)
    return jsonify({"run": run, "records": records})


@app.route("/api/runs/compare", methods=["GET"])
def compare_runs():
    a = request.args.get("a")
    b = request.args.get("b")
    if not a or not b:
        return jsonify({"error": "a and b required"}), 400
    run_a = db.get_run_detail(a)
    run_b = db.get_run_detail(b)
    if not run_a or not run_b:
        abort(404)
    recs_a = db.list_records(a, limit=500)
    recs_b = db.list_records(b, limit=500)
    summary_a = summarize_run(run_a, recs_a)
    summary_b = summarize_run(run_b, recs_b)

    from collections import Counter
    src_a = Counter(r.get("source") for r in recs_a)
    src_b = Counter(r.get("source") for r in recs_b)
    scores_a = [r.get("score") or 0 for r in recs_a]
    scores_b = [r.get("score") or 0 for r in recs_b]

    return jsonify({
        "a": {"run": run_a, "summary": summary_a},
        "b": {"run": run_b, "summary": summary_b},
        "diff": {
            "a_records": len(recs_a),
            "b_records": len(recs_b),
            "a_avg_score": round(sum(scores_a)/len(scores_a), 1) if scores_a else 0,
            "b_avg_score": round(sum(scores_b)/len(scores_b), 1) if scores_b else 0,
            "a_sources": dict(src_a),
            "b_sources": dict(src_b),
        }
    })


# ----------------------------------------------------------------------
# Error handlers
# ----------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "server error", "detail": str(e)}), 500


if __name__ == "__main__":
    # debug=False to avoid reloader issues during testing; use `python app.py`
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True, use_reloader=False)