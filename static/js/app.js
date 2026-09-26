/* AI Data Intelligence Platform - frontend logic */

const API = {
  preview: '/api/preview',
  runs: '/api/runs',
  run: id => `/api/runs/${id}`,
  live: id => `/api/runs/${id}/live`,
  records: id => `/api/runs/${id}/records`,
  export: (id, fmt) => `/api/runs/${id}/export?format=${fmt}`,
  stats: '/api/stats',
  demo: '/api/demo/load',
  summary: id => `/api/runs/${id}/summary`,
  sourceHealth: id => `/api/runs/${id}/source-health`,
  sourceHealthAll: '/api/source-health',
  schedules: '/api/schedules',
  schedule: id => `/api/schedules/${id}`,
  scheduleToggle: id => `/api/schedules/${id}/toggle`,
  webhooks: '/api/webhooks',
  webhook: id => `/api/webhooks/${id}`,
  share: id => `/api/runs/${id}/share`,
  shareView: token => `/api/share/${token}`,
  compare: '/api/runs/compare',
};

const state = {
  currentRunId: null,
  run: null,
  records: [],
  pollHandle: null,
  searchDebounce: null,
  theme: localStorage.getItem('dip_theme') || 'dark',
};

/* =========================== Utilities =========================== */

function $(sel, root = document) { return root.querySelector(sel); }
function $$(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function timeAgo(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  if (diff < 86400 * 30) return Math.floor(diff / 86400) + 'd ago';
  return d.toLocaleDateString();
}

function toast(msg, kind = 'info') {
  const host = $('#toast-host');
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = msg;
  host.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; }, 2400);
  setTimeout(() => el.remove(), 2800);
}

function fetchJSON(url, opts = {}) {
  return fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  }).then(r => {
    if (!r.ok) {
      return r.json().then(j => { throw new Error(j.error || `${r.status} ${r.statusText}`); });
    }
    return r.json();
  });
}

/* =========================== Theme =========================== */

function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  $('#theme-toggle').textContent = t === 'dark' ? '🌙' : '☀️';
  state.theme = t;
  localStorage.setItem('dip_theme', t);
}

function toggleTheme() {
  applyTheme(state.theme === 'dark' ? 'light' : 'dark');
  // Re-render charts so colors match theme
  if (state.records.length && state.currentRunId) {
    renderCharts(state.records);
  }
}

/* =========================== Bootstrap =========================== */

document.addEventListener('DOMContentLoaded', () => {
  applyTheme(state.theme);

  $('#theme-toggle').addEventListener('click', toggleTheme);

  $('#btn-new-run').addEventListener('click', openModal);
  $('#modal-close').addEventListener('click', closeModal);
  $('#modal').addEventListener('click', e => {
    if (e.target.id === 'modal') closeModal();
  });

  $$('[data-close]').forEach(b => b.addEventListener('click', () => closeModalById(b.dataset.close)));

  $('#btn-modal-preview').addEventListener('click', () => previewPrompt($('#modal-prompt').value, $('#modal-preview')));
  $('#btn-modal-launch').addEventListener('click', () => launchFromModal());

  $('#btn-empty-launch').addEventListener('click', () => launchFromEmpty());
  $('#btn-empty-preview').addEventListener('click', () => previewPrompt($('#empty-prompt').value, $('#empty-preview')));
  $('#btn-empty-load-demo').addEventListener('click', loadDemo);
  $('#btn-load-demo').addEventListener('click', loadDemo);

  $$('.example-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const prompt = btn.getAttribute('data-prompt');
      $('#modal-prompt').value = prompt;
      openModal();
    });
  });

  // Voice buttons
  setupVoice('#btn-voice-empty', '#empty-prompt');
  setupVoice('#btn-voice-modal', '#modal-prompt');

  // Run actions
  $('#btn-export-json').addEventListener('click', () => exportRun('json'));
  $('#btn-export-csv').addEventListener('click', () => exportRun('csv'));
  $('#btn-replay').addEventListener('click', replayRun);
  $('#btn-delete').addEventListener('click', deleteRun);
  $('#btn-share').addEventListener('click', shareRun);
  $('#btn-compare').addEventListener('click', openCompareModal);

  // Schedules & webhooks
  $('#btn-new-schedule').addEventListener('click', () => $('#schedule-modal').hidden = false);
  $('#btn-schedule-save').addEventListener('click', saveSchedule);
  $('#btn-new-webhook').addEventListener('click', () => $('#webhook-modal').hidden = false);
  $('#btn-webhook-save').addEventListener('click', saveWebhook);

  // Filters
  $('#search-input').addEventListener('input', () => {
    clearTimeout(state.searchDebounce);
    state.searchDebounce = setTimeout(refreshRecords, 200);
  });
  $('#source-filter').addEventListener('change', refreshRecords);
  $('#score-filter').addEventListener('change', refreshRecords);
  $('#sort-select').addEventListener('change', refreshRecords);

  refreshStats();
  refreshRuns();
  refreshSchedules();
  refreshWebhooks();
});

/* =========================== Modal helpers =========================== */

function openModal() {
  $('#modal').hidden = false;
  $('#modal-preview').hidden = true;
  if (!$('#modal-prompt').value) {
    $('#modal-prompt').value = $('#empty-prompt').value || '';
  }
  setTimeout(() => $('#modal-prompt').focus(), 50);
}
function closeModal() { $('#modal').hidden = true; }
function closeModalById(id) { $('#' + id).hidden = true; }

function previewPrompt(prompt, targetEl) {
  if (!prompt || !prompt.trim()) {
    toast('Please enter a prompt first', 'error');
    return;
  }
  fetchJSON(API.preview, { method: 'POST', body: JSON.stringify({ prompt }) })
    .then(({ intent }) => {
      targetEl.hidden = false;
      targetEl.textContent = JSON.stringify(intent, null, 2);
    })
    .catch(err => toast(err.message, 'error'));
}

function launchFromModal() {
  const prompt = $('#modal-prompt').value.trim();
  if (!prompt) { toast('Please enter a prompt', 'error'); return; }
  closeModal();
  startRun(prompt);
}

function launchFromEmpty() {
  const prompt = $('#empty-prompt').value.trim();
  if (!prompt) { toast('Please enter a prompt', 'error'); return; }
  startRun(prompt);
}

/* =========================== Voice =========================== */

function setupVoice(btnSel, inputSel) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    const btn = $(btnSel);
    if (btn) btn.style.display = 'none';
    return;
  }
  const btn = $(btnSel);
  const input = $(inputSel);
  if (!btn || !input) return;

  const recognition = new SR();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = 'en-US';

  btn.addEventListener('click', () => {
    if (btn.classList.contains('listening')) {
      recognition.stop();
      return;
    }
    try {
      recognition.start();
      btn.classList.add('listening');
      toast('Listening...', 'success');
    } catch (e) {
      toast('Voice not available: ' + e.message, 'error');
    }
  });

  recognition.onresult = (e) => {
    const text = Array.from(e.results).map(r => r[0].transcript).join('');
    input.value = text;
  };
  recognition.onerror = (e) => {
    btn.classList.remove('listening');
    toast('Voice error: ' + e.error, 'error');
  };
  recognition.onend = () => btn.classList.remove('listening');
}

/* =========================== Runs =========================== */

function startRun(prompt) {
  fetchJSON(API.runs, { method: 'POST', body: JSON.stringify({ prompt }) })
    .then(({ run_id }) => {
      state.currentRunId = run_id;
      $('#empty-state').hidden = true;
      $('#run-view').hidden = false;
      $('#run-id').textContent = `run-${run_id}`;
      $('#run-prompt').textContent = prompt;
      $('#empty-prompt').value = '';
      $('#records').innerHTML = '<div class="results-loading"><div class="spinner"></div><div>Starting workflow…</div></div>';
      $('#run-status-bar').hidden = false;
      $('#status-pill').className = 'status-pill';
      $('#status-pill').textContent = 'queued';
      $('#status-text').textContent = 'Initializing…';
      $('#summary-card').hidden = true;
      $('#charts-card').hidden = true;
      $('#health-card').hidden = true;
      toast('Workflow started', 'success');
      refreshRuns();
      pollRun(run_id);
    })
    .catch(err => toast(err.message, 'error'));
}

function replayRun() {
  if (!state.currentRunId) return;
  fetchJSON(`${API.run(state.currentRunId)}/replay`, { method: 'POST' })
    .then(({ run_id }) => {
      state.currentRunId = run_id;
      $('#run-id').textContent = `run-${run_id}`;
      $('#records').innerHTML = '<div class="results-loading"><div class="spinner"></div><div>Replaying workflow…</div></div>';
      toast('Replay started', 'success');
      refreshRuns();
      pollRun(run_id);
    })
    .catch(err => toast(err.message, 'error'));
}

function deleteRun() {
  if (!state.currentRunId) return;
  if (!confirm('Delete this run and its dataset?')) return;
  fetchJSON(API.run(state.currentRunId), { method: 'DELETE' })
    .then(() => {
      toast('Run deleted', 'success');
      state.currentRunId = null;
      state.records = [];
      state.run = null;
      $('#run-view').hidden = true;
      $('#empty-state').hidden = false;
      refreshRuns();
      refreshStats();
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
      navigator.clipboard?.writeText(fullUrl);
      toast('Share link copied to clipboard!', 'success');
      prompt('Share this public read-only link:', fullUrl);
    })
    .catch(err => toast(err.message, 'error'));
}

function refreshRuns() {
  fetchJSON(API.runs)
    .then(({ runs }) => {
      const list = $('#run-list');
      if (!runs.length) {
        list.innerHTML = '<li style="background:transparent;border:none;color:var(--text-mute);padding:8px;font-style:italic;">No runs yet</li>';
        return;
      }
      list.innerHTML = runs.map(r => `
        <li class="${r.id === state.currentRunId ? 'active' : ''}" data-id="${r.id}">
          <button class="rl-delete" data-del-run="${r.id}" title="Delete this run">×</button>
          <div class="rl-prompt">${escapeHtml(r.prompt)}</div>
          <div class="rl-meta">
            <span><span class="status-dot ${r.status}"></span> ${r.status}</span>
            <span>${r.total_records} rec · ${timeAgo(new Date(r.created_at * 1000).toISOString())}</span>
          </div>
        </li>
      `).join('');
      $$('#run-list li[data-id]').forEach(li => {
        li.addEventListener('click', (e) => {
          if (e.target.closest('[data-del-run]')) return;
          selectRun(li.dataset.id);
        });
      });
      $$('[data-del-run]').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const id = btn.dataset.delRun;
          const promptText = btn.closest('li').querySelector('.rl-prompt').textContent.trim();
          if (!confirm(`Delete this run?\n\n"${promptText.substring(0, 80)}${promptText.length > 80 ? '…' : ''}"`)) return;
          fetchJSON(API.run(id), { method: 'DELETE' })
            .then(() => {
              toast('Run deleted', 'success');
              if (state.currentRunId === id) {
                state.currentRunId = null;
                state.records = [];
                $('#run-view').hidden = true;
                $('#empty-state').hidden = false;
              }
              refreshRuns();
              refreshStats();
            })
            .catch(err => toast(err.message, 'error'));
        });
      });
    })
    .catch(err => toast(err.message, 'error'));
}

function selectRun(id) {
  state.currentRunId = id;
  $('#empty-state').hidden = true;
  $('#run-view').hidden = false;
  refreshRuns();
  fetchJSON(API.live(id))
    .then(({ run, live }) => {
      applyRun(run);
      loadRunExtras(id);
      if (!live && run.status !== 'running') {
        refreshRecords();
      } else {
        pollRun(id);
      }
    })
    .catch(() => {
      $('#empty-state').hidden = false;
      $('#run-view').hidden = true;
      toast('Run not found', 'error');
    });
}

function refreshStats() {
  fetchJSON(API.stats)
    .then(s => {
      $('#stat-runs').textContent = s.runs || 0;
      $('#stat-records').textContent = s.records || 0;
      $('#stat-types').textContent = Object.keys(s.by_type || {}).length;
    })
    .catch(() => {});
}

/* =========================== Polling live =========================== */

function pollRun(runId) {
  clearInterval(state.pollHandle);
  const tick = () => {
    fetchJSON(API.live(runId))
      .then(({ run, live }) => {
        applyRun(run);
        if (run.status !== 'running') {
          clearInterval(state.pollHandle);
          refreshRuns();
          refreshRecords();
          refreshStats();
          loadRunExtras(runId);
          toast(`Workflow ${run.status}`, run.status === 'done' ? 'success' : 'error');
          return;
        }
        if (!state._sidebarTick) state._sidebarTick = 0;
        state._sidebarTick = (state._sidebarTick + 1) % 3;
        if (state._sidebarTick === 0) refreshRuns();
      })
      .catch(() => clearInterval(state.pollHandle));
  };
  state.pollHandle = setInterval(tick, 1000);
  tick();
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

  renderSteps(run.workflow);
  renderIntent(run.intent);
  renderHealth(run.workflow);

  if (run.status === 'running' && Array.isArray(run.records)) {
    $('#records').innerHTML = '<div class="results-loading"><div class="spinner"></div><div>Collecting…</div></div>';
  }
}

/* =========================== Run extras (summary, charts, health) =========================== */

function loadRunExtras(runId) {
  if (!runId) return;
  fetchJSON(API.summary(runId))
    .then(({ summary }) => renderSummary(summary))
    .catch(() => {});
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
    </div>
  `).join('');
}

function renderSteps(workflow) {
  const steps = (workflow && workflow.steps) || [];
  $('#steps').innerHTML = steps.map(s => `
    <div class="step ${s.status}">
      <div class="step-icon">${
        s.status === 'done' ? '✓' :
        s.status === 'failed' ? '✕' :
        s.status === 'running' ? '⟳' : '·'
      }</div>
      <div>
        <div class="step-name">${escapeHtml(s.name)}</div>
        <div class="step-meta">${escapeHtml(s.message || '')} ${s.records_out ? '· ' + s.records_out + ' rec' : ''} ${s.latency_ms ? '· ' + s.latency_ms + 'ms' : ''}</div>
      </div>
      ${s.source ? `<div class="step-source">${escapeHtml(s.source)}</div>` : ''}
    </div>
  `).join('');
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
        : `<div class="val">${escapeHtml(String(i.val || '—'))}</div>`
      }
    </div>
  `).join('');
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
    return `
      <div class="health-item">
        <div class="health-dot ${cls}"></div>
        <div class="health-name">${escapeHtml(s.source || 'unknown')}</div>
        <div class="health-time">${s.latency_ms ? s.latency_ms + 'ms' : '-'}</div>
      </div>
    `;
  }).join('');
}

/* =========================== Charts (SVG) =========================== */

function renderCharts(records) {
  if (!records || !records.length) { $('#charts-card').hidden = true; return; }
  $('#charts-card').hidden = false;

  const isDark = state.theme === 'dark';
  const textColor = isDark ? '#a3acd9' : '#4b5575';
  const gridColor = isDark ? '#232c52' : '#e6eaf5';
  const palette = ['#7c5cff', '#5cc8ff', '#ff7ac6', '#36d399', '#fbbd23', '#f87171', '#a78bfa', '#34d399'];

  // Source distribution (donut)
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
    </div>
  `).join('');

  // Score histogram (bar chart)
  const buckets = [0, 0, 0, 0, 0]; // 0-20, 20-40, 40-60, 60-80, 80-100
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
      <text x="${x + barW/2}" y="${barY + 16}" text-anchor="middle" fill="${textColor}" font-size="10" font-family="JetBrains Mono">${labels[i]}</text>
    `;
  }).join('');

  $('#charts-grid').innerHTML = `
    <div class="chart-card">
      <div class="chart-title">Records by Source</div>
      <svg class="chart-svg" viewBox="0 0 320 160" preserveAspectRatio="xMidYMid meet">
        ${donutSegs}
        <text x="${cx}" y="${cy + 4}" text-anchor="middle" fill="${textColor}" font-size="14" font-weight="700" font-family="Inter">${records.length}</text>
        <text x="${cx}" y="${cy + 18}" text-anchor="middle" fill="${textColor}" font-size="9" font-family="JetBrains Mono">total</text>
      </svg>
      <div class="chart-legend">${donutLegend}</div>
    </div>
    <div class="chart-card">
      <div class="chart-title">Score Distribution</div>
      <svg class="chart-svg" viewBox="0 0 340 160" preserveAspectRatio="xMidYMid meet">
        <line x1="20" y1="130" x2="330" y2="130" stroke="${gridColor}" stroke-width="1"/>
        ${bars}
      </svg>
    </div>
  `;
}

function describeDonut(cx, cy, rOuter, rInner, startAngle, endAngle) {
  // Avoid huge arcs (full circle problem)
  if (endAngle - startAngle >= 359.99) return '';
  const p1 = polar(cx, cy, rOuter, startAngle);
  const p2 = polar(cx, cy, rOuter, endAngle);
  const p3 = polar(cx, cy, rInner, endAngle);
  const p4 = polar(cx, cy, rInner, startAngle);
  const large = (endAngle - startAngle) > 180 ? 1 : 0;
  return `M${p1.x},${p1.y} A${rOuter},${rOuter} 0 ${large} 1 ${p2.x},${p2.y} L${p3.x},${p3.y} A${rInner},${rInner} 0 ${large} 0 ${p4.x},${p4.y} Z`;
}
function polar(cx, cy, r, angle) {
  const rad = (angle - 90) * Math.PI / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

/* =========================== Records =========================== */

function refreshRecords() {
  if (!state.currentRunId) return;
  const q = $('#search-input').value;
  const source = $('#source-filter').value;
  const minScore = parseInt($('#score-filter').value || '0', 10);
  const sort = $('#sort-select').value;
  const url = new URL(API.records(state.currentRunId), window.location.origin);
  if (q) url.searchParams.set('q', q);
  if (source) url.searchParams.set('source', source);
  if (minScore) url.searchParams.set('min_score', String(minScore));
  url.searchParams.set('sort', sort);

  $('#records').innerHTML = '<div class="results-loading"><div class="spinner"></div><div>Loading records…</div></div>';

  fetchJSON(url)
    .then(({ records, sources }) => {
      state.records = records;
      const sf = $('#source-filter');
      const current = sf.value;
      sf.innerHTML = '<option value="">All sources</option>' + (sources || []).map(s => `<option value="${s}">${s}</option>`).join('');
      sf.value = current;

      $('#results-meta').textContent = `${records.length} record(s)` +
        (q ? ` matching "${q}"` : '') +
        (source ? ` from ${source}` : '') +
        (minScore ? ` score ≥ ${minScore}` : '');

      if (!records.length) {
        $('#records').innerHTML = '<div class="no-records">No records match your filters.</div>';
        $('#charts-card').hidden = true;
        return;
      }

      $('#records').innerHTML = records.map(r => recordHtml(r)).join('');
      renderCharts(records);
    })
    .catch(err => {
      $('#records').innerHTML = `<div class="no-records">Error: ${escapeHtml(err.message)}</div>`;
    });
}

function recordHtml(r) {
  const skills = (r.skills || []).slice(0, 6).map(s => `<span class="meta-tag skill">${escapeHtml(s)}</span>`).join('');
  const inds = (r.industries || []).slice(0, 4).map(i => `<span class="meta-tag industry">${escapeHtml(i)}</span>`).join('');
  const comp = r.company ? `<span class="meta-tag">🏢 ${escapeHtml(r.company)}</span>` : '';
  const loc = r.location ? `<span class="meta-tag">📍 ${escapeHtml(r.location)}</span>` : '';
  const ts = r.published_at ? `<span>${escapeHtml(timeAgo(r.published_at))}</span>` : '';
  const link = r.url ? `<a href="${escapeHtml(r.url)}" target="_blank" rel="noopener">View source ↗</a>` : '<span>no url</span>';
  const title = r.url
    ? `<a href="${escapeHtml(r.url)}" target="_blank" rel="noopener">${escapeHtml(r.title)}</a>`
    : escapeHtml(r.title);
  return `
    <div class="record">
      <div class="record-head">
        <h3 class="record-title">${title}</h3>
        <div class="record-score">★ ${r.score || 0}</div>
      </div>
      ${r.description ? `<div class="record-desc">${escapeHtml(r.description).slice(0, 320)}${r.description.length > 320 ? '…' : ''}</div>` : ''}
      <div class="record-meta">
        <span class="meta-tag source">${escapeHtml(r.source || 'unknown')}</span>
        <span class="meta-tag">${escapeHtml(r.type || 'item')}</span>
        ${comp}${loc}${inds}${skills}
      </div>
      <div class="record-foot">
        ${ts}
        ${link}
      </div>
    </div>
  `;
}

/* =========================== Demo =========================== */

function loadDemo() {
  toast('Loading demo data...', 'success');
  fetchJSON(API.demo, { method: 'POST' })
    .then(({ seeded, count }) => {
      toast(`Loaded ${count} demo runs`, 'success');
      refreshRuns();
      refreshStats();
      if (seeded && seeded.length) {
        selectRun(seeded[0]);
      }
    })
    .catch(err => toast(err.message, 'error'));
}

/* =========================== Schedules =========================== */

function saveSchedule() {
  const prompt = $('#schedule-prompt').value.trim();
  const interval = parseInt($('#schedule-interval').value, 10);
  if (!prompt) { toast('Prompt is required', 'error'); return; }
  fetchJSON(API.schedules, {
    method: 'POST',
    body: JSON.stringify({ prompt, interval_seconds: interval }),
  })
    .then(() => {
      toast('Schedule created', 'success');
      $('#schedule-prompt').value = '';
      $('#schedule-modal').hidden = true;
      refreshSchedules();
    })
    .catch(err => toast(err.message, 'error'));
}

function refreshSchedules() {
  fetchJSON(API.schedules)
    .then(({ schedules }) => {
      const list = $('#schedule-list');
      if (!schedules.length) {
        list.innerHTML = '<div style="font-size:11px;color:var(--text-mute);margin-top:8px;font-style:italic;">No schedules yet</div>';
        return;
      }
      list.innerHTML = schedules.map(s => `
        <div class="item-row">
          <div class="item-info">
            <div class="item-title">${escapeHtml(s.prompt.substring(0, 50))}${s.prompt.length > 50 ? '...' : ''}</div>
            <div class="item-meta">every ${Math.round(s.interval_seconds/60)}m · ${s.enabled ? 'enabled' : 'paused'}</div>
          </div>
          <button class="btn-ghost" data-toggle-schedule="${s.id}">${s.enabled ? 'Pause' : 'Resume'}</button>
          <button class="btn-danger" data-del-schedule="${s.id}">×</button>
        </div>
      `).join('');
      $$('[data-del-schedule]').forEach(b => b.addEventListener('click', () => {
        fetchJSON(API.schedule(b.dataset.delSchedule), { method: 'DELETE' }).then(() => refreshSchedules());
      }));
      $$('[data-toggle-schedule]').forEach(b => b.addEventListener('click', () => {
        const id = b.dataset.toggleSchedule;
        const enabled = b.textContent.trim() === 'Resume';
        fetchJSON(API.scheduleToggle(id), { method: 'POST', body: JSON.stringify({ enabled }) }).then(() => refreshSchedules());
      }));
    })
    .catch(() => {});
}

/* =========================== Webhooks =========================== */

function saveWebhook() {
  const url = $('#webhook-url').value.trim();
  const type = $('#webhook-type').value;
  const event = $('#webhook-event').value;
  if (!url) { toast('URL required', 'error'); return; }
  fetchJSON(API.webhooks, {
    method: 'POST',
    body: JSON.stringify({ url, type, event }),
  })
    .then(() => {
      toast('Webhook saved', 'success');
      $('#webhook-url').value = '';
      $('#webhook-modal').hidden = true;
      refreshWebhooks();
    })
    .catch(err => toast(err.message, 'error'));
}

function refreshWebhooks() {
  fetchJSON(API.webhooks)
    .then(({ webhooks }) => {
      const list = $('#webhook-list');
      if (!webhooks.length) {
        list.innerHTML = '<div style="font-size:11px;color:var(--text-mute);margin-top:8px;font-style:italic;">No webhooks yet</div>';
        return;
      }
      list.innerHTML = webhooks.map(w => `
        <div class="item-row">
          <div class="item-info">
            <div class="item-title">${escapeHtml(w.type)} · ${escapeHtml(w.event)}</div>
            <div class="item-meta">${escapeHtml(w.url.substring(0, 40))}...</div>
          </div>
          <button class="btn-danger" data-del-webhook="${w.id}">×</button>
        </div>
      `).join('');
      $$('[data-del-webhook]').forEach(b => b.addEventListener('click', () => {
        fetchJSON(API.webhook(b.dataset.delWebhook), { method: 'DELETE' }).then(() => refreshWebhooks());
      }));
    })
    .catch(() => {});
}

/* =========================== Compare =========================== */

function openCompareModal() {
  if (!state.currentRunId) return;
  fetchJSON(API.runs).then(({ runs }) => {
    const sel = $('#compare-b');
    sel.innerHTML = '<option value="">Pick a run...</option>' + runs
      .filter(r => r.id !== state.currentRunId)
      .map(r => `<option value="${r.id}">${escapeHtml(r.prompt.substring(0, 60))} (${r.total_records} rec)</option>`).join('');
    sel.value = '';
    $('#compare-result').innerHTML = '';
    sel.onchange = () => {
      if (!sel.value) { $('#compare-result').innerHTML = ''; return; }
      fetchJSON(`${API.compare}?a=${state.currentRunId}&b=${sel.value}`)
        .then(data => renderCompare(data))
        .catch(err => toast(err.message, 'error'));
    };
    $('#compare-modal').hidden = false;
  });
}

function renderCompare(data) {
  const diff = data.diff || {};
  $('#compare-result').innerHTML = `
    <table class="compare-table">
      <tr><th></th><th>${escapeHtml((data.a.run.prompt || '').substring(0, 40))}</th><th>${escapeHtml((data.b.run.prompt || '').substring(0, 40))}</th></tr>
      <tr><td>Status</td><td>${data.a.run.status}</td><td>${data.b.run.status}</td></tr>
      <tr><td>Records</td><td>${diff.a_records}</td><td>${diff.b_records}</td></tr>
      <tr><td>Avg score</td><td>${diff.a_avg_score}</td><td>${diff.b_avg_score}</td></tr>
      <tr><td>Sources</td><td>${Object.entries(diff.a_sources || {}).map(([k,v]) => `${escapeHtml(k)}: ${v}`).join('<br>')}</td><td>${Object.entries(diff.b_sources || {}).map(([k,v]) => `${escapeHtml(k)}: ${v}`).join('<br>')}</td></tr>
    </table>
  `;
}