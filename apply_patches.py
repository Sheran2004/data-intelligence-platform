"""
apply_patches.py - One-shot patch script for the Data Intelligence Platform.

Fixes 4 things in your project:
  1. data_intelligence/database.py - add watchlist + notifications tables and helpers
  2. app.py                          - add missing endpoints (clear-all, ab-test, watchlist,
                                         notifications, bulk-export, replay-diff, quality, sources)
  3. templates/index.html            - add bulk-export modal
  4. static/js/app.js                - rewrite to match actual HTML element IDs

Usage (from project root):
  python apply_patches.py

It writes *.bak backups next to each touched file. If a patch has already been
applied it is a no-op for that file.
"""
from __future__ import annotations
import os
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"  backup -> {bak.name}")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, content: str) -> None:
    _backup(path)
    path.write_text(content, encoding="utf-8")
    print(f"  patched {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# 1. database.py - add tables to init_db() and new helpers at end of file
# ---------------------------------------------------------------------------
DATABASE_NEW_TABLES = """
            CREATE TABLE IF NOT EXISTS watchlist (
                id TEXT PRIMARY KEY,
                record_id TEXT,
                run_id TEXT,
                url TEXT,
                title TEXT,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                kind TEXT,
                title TEXT,
                message TEXT,
                run_id TEXT,
                created_at REAL,
                read_at REAL
            );
"""

DATABASE_NEW_FUNCS = '''


# ======================================================================
# Watchlist
# ======================================================================

def add_watchlist(item_id: str, record_id: str, run_id: str, url: str, title: str) -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO watchlist (id, record_id, run_id, url, title, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item_id, record_id, run_id, url, title, time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def list_watchlist() -> List[Dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            rows = conn.execute("SELECT * FROM watchlist ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def remove_watchlist(item_id: str) -> bool:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM watchlist WHERE id = ?", (item_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def find_watchlist_by_record(record_id: str) -> Optional[Dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM watchlist WHERE record_id = ?", (record_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


# ======================================================================
# Notifications
# ======================================================================

def add_notification(notif_id: str, kind: str, title: str, message: str, run_id: str = "") -> None:
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO notifications (id, kind, title, message, run_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (notif_id, kind, title, message, run_id, time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def list_notifications() -> List[Dict[str, Any]]:
    with _DB_LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM notifications ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def mark_notification_read(notif_id: str) -> bool:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE notifications SET read_at = ? WHERE id = ?",
                (time.time(), notif_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def delete_notification(notif_id: str) -> bool:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM notifications WHERE id = ?", (notif_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def clear_notifications() -> int:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.execute("DELETE FROM notifications")
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


# ======================================================================
# Clear all runs
# ======================================================================

def delete_all_runs() -> int:
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            # Manually clean records first (FK cascade is not enforced unless
            # PRAGMA foreign_keys = ON, so be explicit for portability).
            cur.execute("DELETE FROM records")
            cur.execute("DELETE FROM share_links")
            cur.execute("DELETE FROM runs")
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()
'''


def patch_database() -> bool:
    path = ROOT / "data_intelligence" / "database.py"
    if not path.exists():
        print(f"  SKIP: {path} not found")
        return False
    src = _read(path)

    changed = False
    # 1) insert new tables inside init_db() block
    marker_tables = "CREATE TABLE IF NOT EXISTS source_health ("
    if marker_tables in src and "CREATE TABLE IF NOT EXISTS watchlist (" not in src:
        src = src.replace(
            marker_tables,
            DATABASE_NEW_TABLES.strip() + "\n            " + marker_tables,
            1,
        )
        changed = True

    # 2) append new helpers at end
    if "def delete_all_runs" not in src:
        src = src.rstrip() + "\n" + DATABASE_NEW_FUNCS
        changed = True

    if changed:
        _write(path, src)
    else:
        print(f"  database.py already patched")
    return changed


# ---------------------------------------------------------------------------
# 2. app.py - add new endpoints before "# Error handlers" block
# ---------------------------------------------------------------------------
APP_NEW_ENDPOINTS = '''


# ======================================================================
# Clear all runs (used by sidebar "Clear" button)
# ======================================================================

@app.route("/api/runs", methods=["DELETE"])
def delete_all_runs_route():
    n = db.delete_all_runs()
    return jsonify({"deleted": n})


# ======================================================================
# A/B test - run two prompts in parallel and return both run_ids
# ======================================================================

@app.route("/api/ab-test", methods=["POST"])
def ab_test_route():
    body = request.get_json(force=True) or {}
    pa = (body.get("prompt_a") or body.get("prompt1") or "").strip()
    pb = (body.get("prompt_b") or body.get("prompt2") or "").strip()
    if not pa or not pb:
        return jsonify({"error": "prompt_a and prompt_b required"}), 400
    ra = uuid.uuid4().hex[:8]
    rb = uuid.uuid4().hex[:8]
    db.create_run(ra, pa)
    db.create_run(rb, pb)

    def _persist_a(meta, records):
        db.save_run(meta, records)
        db.update_run_status(ra, meta["status"])

    def _persist_b(meta, records):
        db.save_run(meta, records)
        db.update_run_status(rb, meta["status"])

    orchestrator.execute_async(ra, pa, persist_fn=_persist_a)
    orchestrator.execute_async(rb, pb, persist_fn=_persist_b)

    db.add_notification(
        uuid.uuid4().hex[:8], "ab_test", "A/B test started",
        f"Prompt A: {pa[:60]} | Prompt B: {pb[:60]}", ra,
    )
    return jsonify({"run_a": ra, "run_b": rb, "status": "running"}), 202


# ======================================================================
# Watchlist
# ======================================================================

@app.route("/api/watchlist", methods=["GET"])
def list_watchlist_route():
    return jsonify({"items": db.list_watchlist()})


@app.route("/api/watchlist", methods=["POST"])
def add_watchlist_route():
    body = request.get_json(force=True) or {}
    record_id = (body.get("record_id") or "").strip()
    run_id = body.get("run_id") or ""
    url = body.get("url") or ""
    title = body.get("title") or ""
    if not record_id and not url:
        return jsonify({"error": "record_id or url required"}), 400
    item_id = uuid.uuid4().hex[:8]
    db.add_watchlist(item_id, record_id, run_id, url, title)
    return jsonify({"id": item_id}), 201


@app.route("/api/watchlist/<item_id>", methods=["DELETE"])
def remove_watchlist_route(item_id: str):
    ok = db.remove_watchlist(item_id)
    return jsonify({"deleted": ok})


# ======================================================================
# Notifications
# ======================================================================

@app.route("/api/notifications", methods=["GET"])
def list_notifications_route():
    return jsonify({"items": db.list_notifications()})


@app.route("/api/notifications/<notif_id>", methods=["PATCH"])
def mark_notification_read_route(notif_id: str):
    ok = db.mark_notification_read(notif_id)
    return jsonify({"marked": ok})


@app.route("/api/notifications/<notif_id>", methods=["DELETE"])
def delete_notification_route(notif_id: str):
    ok = db.delete_notification(notif_id)
    return jsonify({"deleted": ok})


@app.route("/api/notifications/clear", methods=["POST"])
def clear_notifications_route():
    n = db.clear_notifications()
    return jsonify({"cleared": n})


@app.route("/api/admin/notify", methods=["POST"])
def admin_notify_route():
    body = request.get_json(force=True) or {}
    nid = uuid.uuid4().hex[:8]
    db.add_notification(
        nid,
        body.get("kind") or "info",
        body.get("title") or "Notification",
        body.get("message") or "",
        body.get("run_id") or "",
    )
    return jsonify({"id": nid}), 201


# ======================================================================
# Bulk export - zip multiple runs into a single archive
# ======================================================================

@app.route("/api/bulk-export", methods=["POST"])
def bulk_export_route():
    body = request.get_json(force=True) or {}
    run_ids = body.get("run_ids") or []
    fmt = (body.get("format") or "json").lower()
    if not run_ids:
        return jsonify({"error": "run_ids required"}), 400
    import zipfile
    buf = io.BytesIO()
    written = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rid in run_ids:
            recs = db.list_records(rid, limit=500)
            if not recs:
                continue
            if fmt == "csv":
                sbuf = io.StringIO()
                writer = csv.DictWriter(sbuf, fieldnames=[
                    "id", "type", "source", "title", "company", "location",
                    "url", "skills", "industries", "score", "published_at", "description",
                ])
                writer.writeheader()
                for r in recs:
                    writer.writerow({
                        "id": r.get("id"), "type": r.get("type"),
                        "source": r.get("source"), "title": r.get("title"),
                        "company": r.get("company"), "location": r.get("location"),
                        "url": r.get("url"),
                        "skills": ", ".join(r.get("skills") or []),
                        "industries": ", ".join(r.get("industries") or []),
                        "score": r.get("score"),
                        "published_at": r.get("published_at"),
                        "description": (r.get("description") or "")[:500],
                    })
                zf.writestr(f"dataset_{rid}.csv", sbuf.getvalue())
            else:
                zf.writestr(f"dataset_{rid}.json", json.dumps(recs, indent=2))
            written += 1
    data = buf.getvalue()
    if not written:
        return jsonify({"error": "no records in selected runs"}), 404
    return send_file(
        io.BytesIO(data),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"bulk_export_{int(time.time())}.zip",
    )


# ======================================================================
# Per-run replay & diff (sync - waits up to 90s for replay to finish)
# ======================================================================

@app.route("/api/runs/<run_id>/replay-diff", methods=["POST"])
def replay_diff_route(run_id: str):
    detail = db.get_run_detail(run_id)
    if not detail:
        abort(404)
    from data_intelligence.ai_summarizer import summarize_run
    prompt = detail["prompt"]
    new_id = uuid.uuid4().hex[:8]
    db.create_run(new_id, prompt)

    def _persist(meta, records):
        db.save_run(meta, records)
        db.update_run_status(new_id, meta["status"])

    orchestrator.execute_async(new_id, prompt, persist_fn=_persist)

    deadline = time.time() + 90
    finished_status = None
    while time.time() < deadline:
        time.sleep(0.6)
        live = orchestrator.get_run(new_id)
        if live and live.get("status") in ("done", "failed"):
            finished_status = live.get("status")
            break
        det = db.get_run_detail(new_id)
        if det and det.get("status") in ("done", "failed"):
            finished_status = det.get("status")
            break

    a_recs = db.list_records(run_id, limit=500)
    b_det = db.get_run_detail(new_id)
    b_recs = db.list_records(new_id, limit=500)
    if not b_det:
        return jsonify({"error": "replay did not finish in time"}), 504

    a_summary = summarize_run(detail, a_recs)
    b_summary = summarize_run(b_det, b_recs)

    from collections import Counter
    sa = Counter(r.get("source") for r in a_recs)
    sb = Counter(r.get("source") for r in b_recs)
    scores_a = [r.get("score") or 0 for r in a_recs]
    scores_b = [r.get("score") or 0 for r in b_recs]

    a_titles = [(r.get("title") or "").strip() for r in a_recs if r.get("title")]
    b_titles = [(r.get("title") or "").strip() for r in b_recs if r.get("title")]
    a_set = {t.lower() for t in a_titles}
    b_set = {t.lower() for t in b_titles}
    only_a = [t for t in a_titles if t.lower() not in b_set][:5]
    only_b = [t for t in b_titles if t.lower() not in a_set][:5]

    diff = {
        "a_records": len(a_recs),
        "b_records": len(b_recs),
        "records_delta": len(b_recs) - len(a_recs),
        "a_avg_score": round(sum(scores_a)/len(scores_a), 1) if scores_a else 0,
        "b_avg_score": round(sum(scores_b)/len(scores_b), 1) if scores_b else 0,
        "score_delta": round((sum(scores_b)/max(1, len(scores_b))) - (sum(scores_a)/max(1, len(scores_a))), 1),
        "a_sources": dict(sa),
        "b_sources": dict(sb),
        "only_in_original": only_a,
        "only_in_replay": only_b,
        "replay_status": finished_status or "unknown",
    }
    return jsonify({
        "original_run_id": run_id,
        "replay_run_id": new_id,
        "diff": diff,
        "a_summary": a_summary,
        "b_summary": b_summary,
    })


# ======================================================================
# Per-run data quality
# ======================================================================

@app.route("/api/runs/<run_id>/quality", methods=["GET"])
def quality_route(run_id: str):
    from data_intelligence import data_quality
    detail = db.get_run_detail(run_id)
    if not detail:
        abort(404)
    recs = db.list_records(run_id, limit=500)
    report = data_quality.quality_report_for_records(recs)

    checks = []
    total = report.get("total", 0)
    ok_urls = report.get("ok_urls", 0)
    mock_urls = report.get("mock_urls", 0)
    pii_records = report.get("pii_records", 0)
    completeness_avg = report.get("completeness_avg", 0)

    checks.append({
        "name": "URLs valid",
        "passed": ok_urls == total,
        "detail": f"{ok_urls}/{total} records have a parseable URL",
    })
    checks.append({
        "name": "No mock URLs",
        "passed": mock_urls == 0,
        "detail": f"{mock_urls} records use mock/example URLs" if mock_urls else "All URLs are real",
    })
    checks.append({
        "name": "No PII detected",
        "passed": pii_records == 0,
        "detail": f"{pii_records} records contain emails/phones" if pii_records else "No PII found",
    })
    checks.append({
        "name": "Average completeness >= 50%",
        "passed": completeness_avg >= 0.5,
        "detail": f"Average field completeness is {round(completeness_avg*100)}%",
    })
    checks.append({
        "name": "Dataset size >= 10 records",
        "passed": total >= 10,
        "detail": f"{total} records collected",
    })

    score = sum(20 for c in checks if c["passed"])

    narrative = (
        f"This dataset scores {score}/100. "
        + ("Looks healthy and ready to ship." if score >= 80 else
           "Some checks need attention - review details below." if score >= 40 else
           "Significant quality issues - re-run with stricter sources.")
    )

    return jsonify({
        "quality": {
            "overall_score": score,
            "total_records": total,
            "valid_urls": ok_urls,
            "mock_urls": mock_urls,
            "duplicates": total - len({(r.get("url") or r.get("id")) for r in recs}),
            "checks": checks,
            "narrative": narrative,
            "fields_present_pct": report.get("fields_present_pct", {}),
        }
    })


# ======================================================================
# Per-run sources (for source explorer)
# ======================================================================

@app.route("/api/runs/<run_id>/sources", methods=["GET"])
def run_sources_route(run_id: str):
    detail = db.get_run_detail(run_id)
    if not detail:
        abort(404)
    workflow = detail.get("workflow") or {}
    steps = [s for s in (workflow.get("steps") or []) if s.get("type") == "collect"]
    return jsonify({"sources": steps})

'''


def patch_app() -> bool:
    path = ROOT / "app.py"
    if not path.exists():
        print(f"  SKIP: {path} not found")
        return False
    src = _read(path)
    if "delete_all_runs_route" in src:
        print("  app.py already patched")
        return False

    marker = "# ----------------------------------------------------------------------\n# Error handlers"
    if marker not in src:
        marker = 'if __name__ == "__main__":'
    if marker not in src:
        print(f"  ERROR: marker not found in app.py")
        return False
    src = src.replace(marker, APP_NEW_ENDPOINTS + "\n\n" + marker, 1)
    _write(path, src)
    return True


# ---------------------------------------------------------------------------
# 3. templates/index.html - add bulk-export-modal
# ---------------------------------------------------------------------------
INDEX_NEW_MODAL = '''
<!-- Bulk Export modal -->
<div class="modal" id="bulk-export-modal" hidden>
  <div class="modal-card wide">
    <div class="modal-header">
      <div class="modal-title">📦 Bulk Export</div>
      <button class="modal-close" data-close="bulk-export-modal">×</button>
    </div>
    <div class="modal-body">
      <p style="color:var(--text-mute);margin-bottom:10px;">Pick the runs to include in one ZIP archive:</p>
      <div style="margin-bottom:10px;">
        <button class="btn-secondary" id="bulk-select-all" style="font-size:11px;padding:4px 8px;">Select all</button>
        <button class="btn-secondary" id="bulk-select-none" style="font-size:11px;padding:4px 8px;">Clear</button>
      </div>
      <select id="bulk-export-runs" multiple size="8" style="width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--bg-2);color:var(--text);"></select>
      <label style="font-size:12px;color:var(--text-mute);text-transform:uppercase;display:block;margin-top:14px;">Format (per file inside ZIP)</label>
      <select id="bulk-export-fmt" style="width:100%;margin-top:6px;padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--bg-2);color:var(--text);">
        <option value="json">JSON</option>
        <option value="csv">CSV</option>
      </select>
    </div>
    <div class="modal-footer">
      <button class="btn-secondary" data-close="bulk-export-modal">Cancel</button>
      <button class="btn-primary" id="btn-bulk-go">Download ZIP</button>
    </div>
  </div>
</div>

'''


def patch_index() -> bool:
    path = ROOT / "templates" / "index.html"
    if not path.exists():
        print(f"  SKIP: {path} not found")
        return False
    src = _read(path)
    if 'id="bulk-export-modal"' in src:
        print("  index.html already patched")
        return False
    marker = '<div class="toast-host" id="toast-host"></div>'
    if marker not in src:
        print(f"  ERROR: toast-host marker not found in index.html")
        return False
    src = src.replace(marker, INDEX_NEW_MODAL + "\n" + marker, 1)
    _write(path, src)
    return True


# ---------------------------------------------------------------------------
# 4. static/js/app.js - rewrite to match actual HTML IDs
# ---------------------------------------------------------------------------
NEW_APP_JS_HEAD = "/* AI Data Intelligence Platform - frontend logic (v4)\n"
NEW_APP_JS_MARKER = "Matches the exact modal/element IDs in templates/index.html"


def patch_app_js() -> bool:
    path = ROOT / "static" / "js" / "app.js"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(NEW_APP_JS_HEAD, encoding="utf-8")
    src = _read(path)
    if NEW_APP_JS_MARKER in src:
        print("  app.js already patched (v4)")
        return False
    # We embed the new JS via _write from disk - read full content from sibling
    full = ROOT / "static" / "js" / "app.v4.js"
    if not full.exists():
        # Write our embedded NEW_APP_JS there for transparency, then move
        full.write_text(NEW_APP_JS_BODY, encoding="utf-8")
    content = NEW_APP_JS_HEAD + " * " + NEW_APP_JS_MARKER + "\n */\n" + NEW_APP_JS_BODY
    _write(path, content)
    return True


NEW_APP_JS_BODY = r'''
const API = {
  preview: '/api/preview',
  runs: '/api/runs',
  run: id => `/api/runs/${id}`,
  live: id => `/api/runs/${id}/live`,
  records: id => `/api/runs/${id}/records`,
  export: (id, fmt) => `/api/runs/${id}/export?format=${fmt}`,
  bulkExport: '/api/bulk-export',
  stats: '/api/stats',
  demo: '/api/demo/load',
  summary: id => `/api/runs/${id}/summary`,
  sourceHealth: id => `/api/runs/${id}/source-health`,
  sourceHealthAll: '/api/source-health',
  runSources: id => `/api/runs/${id}/sources`,
  replay: id => `/api/runs/${id}/replay`,
  replayDiff: id => `/api/runs/${id}/replay-diff`,
  quality: id => `/api/runs/${id}/quality`,
  schedules: '/api/schedules',
  schedule: id => `/api/schedules/${id}`,
  scheduleToggle: id => `/api/schedules/${id}/toggle`,
  webhooks: '/api/webhooks',
  webhook: id => `/api/webhooks/${id}`,
  share: id => `/api/runs/${id}/share`,
  shareView: token => `/api/share/${token}`,
  compare: '/api/runs/compare',
  abTest: '/api/ab-test',
  watchlist: '/api/watchlist',
  watchlistItem: id => `/api/watchlist/${id}`,
  notifications: '/api/notifications',
  notificationItem: id => `/api/notifications/${id}`,
  notificationsClear: '/api/notifications/clear',
};

const state = {
  currentRunId: null, run: null, records: [], pollHandle: null, searchDebounce: null,
  theme: localStorage.getItem('dip_theme') || 'dark',
  historyFilter: 'all', historyQuery: '',
  watchlist: [], notifications: [], cachedRuns: [],
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function escapeHtml(str) {
  if (str == null) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function timeAgo(iso) {
  if (!iso) return '';
  const d = new Date(iso); if (isNaN(d.getTime())) return '';
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  if (diff < 86400 * 30) return Math.floor(diff / 86400) + 'd ago';
  return d.toLocaleDateString();
}
function toast(msg, kind = 'info') {
  const host = $('#toast-host') || (() => {
    const h = document.createElement('div');
    h.id = 'toast-host'; h.className = 'toast-host'; document.body.appendChild(h);
    return h;
  })();
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = msg;
  host.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; }, 2400);
  setTimeout(() => el.remove(), 2800);
}
function fetchJSON(url, opts = {}) {
  return fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) }, ...opts,
  }).then(r => {
    if (!r.ok) {
      return r.json().catch(() => ({})).then(j => {
        throw new Error((j && j.error) || `${r.status} ${r.statusText}`);
      });
    }
    return r.json();
  });
}
function on(sel, evt, fn) { const e = $(sel); if (e) e.addEventListener(evt, fn); }
function onAll(sel, evt, fn) { $$(sel).forEach(e => e.addEventListener(evt, fn)); }

function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  const btn = $('#theme-toggle'); if (btn) btn.textContent = t === 'dark' ? '🌙' : '☀️';
  state.theme = t; localStorage.setItem('dip_theme', t);
}
function toggleTheme() {
  applyTheme(state.theme === 'dark' ? 'light' : 'dark');
  if (state.records.length && state.currentRunId) renderCharts(state.records);
}

function openModalById(id) { const m = $('#' + id); if (m) m.hidden = false; }
function closeModalById(id) { const m = $('#' + id); if (m) m.hidden = true; }

function previewPrompt(prompt, targetEl) {
  if (!prompt || !prompt.trim()) { toast('Please enter a prompt first', 'error'); return; }
  fetchJSON(API.preview, { method: 'POST', body: JSON.stringify({ prompt }) })
    .then(({ intent }) => { targetEl.hidden = false; targetEl.textContent = JSON.stringify(intent, null, 2); })
    .catch(err => toast(err.message, 'error'));
}
function launchFromModal() {
  const prompt = $('#modal-prompt').value.trim();
  if (!prompt) { toast('Please enter a prompt', 'error'); return; }
  closeModalById('modal'); startRun(prompt);
}
function launchFromEmpty() {
  const prompt = $('#empty-prompt').value.trim();
  if (!prompt) { toast('Please enter a prompt', 'error'); return; }
  startRun(prompt);
}

function setupVoice(btnSel, inputSel) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { const b = $(btnSel); if (b) b.style.display = 'none'; return; }
  const btn = $(btnSel); const input = $(inputSel);
  if (!btn || !input) return;
  const recognition = new SR();
  recognition.continuous = false; recognition.interimResults = true; recognition.lang = 'en-US';
  btn.addEventListener('click', () => {
    if (btn.classList.contains('listening')) { recognition.stop(); return; }
    try { recognition.start(); btn.classList.add('listening'); toast('Listening…', 'success'); }
    catch (e) { toast('Voice not available: ' + e.message, 'error'); }
  });
  recognition.onresult = (e) => { input.value = Array.from(e.results).map(r => r[0].transcript).join(''); };
  recognition.onerror = (e) => { btn.classList.remove('listening'); toast('Voice error: ' + e.error, 'error'); };
  recognition.onend = () => btn.classList.remove('listening');
}

document.addEventListener('DOMContentLoaded', () => {
  applyTheme(state.theme);
  on('#theme-toggle', 'click', toggleTheme);
  on('#btn-watchlist', 'click', openWatchlistModal);
  on('#btn-notifications', 'click', openNotificationsModal);
  on('#btn-bulk-export', 'click', openBulkExportModal);
  on('#btn-analytics', 'click', openAnalyticsModal);
  on('#btn-new-run', 'click', () => openModalById('modal'));
  on('#btn-load-demo', 'click', loadDemo);
  on('#btn-ab-test', 'click', openAbTestModal);
  on('#history-search', 'input', e => {
    state.historyQuery = (e.target.value || '').toLowerCase();
    renderRunList(state.cachedRuns);
  });
  onAll('.history-tab', 'click', e => {
    state.historyFilter = e.currentTarget.dataset.filter || 'all';
    $$('.history-tab').forEach(t => t.classList.toggle('active', t === e.currentTarget));
    renderRunList(state.cachedRuns);
  });
  on('#btn-clear-history', 'click', clearHistory);
  on('#btn-export-json', 'click', () => exportRun('json'));
  on('#btn-export-csv', 'click', () => exportRun('csv'));
  on('#btn-replay', 'click', replayRun);
  on('#btn-replay-diff', 'click', openReplayDiffModal);
  on('#btn-share', 'click', shareRun);
  on('#btn-compare', 'click', openCompareModal);
  on('#btn-quality', 'click', openQualityModal);
  on('#btn-explore-sources', 'click', openSourcesModal);
  on('#btn-delete', 'click', deleteRun);
  on('#modal-close', 'click', () => closeModalById('modal'));
  on('#modal', 'click', e => { if (e.target.id === 'modal') closeModalById('modal'); });
  onAll('[data-close]', 'click', e => closeModalById(e.currentTarget.dataset.close));
  on('#btn-modal-preview', 'click', () => previewPrompt($('#modal-prompt').value, $('#modal-preview')));
  on('#btn-modal-launch', 'click', launchFromModal);
  on('#btn-empty-launch', 'click', launchFromEmpty);
  on('#btn-empty-preview', 'click', () => previewPrompt($('#empty-prompt').value, $('#empty-preview')));
  on('#btn-empty-load-demo', 'click', loadDemo);
  onAll('.example-chip', 'click', e => {
    const prompt = e.currentTarget.dataset.prompt;
    $('#modal-prompt').value = prompt; openModalById('modal');
  });
  on('#btn-new-schedule', 'click', () => openModalById('schedule-modal'));
  on('#btn-schedule-save', 'click', saveSchedule);
  on('#btn-new-webhook', 'click', () => openModalById('webhook-modal'));
  on('#btn-webhook-save', 'click', saveWebhook);
  on('#btn-run-ab', 'click', runAbTest);
  on('#btn-replay-diff-go', 'click', runReplayDiff);
  on('#btn-bulk-go', 'click', runBulkExport);
  on('#bulk-select-all', 'click', () => {
    const sel = $('#bulk-export-runs'); if (sel) Array.from(sel.options).forEach(o => o.selected = true);
  });
  on('#bulk-select-none', 'click', () => {
    const sel = $('#bulk-export-runs'); if (sel) Array.from(sel.options).forEach(o => o.selected = false);
  });
  on('#btn-notif-clear', 'click', clearAllNotifications);
  setupVoice('#btn-voice-empty', '#empty-prompt');
  setupVoice('#btn-voice-modal', '#modal-prompt');
  on('#search-input', 'input', () => {
    clearTimeout(state.searchDebounce);
    state.searchDebounce = setTimeout(refreshRecords, 200);
  });
  on('#source-filter', 'change', refreshRecords);
  on('#score-filter', 'change', refreshRecords);
  on('#sort-select', 'change', refreshRecords);
  document.addEventListener('keydown', e => {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable)) {
      if (e.key === 'Escape') e.target.blur();
      return;
    }
    if (e.key === '/') { e.preventDefault(); const s = $('#history-search'); if (s) s.focus(); }
    else if (e.key === 'n' || e.key === 'N') { openModalById('modal'); }
    else if (e.key === 'd' || e.key === 'D') { loadDemo(); }
    else if (e.key === 't' || e.key === 'T') { toggleTheme(); }
    else if (e.key === 'b' || e.key === 'B') { openAbTestModal(); }
    else if (e.key === 'Escape') { $$('.modal').forEach(m => { m.hidden = true; }); }
  });
  refreshStats(); refreshRuns(); refreshSchedules(); refreshWebhooks();
  refreshNotifications(); refreshWatchlist();
});

function loadDemo() {
  fetchJSON(API.demo, { method: 'POST' })
    .then(({ seeded, count }) => {
      toast(`Loaded ${count} demo runs`, 'success');
      refreshRuns(); refreshStats();
      if (seeded && seeded.length) selectRun(seeded[0]);
    })
    .catch(err => toast(err.message, 'error'));
}

function startRun(prompt) {
  fetchJSON(API.runs, { method: 'POST', body: JSON.stringify({ prompt }) })
    .then(({ run_id }) => {
      state.currentRunId = run_id;
      $('#empty-state').hidden = true; $('#run-view').hidden = false;
      $('#run-id').textContent = `run-${run_id}`; $('#run-prompt').textContent = prompt;
      $('#empty-prompt').value = '';
      $('#records').innerHTML = '<div class="results-loading"><div class="spinner"></div><div>Starting workflow…</div></div>';
      $('#run-status-bar').hidden = false;
      $('#status-pill').className = 'status-pill';
      $('#status-pill').textContent = 'queued';
      $('#status-text').textContent = 'Initializing…';
      $('#summary-card').hidden = true; $('#charts-card').hidden = true; $('#health-card').hidden = true;
      toast('Workflow started', 'success');
      refreshRuns(); pollRun(run_id);
    })
    .catch(err => toast(err.message, 'error'));
}

function replayRun() {
  if (!state.currentRunId) return;
  fetchJSON(API.replay(state.currentRunId), { method: 'POST' })
    .then(({ run_id }) => {
      state.currentRunId = run_id;
      $('#run-id').textContent = `run-${run_id}`;
      $('#records').innerHTML = '<div class="results-loading"><div class="spinner"></div><div>Replaying workflow…</div></div>';
      toast('Replay started', 'success'); refreshRuns(); pollRun(run_id);
    })
    .catch(err => toast(err.message, 'error'));
}

function deleteRun() {
  if (!state.currentRunId) return;
  if (!confirm('Delete this run and its dataset?')) return;
  fetchJSON(API.run(state.currentRunId), { method: 'DELETE' })
    .then(() => {
      toast('Run deleted', 'success');
      state.currentRunId = null; state.records = []; state.run = null;
      $('#run-view').hidden = true; $('#empty-state').hidden = false;
      refreshRuns(); refreshStats();
    })
    .catch(err => toast(err.message, 'error'));
}

function deleteRunById(id, event) {
  if (event) event.stopPropagation();
  if (!confirm('Delete this run?')) return;
  fetchJSON(API.run(id), { method: 'DELETE' })
    .then(() => {
      toast('Run deleted', 'success');
      if (state.currentRunId === id) {
        state.currentRunId = null; state.run = null; state.records = [];
        $('#run-view').hidden = true; $('#empty-state').hidden = false;
      }
      refreshRuns(); refreshStats();
    })
    .catch(err => toast(err.message, 'error'));
}

function clearHistory() {
  if (!confirm('Delete ALL runs? This cannot be undone.')) return;
  fetchJSON(API.runs, { method: 'DELETE' })
    .then(({ deleted }) => {
      toast(`Cleared ${deleted || 0} runs`, 'success');
      state.currentRunId = null; state.run = null; state.records = [];
      $('#run-view').hidden = true; $('#empty-state').hidden = false;
      state.cachedRuns = []; renderRunList(state.cachedRuns); refreshStats();
    })
    .catch(err => toast(err.message, 'error'));
}

function exportRun(fmt) {
  if (!state.currentRunId) return;
  window.location.href = API.export(state.currentRunId, fmt);
}

function shareRun() {
  if (!state.currentRunId) return;
  fetchJSON(API.share(state.currentRunId), { method: 'POST' })
    .then(({ token, url }) => {
      const fullUrl = `${window.location.origin}${url}`;
      if (navigator.clipboard) navigator.clipboard.writeText(fullUrl).catch(() => {});
      toast('Share link copied!', 'success');
      prompt('Share this public read-only link:', fullUrl);
    })
    .catch(err => toast(err.message, 'error'));
}

function refreshRuns() {
  fetchJSON(API.runs).then(({ runs }) => {
    state.cachedRuns = runs || []; renderRunList(state.cachedRuns);
  }).catch(err => toast(err.message, 'error'));
}

function renderRunList(runs) {
  const list = $('#run-list'); if (!list) return;
  let filtered = runs || [];
  if (state.historyFilter && state.historyFilter !== 'all') {
    filtered = filtered.filter(r => (r.status || '').toLowerCase() === state.historyFilter);
  }
  if (state.historyQuery) filtered = filtered.filter(r => (r.prompt || '').toLowerCase().includes(state.historyQuery));
  if (!filtered.length) {
    list.innerHTML = '<li style="background:transparent;border:none;color:var(--text-mute);padding:8px;font-style:italic;">No runs match</li>';
    return;
  }
  list.innerHTML = filtered.map(r => `
    <li class="${r.id === state.currentRunId ? 'active' : ''}" data-id="${r.id}">
      <button class="rl-del" data-del="${r.id}" title="Delete this run">×</button>
      <div class="rl-prompt">${escapeHtml(r.prompt)}</div>
      <div class="rl-meta">
        <span><span class="status-dot ${escapeHtml(r.status)}"></span> ${escapeHtml(r.status)}</span>
        <span>${r.total_records} rec · ${timeAgo(new Date(r.created_at * 1000).toISOString())}</span>
      </div>
    </li>`).join('');
  $$('#run-list li[data-id]').forEach(li => {
    li.addEventListener('click', e => {
      if (e.target.closest('[data-del]')) return;
      selectRun(li.dataset.id);
    });
  });
  $$('#run-list [data-del]').forEach(btn => {
    btn.addEventListener('click', e => deleteRunById(btn.dataset.del, e));
  });
}

function selectRun(id) {
  state.currentRunId = id;
  $('#empty-state').hidden = true; $('#run-view').hidden = false;
  renderRunList(state.cachedRuns);
  fetchJSON(API.live(id))
    .then(({ run, live }) => {
      applyRun(run); loadRunExtras(id);
      if (!live && run.status !== 'running') refreshRecords(); else pollRun(id);
    })
    .catch(() => {
      $('#empty-state').hidden = false; $('#run-view').hidden = true;
      toast('Run not found', 'error');
    });
}

function refreshStats() {
  fetchJSON(API.stats).then(s => {
    const sr = $('#stat-runs'); if (sr) sr.textContent = s.runs || 0;
    const srec = $('#stat-records'); if (srec) srec.textContent = s.records || 0;
    const st = $('#stat-types'); if (st) st.textContent = Object.keys(s.by_type || {}).length;
  }).catch(() => {});
}

function pollRun(runId) {
  clearInterval(state.pollHandle);
  let sidebarTick = 0;
  const tick = () => {
    fetchJSON(API.live(runId))
      .then(({ run, live }) => {
        applyRun(run);
        if (run.status !== 'running') {
          clearInterval(state.pollHandle);
          refreshRuns(); refreshRecords(); refreshStats(); loadRunExtras(runId);
          addClientNotification({
            kind: run.status === 'done' ? 'success' : 'error',
            title: run.status === 'done' ? 'Run completed' : 'Run failed',
            message: (run.prompt || '').slice(0, 80), run_id: runId,
          });
          toast(`Workflow ${run.status}`, run.status === 'done' ? 'success' : 'error');
          return;
        }
        sidebarTick = (sidebarTick + 1) % 3;
        if (sidebarTick === 0) refreshRuns();
      })
      .catch(() => clearInterval(state.pollHandle));
  };
  state.pollHandle = setInterval(tick, 1000); tick();
}

function addClientNotification(notif) {
  fetchJSON('/api/admin/notify', { method: 'POST', body: JSON.stringify(notif) })
    .then(() => refreshNotifications()).catch(() => {});
}

function applyRun(run) {
  state.run = run;
  $('#run-id').textContent = `run-${run.id}`;
  $('#run-prompt').textContent = run.prompt;
  const pill = $('#status-pill');
  pill.className = 'status-pill ' + (run.status || '');
  pill.textContent = run.status;
  $('#status-text').textContent = run.status === 'running'
    ? 'Workflow is running…'
    : run.status === 'failed'
      ? (run.error || 'Workflow failed')
      : `${(run.workflow || {}).total_records || 0} record(s) collected`;
  renderSteps(run.workflow); renderIntent(run.intent); renderHealth(run.workflow);
  if (run.status === 'running' && Array.isArray(run.records)) {
    $('#records').innerHTML = '<div class="results-loading"><div class="spinner"></div><div>Collecting…</div></div>';
  }
}

function loadRunExtras(runId) {
  if (!runId) return;
  fetchJSON(API.summary(runId)).then(({ summary }) => renderSummary(summary)).catch(() => {});
}

function renderSummary(summary) {
  if (!summary) return;
  $('#summary-card').hidden = false;
  $('#summary-body').innerHTML = summary.narrative || '';
  const insights = summary.insights || [];
  $('#summary-insights').innerHTML = insights.map(i => `
    <div class="insight">
      <div class="insight-label">${escapeHtml(i.label)}</div>
      <div class="insight-value">${escapeHtml(i.value)}</div>
    </div>`).join('');
}

function renderSteps(workflow) {
  const steps = (workflow && workflow.steps) || [];
  $('#steps').innerHTML = steps.map(s => `
    <div class="step ${escapeHtml(s.status)}">
      <div class="step-icon">${
        s.status === 'done' ? '✓' : s.status === 'failed' ? '✕' :
        s.status === 'running' ? '⟳' : '·'}</div>
      <div>
        <div class="step-name">${escapeHtml(s.name)}</div>
        <div class="step-meta">${escapeHtml(s.message || '')} ${s.records_out ? '· ' + s.records_out + ' rec' : ''} ${s.latency_ms ? '· ' + s.latency_ms + 'ms' : ''}</div>
      </div>
      ${s.source ? `<div class="step-source">${escapeHtml(s.source)}</div>` : ''}
    </div>`).join('');
}

function renderIntent(intent) {
  if (!intent) { $('#intent-grid').innerHTML = ''; return; }
  const items = [
    { label: 'Data type', val: intent.data_type },
    { label: 'Skills', val: intent.skills || [], kind: 'pills-accent' },
    { label: 'Locations', val: intent.locations || [], kind: 'pills' },
    { label: 'Industries', val: intent.industries || [], kind: 'pills' },
    { label: 'Company size', val: intent.company_sizes || [], kind: 'pills' },
    { label: 'Time window', val: intent.time_window_hours ? `${intent.time_window_hours}h` : '—' },
    { label: 'Freshness', val: intent.freshness || 'any' },
    { label: 'Max results', val: intent.max_results },
  ];
  $('#intent-grid').innerHTML = items.map(i => `
    <div class="intent-item">
      <label>${escapeHtml(i.label)}</label>
      ${Array.isArray(i.val)
        ? `<div class="val-pills">${i.val.length ? i.val.map(v => `<span class="pill ${i.kind === 'pills-accent' ? 'accent' : ''}">${escapeHtml(v)}</span>`).join('') : '<span style="color:var(--text-mute)">—</span>'}</div>`
        : `<div class="val">${escapeHtml(String(i.val || '—'))}</div>`}
    </div>`).join('');
}

function renderHealth(workflow) {
  const steps = (workflow && workflow.steps) || [];
  const collectSteps = steps.filter(s => s.type === 'collect');
  if (!collectSteps.length) { $('#health-card').hidden = true; return; }
  $('#health-card').hidden = false;
  $('#health-grid').innerHTML = collectSteps.map(s => {
    let cls = 'good';
    if (s.status === 'failed' || s.status === 'fail') cls = 'bad';
    else if (s.latency_ms > 8000) cls = 'warn';
    return `<div class="health-item">
      <div class="health-dot ${cls}"></div>
      <div class="health-name">${escapeHtml(s.source || 'unknown')}</div>
      <div class="health-time">${s.latency_ms ? s.latency_ms + 'ms' : '-'}</div>
    </div>`;
  }).join('');
}

function renderCharts(records) {
  if (!records || !records.length) { $('#charts-card').hidden = true; return; }
  $('#charts-card').hidden = false;
  const isDark = state.theme === 'dark';
  const textColor = isDark ? '#a3acd9' : '#4b5575';
  const gridColor = isDark ? '#232c52' : '#e6eaf5';
  const palette = ['#7c5cff', '#5cc8ff', '#ff7ac6', '#36d399', '#fbbd23', '#f87171', '#a78bfa', '#34d399'];

  const srcCounts = {};
  records.forEach(r => { const s = r.source || 'unknown'; srcCounts[s] = (srcCounts[s] || 0) + 1; });
  const srcTotal = Object.values(srcCounts).reduce((a, b) => a + b, 0);
  let startAngle = 0;
  const cx = 80, cy = 80, r = 60, r2 = 36;
  const donutSegs = Object.entries(srcCounts).map(([k, v], i) => {
    const angle = (v / srcTotal) * 360;
    const path = describeDonut(cx, cy, r, r2, startAngle, startAngle + angle);
    startAngle += angle;
    return `<path d="${path}" fill="${palette[i % palette.length]}" opacity="0.9"/>`;
  }).join('');
  const donutLegend = Object.entries(srcCounts).map(([k, v], i) => `
    <div class="chart-legend-item">
      <span class="swatch" style="background:${palette[i % palette.length]}"></span>
      <span>${escapeHtml(k)} (${v})</span>
    </div>`).join('');

  const buckets = [0, 0, 0, 0, 0];
  records.forEach(r => {
    const s = r.score || 0;
    const idx = Math.min(4, Math.floor(s / 20));
    buckets[idx]++;
  });
  const maxB = Math.max(1, ...buckets);
  const barW = 50, barGap = 12, barY = 130;
  const labels = ['0-20', '20-40', '40-60', '60-80', '80-100'];
  const bars = buckets.map((b, i) => {
    const h = (b / maxB) * 100;
    const x = 30 + i * (barW + barGap);
    return `
      <rect x="${x}" y="${barY - h}" width="${barW}" height="${h}" fill="${palette[i]}" rx="4"/>
      <text x="${x + barW/2}" y="${barY - h - 6}" text-anchor="middle" fill="${textColor}" font-size="11" font-family="JetBrains Mono">${b}</text>
      <text x="${x + barW/2}" y="${barY + 16}" text-anchor="middle" fill="${textColor}" font-size="11" font-family="JetBrains Mono">${labels[i]}</text>`;
  }).join('');

  const sorted = records.slice().sort((a, b) => (a.id || 0) - (b.id || 0));
  const pts = sorted.map((rec, i) => {
    const x = 30 + (i / Math.max(1, sorted.length - 1)) * 360;
    const y = 160 - ((rec.score || 0) / 100) * 130;
    return `${x},${y}`;
  }).join(' ');
  const lineSvg = `
    <polyline points="${pts}" fill="none" stroke="${palette[1]}" stroke-width="2"/>
    ${sorted.map((rec, i) => {
      const x = 30 + (i / Math.max(1, sorted.length - 1)) * 360;
      const y = 160 - ((rec.score || 0) / 100) * 130;
      return `<circle cx="${x}" cy="${y}" r="3" fill="${palette[1]}"/>`;
    }).join('')}`;

  $('#charts-grid').innerHTML = `
    <div class="chart-block">
      <div class="chart-title">Source distribution</div>
      <svg viewBox="0 0 400 200" class="chart-svg">${donutSegs}</svg>
      <div class="chart-legend">${donutLegend}</div>
    </div>
    <div class="chart-block">
      <div class="chart-title">Score histogram</div>
      <svg viewBox="0 0 400 160" class="chart-svg">
        <line x1="30" y1="130" x2="370" y2="130" stroke="${gridColor}"/>
        ${bars}
      </svg>
    </div>
    <div class="chart-block">
      <div class="chart-title">Score trend (by record index)</div>
      <svg viewBox="0 0 400 170" class="chart-svg">
        <line x1="30" y1="30" x2="30" y2="160" stroke="${gridColor}"/>
        <line x1="30" y1="160" x2="370" y2="160" stroke="${gridColor}"/>
        ${lineSvg}
      </svg>
    </div>`;
}

function describeDonut(cx, cy, r, r2, startDeg, endDeg) {
  const startRad = (startDeg - 90) * Math.PI / 180;
  const endRad = (endDeg - 90) * Math.PI / 180;
  const x1 = cx + r * Math.cos(startRad), y1 = cy + r * Math.sin(startRad);
  const x2 = cx + r * Math.cos(endRad), y2 = cy + r * Math.sin(endRad);
  const x3 = cx + r2 * Math.cos(endRad), y3 = cy + r2 * Math.sin(endRad);
  const x4 = cx + r2 * Math.cos(startRad), y4 = cy + r2 * Math.sin(startRad);
  const large = (endDeg - startDeg) > 180 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} L ${x3} ${y3} A ${r2} ${r2} 0 ${large} 0 ${x4} ${y4} Z`;
}

function refreshRecords() {
  if (!state.currentRunId) return;
  const q = $('#search-input').value;
  const source = $('#source-filter').value;
  const minScore = $('#score-filter').value || 0;
  const sort = $('#sort-select').value;
  const params = new URLSearchParams({ q, source, min_score: minScore, sort });
  fetchJSON(`${API.records(state.currentRunId)}?${params}`)
    .then(({ records, sources }) => {
      state.records = records;
      $('#results-meta').textContent = `${records.length} record(s)${q ? ' matching "' + q + '"' : ''}`;
      const sf = $('#source-filter'); const cur = sf.value;
      sf.innerHTML = '<option value="">All sources</option>' +
        sources.map(s => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join('');
      sf.value = cur;
      renderRecords(records); renderCharts(records);
    })
    .catch(err => toast(err.message, 'error'));
}

function renderRecords(records) {
  if (!records.length) {
    $('#records').innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-mute);">No records yet.</div>';
    return;
  }
  $('#records').innerHTML = records.map(r => {
    const starred = state.watchlist.some(w => (w.record_id || w.id) === r.id);
    const skills = (r.skills || []).slice(0, 6).map(s => `<span class="pill">${escapeHtml(s)}</span>`).join('');
    return `
      <div class="record" data-id="${escapeHtml(r.id)}">
        <div class="record-top">
          <div class="record-title">
            <a href="${escapeHtml(r.url)}" target="_blank" rel="noopener">${escapeHtml(r.title || '(untitled)')}</a>
          </div>
          <button class="star-btn ${starred ? 'starred' : ''}" data-star="${escapeHtml(r.id)}" title="Add to watchlist">${starred ? '★' : '☆'}</button>
        </div>
        <div class="record-meta">
          ${r.company ? `<span class="meta-company">${escapeHtml(r.company)}</span>` : ''}
          ${r.location ? `<span class="meta-loc">📍 ${escapeHtml(r.location)}</span>` : ''}
          <span class="meta-source">${escapeHtml(r.source)}</span>
          ${r.score ? `<span class="meta-score">${r.score}/100</span>` : ''}
        </div>
        ${r.description ? `<div class="record-desc">${escapeHtml((r.description || '').slice(0, 220))}${(r.description || '').length > 220 ? '…' : ''}</div>` : ''}
        ${skills ? `<div class="record-skills">${skills}</div>` : ''}
      </div>`;
  }).join('');
  $$('#records [data-star]').forEach(btn => {
    btn.addEventListener('click', e => toggleWatchlist(btn.dataset.star, e.currentTarget, records));
  });
}

function refreshWatchlist() {
  fetchJSON(API.watchlist).then(({ items }) => {
    state.watchlist = items || [];
    if (state.records.length) renderRecords(state.records);
  }).catch(() => { state.watchlist = []; });
}

function toggleWatchlist(recordId, btn, records) {
  const rec = (records || []).find(r => r.id === recordId) || {};
  const existing = state.watchlist.find(w => (w.record_id || w.id) === recordId);
  if (existing) {
    fetchJSON(API.watchlistItem(existing.id), { method: 'DELETE' })
      .then(() => {
        btn.classList.remove('starred'); btn.textContent = '☆';
        toast('Removed from watchlist', 'success'); refreshWatchlist();
      })
      .catch(err => toast(err.message, 'error'));
  } else {
    fetchJSON(API.watchlist, {
      method: 'POST',
      body: JSON.stringify({
        record_id: recordId, run_id: state.currentRunId,
        url: rec.url || '', title: rec.title || '',
      }),
    })
      .then(() => {
        btn.classList.add('starred'); btn.textContent = '★';
        toast('Added to watchlist ★', 'success'); refreshWatchlist();
      })
      .catch(err => toast(err.message, 'error'));
  }
}

function openWatchlistModal() {
  fetchJSON(API.watchlist)
    .then(({ items }) => {
      state.watchlist = items || [];
      const body = $('#watchlist-records');
      if (!items.length) {
        body.innerHTML = '<div class="no-records" style="padding:30px;text-align:center;color:var(--text-mute);">Star any record (☆ button) to add it here.</div>';
      } else {
        body.innerHTML = items.map(it => `
          <div class="record">
            <div class="record-top">
              <div class="record-title">
                ${it.url ? `<a href="${escapeHtml(it.url)}" target="_blank" rel="noopener">${escapeHtml(it.title || '(untitled)')}</a>`
                          : escapeHtml(it.title || '(untitled)')}
              </div>
              <button class="btn-danger" data-rm="${escapeHtml(it.id)}" style="padding:2px 8px;font-size:11px;">Remove</button>
            </div>
            <div class="record-meta">
              <span class="meta-source">run: ${escapeHtml((it.run_id || '').slice(0, 12))}</span>
              <span style="color:var(--text-mute)">${timeAgo(new Date(((it.created_at || Date.now()/1000) * 1000)).toISOString())}</span>
            </div>
          </div>`).join('');
        $$('#watchlist-records [data-rm]').forEach(b => {
          b.addEventListener('click', () => {
            fetchJSON(API.watchlistItem(b.dataset.rm), { method: 'DELETE' })
              .then(() => { toast('Removed', 'success'); openWatchlistModal(); refreshWatchlist(); })
              .catch(err => toast(err.message, 'error'));
          });
        });
      }
      openModalById('watchlist-modal');
    })
    .catch(err => toast(err.message, 'error'));
}

function refreshNotifications() {
  fetchJSON(API.notifications).then(({ items }) => {
    state.notifications = items || []; updateNotifBadge();
  }).catch(() => { state.notifications = []; updateNotifBadge(); });
}

function updateNotifBadge() {
  const badge = $('#notif-badge');
  if (!badge) return;
  const n = state.notifications.filter(x => !x.read_at).length;
  badge.textContent = n > 0 ? String(n) : '';
  badge.hidden = n === 0;
}

function openNotificationsModal() {
  const body = $('#notif-body');
  const items = state.notifications;
  if (!items.length) {
    body.innerHTML = '<div class="no-records" style="padding:30px;text-align:center;color:var(--text-mute);">No notifications yet. They appear when a run finishes or a webhook fires.</div>';
  } else {
    body.innerHTML = items.map(n => `
      <div class="notif-row ${n.read_at ? '' : 'unread'}" style="padding:10px;border-bottom:1px solid var(--border-soft);display:flex;gap:10px;align-items:flex-start;">
        <div style="flex:1;">
          <div style="font-weight:600;color:var(--text);">${escapeHtml(n.title || n.kind || 'Notification')}</div>
          <div style="font-size:12px;color:var(--text-mute);margin-top:2px;">${escapeHtml(n.message || '')}</div>
          <div style="font-size:11px;color:var(--text-mute);margin-top:4px;">${timeAgo(new Date(((n.created_at || Date.now()/1000) * 1000)).toISOString())}</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:4px;">
          ${!n.read_at ? `<button class="btn-ghost" data-dismiss="${escapeHtml(n.id)}" style="font-size:11px;padding:2px 8px;">Mark read</button>` : ''}
          <button class="btn-danger" data-clear="${escapeHtml(n.id)}" style="font-size:11px;padding:2px 8px;">Clear</button>
        </div>
      </div>`).join('');
    $$('#notif-body [data-dismiss]').forEach(b => {
      b.addEventListener('click', () => {
        fetchJSON(API.notificationItem(b.dataset.dismiss), { method: 'PATCH' })
          .then(() => { refreshNotifications(); openNotificationsModal(); })
          .catch(err => toast(err.message, 'error'));
      });
    });
    $$('#notif-body [data-clear]').forEach(b => {
      b.addEventListener('click', () => {
        fetchJSON(API.notificationItem(b.dataset.clear), { method: 'DELETE' })
          .then(() => { refreshNotifications(); openNotificationsModal(); })
          .catch(err => toast(err.message, 'error'));
      });
    });
  }
  openModalById('notif-modal');
}

function clearAllNotifications() {
  if (!confirm('Clear all notifications?')) return;
  fetchJSON(API.notificationsClear, { method: 'POST' })
    .then(() => { toast('Notifications cleared', 'success'); refreshNotifications(); openNotificationsModal(); })
    .catch(err => toast(err.message, 'error'));
}

function openBulkExportModal() {
  const select = $('#bulk-export-runs');
  if (!select) { toast('Bulk export modal not in DOM yet', 'error'); return; }
  select.innerHTML = (state.cachedRuns || []).map(r =>
    `<option value="${escapeHtml(r.id)}" selected>${escapeHtml((r.prompt || '').slice(0, 80))} · ${r.total_records} rec</option>`
  ).join('');
  openModalById('bulk-export-modal');
}

function runBulkExport() {
  const fmt = (($('#bulk-export-fmt') || {}).value) || 'json';
  const select = $('#bulk-export-runs');
  const ids = select ? Array.from(select.selectedOptions).map(o => o.value) : [];
  if (!ids.length) { toast('Pick at least one run', 'error'); return; }
  // Backend returns a ZIP via send_file - we need form-POST fallback for binary download.
  // Try JSON fetch first; if it returns JSON URL use that; otherwise form-POST.
  fetch(API.bulkExport, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_ids: ids, format: fmt }),
  })
    .then(r => {
      const ct = r.headers.get('content-type') || '';
      if (ct.includes('application/json')) {
        return r.json().then(j => {
          if (j && (j.url || j.download_url)) {
            window.location.href = j.url || j.download_url;
          } else if (j && j.error) {
            toast(j.error, 'error');
          }
        });
      }
      // Binary ZIP - download directly
      return r.blob().then(blob => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `bulk_export_${Date.now()}.zip`;
        document.body.appendChild(a); a.click(); a.remove();
        toast(`Downloaded ZIP (${ids.length} runs)`, 'success');
      });
    })
    .catch(err => {
      toast(err.message || 'Bulk export failed', 'error');
    })
    .finally(() => closeModalById('bulk-export-modal'));
}

function openCompareModal() {
  const select = $('#compare-b');
  if (select) {
    const other = (state.cachedRuns || []).filter(r => r.id !== state.currentRunId);
    select.innerHTML = '<option value="">Pick a run…</option>' +
      other.map(r => `<option value="${escapeHtml(r.id)}">${escapeHtml((r.prompt || '').slice(0, 80))} (${r.total_records} rec)</option>`).join('');
    select.onchange = () => { if (state.currentRunId && select.value) doCompare(select.value); };
  }
  $('#compare-result').innerHTML = '';
  openModalById('compare-modal');
}

function doCompare(bId) {
  if (!state.currentRunId || !bId) return;
  fetchJSON(`${API.compare}?a=${state.currentRunId}&b=${bId}`)
    .then(res => {
      const d = res.diff || {};
      $('#compare-result').innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:10px;">
          <div style="padding:10px;background:var(--bg-2);border-radius:8px;">
            <h4 style="margin:0 0 6px;font-size:13px;">Run A · ${escapeHtml(((res.a || {}).run || {}).prompt || '').slice(0, 50)}</h4>
            <div>Records: <strong>${d.a_records || 0}</strong></div>
            <div>Avg score: <strong>${d.a_avg_score || 0}</strong></div>
            <div style="font-size:11px;color:var(--text-mute);margin-top:4px;">Sources: ${escapeHtml(Object.entries(d.a_sources || {}).map(([k,v]) => `${k} (${v})`).join(', '))}</div>
          </div>
          <div style="padding:10px;background:var(--bg-2);border-radius:8px;">
            <h4 style="margin:0 0 6px;font-size:13px;">Run B · ${escapeHtml(((res.b || {}).run || {}).prompt || '').slice(0, 50)}</h4>
            <div>Records: <strong>${d.b_records || 0}</strong></div>
            <div>Avg score: <strong>${d.b_avg_score || 0}</strong></div>
            <div style="font-size:11px;color:var(--text-mute);margin-top:4px;">Sources: ${escapeHtml(Object.entries(d.b_sources || {}).map(([k,v]) => `${k} (${v})`).join(', '))}</div>
          </div>
        </div>
        <div style="margin-top:14px;">
          <h4 style="margin:0 0 6px;font-size:13px;">Summary A</h4>
          <div style="font-size:12px;color:var(--text-mute);">${escapeHtml((((res.a || {}).summary || {}).narrative || '').slice(0, 400))}</div>
          <h4 style="margin:10px 0 6px;font-size:13px;">Summary B</h4>
          <div style="font-size:12px;color:var(--text-mute);">${escapeHtml((((res.b || {}).summary || {}).narrative || '').slice(0, 400))}</div>
        </div>`;
    })
    .catch(err => toast(err.message, 'error'));
}

function openReplayDiffModal() {
  if (!state.currentRunId) return;
  const select = $('#diff-target');
  if (select) {
    const others = (state.cachedRuns || []).filter(r => r.id !== state.currentRunId);
    select.innerHTML = '<option value="">Original run only</option>' +
      others.map(r => `<option value="${escapeHtml(r.id)}">${escapeHtml((r.prompt || '').slice(0, 60))} (${r.total_records} rec)</option>`).join('');
  }
  $('#diff-result').innerHTML = '<p style="color:var(--text-mute);">Click "Replay & Show Diff" to re-run this prompt and compare results.</p>';
  openModalById('diff-modal');
}

function runReplayDiff() {
  if (!state.currentRunId) return;
  const btn = $('#btn-replay-diff-go');
  if (btn) { btn.disabled = true; btn.textContent = 'Replaying…'; }
  $('#diff-result').innerHTML = '<div class="spinner"></div><div>Replaying workflow (up to 90s)…</div>';
  fetchJSON(API.replayDiff(state.currentRunId), { method: 'POST' })
    .then(res => {
      if (btn) { btn.disabled = false; btn.textContent = '↻ Replay & Show Diff'; }
      const d = res.diff || {};
      $('#diff-result').innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-top:10px;">
          <div style="padding:10px;background:var(--bg-2);border-radius:8px;">
            <h4 style="margin:0 0 4px;font-size:12px;">Original</h4>
            <div>Records: <strong>${d.a_records || 0}</strong></div>
            <div>Avg score: <strong>${d.a_avg_score || 0}</strong></div>
          </div>
          <div style="padding:10px;background:var(--bg-2);border-radius:8px;">
            <h4 style="margin:0 0 4px;font-size:12px;">Replay</h4>
            <div>Records: <strong>${d.b_records || 0}</strong></div>
            <div>Avg score: <strong>${d.b_avg_score || 0}</strong></div>
          </div>
          <div style="padding:10px;background:var(--bg-3);border-radius:8px;">
            <h4 style="margin:0 0 4px;font-size:12px;">Delta</h4>
            <div>Records Δ: <strong>${d.records_delta || 0}</strong></div>
            <div>Score Δ: <strong>${d.score_delta || 0}</strong></div>
            <div style="font-size:11px;color:var(--text-mute);margin-top:4px;">Status: ${escapeHtml(d.replay_status || 'unknown')}</div>
          </div>
        </div>
        ${d.only_in_original && d.only_in_original.length ? `
          <div style="margin-top:14px;">
            <h4 style="font-size:12px;">Only in original</h4>
            <ul style="font-size:11px;color:var(--text-mute);">${d.only_in_original.map(t => `<li>${escapeHtml(t)}</li>`).join('')}</ul>
          </div>` : ''}
        ${d.only_in_replay && d.only_in_replay.length ? `
          <div style="margin-top:10px;">
            <h4 style="font-size:12px;">Only in replay</h4>
            <ul style="font-size:11px;color:var(--text-mute);">${d.only_in_replay.map(t => `<li>${escapeHtml(t)}</li>`).join('')}</ul>
          </div>` : ''}`;
      refreshRuns();
    })
    .catch(err => {
      if (btn) { btn.disabled = false; btn.textContent = '↻ Replay & Show Diff'; }
      $('#diff-result').innerHTML = `<p style="color:var(--error);">${escapeHtml(err.message)}</p>`;
      toast(err.message, 'error');
    });
}

function openQualityModal() {
  if (!state.currentRunId) return;
  const body = $('#quality-modal-body');
  if (!body) { toast('Quality modal not in DOM', 'error'); return; }
  body.innerHTML = '<div class="spinner"></div><div>Checking data quality…</div>';
  openModalById('quality-modal');
  fetchJSON(API.quality(state.currentRunId))
    .then(res => {
      const q = (res && res.quality) || res || {};
      const checks = q.checks || [];
      body.innerHTML = `
        <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:10px;margin-bottom:14px;">
          <div style="padding:10px;background:var(--bg-2);border-radius:8px;text-align:center;">
            <div style="font-size:11px;color:var(--text-mute);text-transform:uppercase;">Score</div>
            <div style="font-size:24px;font-weight:700;color:var(--accent);">${q.overall_score ?? q.score ?? '—'}/100</div>
          </div>
          <div style="padding:10px;background:var(--bg-2);border-radius:8px;text-align:center;">
            <div style="font-size:11px;color:var(--text-mute);text-transform:uppercase;">Records</div>
            <div style="font-size:24px;font-weight:700;">${q.total_records ?? 0}</div>
          </div>
          <div style="padding:10px;background:var(--bg-2);border-radius:8px;text-align:center;">
            <div style="font-size:11px;color:var(--text-mute);text-transform:uppercase;">URLs OK</div>
            <div style="font-size:24px;font-weight:700;">${q.valid_urls ?? '—'}</div>
          </div>
          <div style="padding:10px;background:var(--bg-2);border-radius:8px;text-align:center;">
            <div style="font-size:11px;color:var(--text-mute);text-transform:uppercase;">Duplicates</div>
            <div style="font-size:24px;font-weight:700;">${q.duplicates ?? 0}</div>
          </div>
        </div>
        <div style="margin-bottom:10px;">
          ${checks.map(c => `
            <div style="display:flex;align-items:center;gap:8px;padding:8px;border-bottom:1px solid var(--border-soft);">
              <span style="display:inline-block;width:18px;height:18px;border-radius:50%;background:${c.passed ? 'var(--success)' : 'var(--error)'};color:#fff;text-align:center;line-height:18px;font-size:11px;">${c.passed ? '✓' : '✕'}</span>
              <span style="flex:1;font-weight:600;font-size:13px;">${escapeHtml(c.name || c.label || '')}</span>
              <span style="font-size:11px;color:var(--text-mute);">${escapeHtml(c.detail || c.message || '')}</span>
            </div>`).join('') || '<p style="color:var(--text-mute)">No checks returned.</p>'}
        </div>
        ${q.narrative ? `<div style="padding:10px;background:var(--bg-3);border-radius:8px;font-size:12px;">${escapeHtml(q.narrative)}</div>` : ''}`;
    })
    .catch(err => { body.innerHTML = `<p style="color:var(--error);">${escapeHtml(err.message)}</p>`; });
}

function openSourcesModal() {
  if (!state.currentRunId) return;
  const metaEl = $('#source-modal-meta');
  const recsEl = $('#source-modal-records');
  if (metaEl) metaEl.innerHTML = '<div class="spinner"></div>';
  if (recsEl) recsEl.innerHTML = '';
  openModalById('source-modal');
  fetchJSON(API.runSources(state.currentRunId))
    .then(({ sources }) => {
      const nameEl = $('#source-modal-name');
      if (nameEl) nameEl.textContent = `run ${state.currentRunId}`;
      if (metaEl) metaEl.innerHTML = '';
      if (!sources || !sources.length) {
        if (metaEl) metaEl.innerHTML = '<p style="color:var(--text-mute);">No sources recorded for this run.</p>';
        return;
      }
      if (recsEl) {
        recsEl.innerHTML = sources.map(s => `
          <div class="record">
            <div class="record-top">
              <div class="record-title">${escapeHtml(s.source || s.name || 'unknown')}</div>
              <span class="status-pill ${escapeHtml(s.status || '')}" style="font-size:11px;">${escapeHtml(s.status || '')}</span>
            </div>
            <div class="record-meta">
              ${s.records_out != null ? `<span class="meta-source">${s.records_out} rec</span>` : ''}
              ${s.latency_ms != null ? `<span class="meta-source">${s.latency_ms}ms</span>` : ''}
            </div>
            ${s.error ? `<div style="color:var(--error);font-size:11px;margin-top:4px;">${escapeHtml(s.error)}</div>` : ''}
            ${s.message ? `<div style="color:var(--text-mute);font-size:11px;margin-top:4px;">${escapeHtml(s.message)}</div>` : ''}
          </div>`).join('');
      }
    })
    .catch(err => {
      if (metaEl) metaEl.innerHTML = `<p style="color:var(--error);">${escapeHtml(err.message)}</p>`;
    });
}

function openAbTestModal() {
  openModalById('ab-modal');
}

function runAbTest() {
  const a = (($('#ab-prompt-1') || {}).value) || '';
  const b = (($('#ab-prompt-2') || {}).value) || '';
  if (!a.trim() || !b.trim()) { toast('Enter both prompts', 'error'); return; }
  let resultEl = $('#ab-result');
  if (!resultEl) {
    const body = $('#ab-modal').querySelector('.modal-body');
    const d = document.createElement('div');
    d.id = 'ab-result'; d.style.marginTop = '14px'; body.appendChild(d);
    resultEl = d;
  }
  resultEl.innerHTML = '<div class="spinner"></div><div>Running both prompts in parallel…</div>';
  fetchJSON(API.abTest, {
    method: 'POST',
    body: JSON.stringify({ prompt_a: a, prompt_b: b }),
  })
    .then(res => {
      resultEl.innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px;">
          <div style="padding:10px;background:var(--bg-2);border-radius:8px;">
            <h4 style="margin:0 0 6px;font-size:13px;">A · ${escapeHtml(a.slice(0, 50))}</h4>
            <div>Run: <code>${escapeHtml(res.run_a || '—')}</code></div>
            <div style="color:var(--text-mute);font-size:11px;">Status: running…</div>
          </div>
          <div style="padding:10px;background:var(--bg-2);border-radius:8px;">
            <h4 style="margin:0 0 6px;font-size:13px;">B · ${escapeHtml(b.slice(0, 50))}</h4>
            <div>Run: <code>${escapeHtml(res.run_b || '—')}</code></div>
            <div style="color:var(--text-mute);font-size:11px;">Status: running…</div>
          </div>
        </div>
        <p style="color:var(--text-mute);margin-top:10px;font-size:12px;">Both runs are executing. Open either from the sidebar to inspect results.</p>`;
      refreshRuns();
    })
    .catch(err => {
      resultEl.innerHTML = `<p style="color:var(--error);">${escapeHtml(err.message)}</p>`;
    });
}

function openAnalyticsModal() {
  $('#analytics-body').innerHTML = '<div class="spinner"></div><div>Computing analytics…</div>';
  openModalById('analytics-modal');
  const totalRuns = state.cachedRuns.length;
  const totalRec = state.cachedRuns.reduce((a, r) => a + (r.total_records || 0), 0);
  const byStatus = state.cachedRuns.reduce((m, r) => { m[r.status] = (m[r.status] || 0) + 1; return m; }, {});
  const recent = state.cachedRuns.slice(0, 8);
  $('#analytics-body').innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:10px;margin-bottom:14px;">
      <div style="padding:12px;background:var(--bg-2);border-radius:8px;text-align:center;">
        <div style="font-size:11px;color:var(--text-mute);text-transform:uppercase;">Total runs</div>
        <div style="font-size:24px;font-weight:700;">${totalRuns}</div>
      </div>
      <div style="padding:12px;background:var(--bg-2);border-radius:8px;text-align:center;">
        <div style="font-size:11px;color:var(--text-mute);text-transform:uppercase;">Total records</div>
        <div style="font-size:24px;font-weight:700;">${totalRec}</div>
      </div>
      <div style="padding:12px;background:var(--bg-2);border-radius:8px;text-align:center;">
        <div style="font-size:11px;color:var(--text-mute);text-transform:uppercase;">Avg rec/run</div>
        <div style="font-size:24px;font-weight:700;">${totalRuns ? (totalRec/totalRuns).toFixed(1) : 0}</div>
      </div>
      <div style="padding:12px;background:var(--bg-2);border-radius:8px;text-align:center;">
        <div style="font-size:11px;color:var(--text-mute);text-transform:uppercase;">Success</div>
        <div style="font-size:24px;font-weight:700;color:var(--success);">${totalRuns ? Math.round(((byStatus.done||0)/totalRuns)*100) : 0}%</div>
      </div>
    </div>
    <h4 style="margin:0 0 6px;font-size:13px;">Status breakdown</h4>
    <div style="margin-bottom:14px;">${Object.entries(byStatus).map(([k,v]) => `<span class="pill" style="margin-right:6px;">${escapeHtml(k)}: ${v}</span>`).join('') || '<span style="color:var(--text-mute)">No data</span>'}</div>
    <h4 style="margin:0 0 6px;font-size:13px;">Recent runs</h4>
    <div>${recent.map(r => `
      <div style="display:flex;align-items:center;gap:8px;padding:8px;border-bottom:1px solid var(--border-soft);">
        <span class="status-dot ${escapeHtml(r.status)}"></span>
        <span style="flex:1;font-size:12px;">${escapeHtml((r.prompt || '').slice(0, 80))}</span>
        <span style="color:var(--text-mute);font-size:11px;">${r.total_records} rec</span>
      </div>`).join('') || '<span style="color:var(--text-mute)">No runs yet</span>'}</div>`;
}

function saveSchedule() {
  const prompt = $('#schedule-prompt').value.trim();
  const interval_seconds = parseInt($('#schedule-interval').value, 10);
  if (!prompt) { toast('Prompt is required', 'error'); return; }
  fetchJSON(API.schedules, {
    method: 'POST', body: JSON.stringify({ prompt, interval_seconds }),
  })
    .then(() => {
      toast('Schedule saved', 'success');
      closeModalById('schedule-modal'); $('#schedule-prompt').value = ''; refreshSchedules();
    })
    .catch(err => toast(err.message, 'error'));
}

function refreshSchedules() {
  fetchJSON(API.schedules).then(({ schedules }) => {
    const list = $('#schedule-list'); if (!list) return;
    if (!schedules.length) { list.innerHTML = '<div style="color:var(--text-mute);font-size:12px;padding:6px;">No schedules yet</div>'; return; }
    list.innerHTML = schedules.map(s => `
      <div style="display:flex;align-items:center;gap:6px;padding:6px;border-bottom:1px solid var(--border-soft);">
        <input type="checkbox" data-toggle="${escapeHtml(s.id)}" ${s.enabled ? 'checked' : ''} style="width:16px;height:16px;">
        <div style="flex:1;font-size:11px;">
          <div>${escapeHtml((s.prompt || '').slice(0, 60))}</div>
          <div style="color:var(--text-mute);">every ${Math.round((s.interval_seconds || 3600) / 60)} min</div>
        </div>
        <button data-del-sched="${escapeHtml(s.id)}" style="background:none;border:none;color:var(--error);cursor:pointer;font-size:16px;">×</button>
      </div>`).join('');
    $$('#schedule-list [data-toggle]').forEach(t => {
      t.addEventListener('change', () => {
        fetchJSON(API.scheduleToggle(t.dataset.toggle), {
          method: 'POST', body: JSON.stringify({ enabled: t.checked }),
        }).then(refreshSchedules).catch(err => toast(err.message, 'error'));
      });
    });
    $$('#schedule-list [data-del-sched]').forEach(b => {
      b.addEventListener('click', () => {
        fetchJSON(API.schedule(b.dataset.delSched), { method: 'DELETE' })
          .then(refreshSchedules).catch(err => toast(err.message, 'error'));
      });
    });
  }).catch(() => {});
}

function saveWebhook() {
  const url = $('#webhook-url').value.trim();
  const type = $('#webhook-type').value;
  const event = $('#webhook-event').value;
  if (!url) { toast('Webhook URL is required', 'error'); return; }
  fetchJSON(API.webhooks, {
    method: 'POST', body: JSON.stringify({ url, type, event }),
  })
    .then(() => {
      toast('Webhook saved', 'success');
      closeModalById('webhook-modal'); $('#webhook-url').value = ''; refreshWebhooks();
    })
    .catch(err => toast(err.message, 'error'));
}

function refreshWebhooks() {
  fetchJSON(API.webhooks).then(({ webhooks }) => {
    const list = $('#webhook-list'); if (!list) return;
    if (!webhooks.length) { list.innerHTML = '<div style="color:var(--text-mute);font-size:12px;padding:6px;">No webhooks yet</div>'; return; }
    list.innerHTML = webhooks.map(w => `
      <div style="display:flex;align-items:center;gap:6px;padding:6px;border-bottom:1px solid var(--border-soft);">
        <div style="flex:1;font-size:11px;">
          <div>${escapeHtml(w.type || 'generic')} · ${escapeHtml(w.event || 'run_done')}</div>
          <div style="color:var(--text-mute);word-break:break-all;">${escapeHtml((w.url || '').slice(0, 60))}</div>
        </div>
        <button data-del-wh="${escapeHtml(w.id)}" style="background:none;border:none;color:var(--error);cursor:pointer;font-size:16px;">×</button>
      </div>`).join('');
    $$('#webhook-list [data-del-wh]').forEach(b => {
      b.addEventListener('click', () => {
        fetchJSON(API.webhook(b.dataset.delWh), { method: 'DELETE' })
          .then(refreshWebhooks).catch(err => toast(err.message, 'error'));
      });
    });
  }).catch(() => {});
}
'''


def main() -> int:
    print(f"Patching project at: {ROOT}")
    print("=" * 60)
    print("[1/4] Patching database.py ...")
    patch_database()
    print("[2/4] Patching app.py ...")
    patch_app()
    print("[3/4] Patching templates/index.html ...")
    patch_index()
    print("[4/4] Rewriting static/js/app.js ...")
    patch_app_js()
    print("=" * 60)
    print("DONE. Backups saved with .bak extension next to each file.")
    print("Restart Flask (Ctrl+C then 'python app.py') and hard-refresh browser.")
    return 0


if __name__ == "__main__":
    sys.exit(main())