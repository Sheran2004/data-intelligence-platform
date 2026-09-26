# AI-Powered Data Intelligence Platform

> **Prompt → Workflow → Source-backed Dataset.** Turn any natural-language business requirement into a clean, structured, traceable dataset with a managed end-to-end workflow.

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](runtime.txt)
[![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)](https://flask.palletsprojects.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Deploy](https://img.shields.io/badge/Deploy-Docker%20%7C%20Heroku%20%7C%20Render-blueviolet)](DEPLOY.md)

Built for **Code Cubicle 6.0 — Problem Statement 01**.

---

## ✨ Features

### Core
- 🧠 **Prompt Understanding** — Plain-English (incl. **Hinglish/Hindi**) → structured intent (type, skills, locations, industries, time window, count)
- 🔄 **Dynamic Workflows** — Auto-generates collect → process → validate → dedupe → enrich pipeline
- 🌐 **Multi-source Collection** — Real APIs (**HN Algolia**, **GitHub**, **RemoteOK**) + curated mocks as reliable fallbacks
- ✅ **Data Quality Pipeline** — URL validation, PII detection, field coverage, completeness scoring
- 📊 **Source Health Tracking** — Per-source latency, success rate, status indicator

### Dashboard
- 📈 **Visual Analytics** — SVG donut (records-by-source) + bar chart (score distribution) + line chart (records over time)
- 🤖 **AI-Generated Insights** — Auto-narrative + 6 insight tiles + patterns + top-3 highlights
- 🎨 **Dark/Light Theme** — Toggle with localStorage persistence
- ⭐ **Watchlist** — Star important records, view them in a dedicated panel
- 🔍 **Source Explorer** — Click any source in charts to see all its records + quality metrics
- 📦 **Bulk Export** — Download every dataset as a single ZIP archive
- 📡 **SSE Live Updates** — True real-time, no polling

### Automation
- ⏰ **Recurring Schedules** — Cron-style ("run every 1 hour")
- 🪝 **Webhooks** — Slack / Discord / Generic JSON notifications
- 🆎 **A/B Test Prompts** — Run 2-4 variants in parallel, compare results
- ↻ **Replay & Diff** — See exactly what changed when re-running
- 🎤 **Voice Prompt** — Web Speech API speech-to-text

### Management
- 📋 **History Search + Filter** — Filter by status (All/Done/Running/Failed), full-text search
- 🗑️ **Single + Bulk Delete** — × on each sidebar item, or Clear All
- 📤 **Public Share Links** — Read-only URL for any run
- ⌨️ **Keyboard Shortcuts** — N (new), D (demo), T (theme), B (A/B), / (search), Esc (close)

---

## 🚀 Quick Start

### Local
```bash
git clone https://github.com/<you>/data-intelligence-platform.git
cd data-intelligence-platform
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Open **http://localhost:5000**.

### Production
See [DEPLOY.md](DEPLOY.md) for full guides covering Docker, Heroku, Render, Railway, Fly.io, DigitalOcean, and VPS.

### One-command Docker
```bash
docker build -t dip . && docker run -p 5000:5000 -v $(pwd)/data:/app/data dip
```

---

## 🏗 Architecture

```
┌────────────────┐    ┌────────────────┐    ┌──────────────────────┐
│ User prompt    │ -> │ AI Engine       │ -> │ Workflow Builder     │
│  (plain text)  │    │ (intent parse)  │    │ (steps + sources)    │
└────────────────┘    └────────────────┘    └──────────────────────┘
                                                      │
                                                      v
                                            ┌──────────────────────┐
                                            │ Orchestrator         │
                                            │ (executes async)     │
                                            └──────────────────────┘
                                                      │
                          ┌───────────────┬───────────┼───────────────┐
                          v               v           v               v
                     ┌─────────┐     ┌─────────┐ ┌─────────┐    ┌──────────┐
                     │ Sources │     │ Sources │ │ Sources │    │ Process  │
                     │  HN Alg │     │ RemoteOK│ │ GitHub  │    │ Validate │
                     │ Real    │     │ Real    │ │ Real    │    │ Dedupe   │
                     │ Sources │     │ Mocks   │ │ Mocks   │    │ Enrich   │
                     └─────────┘     └─────────┘ └─────────┘    │ Quality  │
                                                                └──────────┘
                                                                       │
                                                                       v
                                                          ┌─────────────────────┐
                                                          │ SQLite + Dashboard  │
                                                          │ + SSE + Webhooks    │
                                                          └─────────────────────┘
```

---

## 📁 Project Layout

```
data-intelligence-platform/
├── app.py                      # Flask entry-point
├── wsgi.py                     # Production WSGI entry
├── requirements.txt
├── Procfile                    # Heroku-style deploy
├── runtime.txt                 # Python version pin
├── Dockerfile                  # Container build
├── .dockerignore
├── .env.example
├── .github/workflows/ci.yml    # GitHub Actions CI
├── LICENSE                     # MIT
├── README.md
├── DEPLOY.md                   # Deploy guides for 8 platforms
├── RUN_AND_TEST.md             # Test checklist
├── CONTRIBUTING.md
├── run.bat                     # Windows one-click launcher
├── data_intelligence/
│   ├── ai_engine.py            # Prompt -> Intent (Hinglish-aware)
│   ├── workflow_builder.py     # Intent -> Workflow plan
│   ├── orchestrator.py         # Async executor + SSE pub/sub
│   ├── data_processor.py       # Normalize / Validate / Dedupe / Enrich
│   ├── data_quality.py         # URL/PII/quality checks
│   ├── sources.py              # Real + mock data sources
│   ├── database.py             # SQLite persistence
│   ├── ai_summarizer.py        # Auto-generates insights
│   ├── demo.py                 # Pre-canned demo seeder
│   └── scheduler.py            # Background scheduler
├── templates/
│   ├── index.html              # Dashboard
│   └── share.html              # Public share view
├── static/
│   ├── css/style.css
│   └── js/app.js
├── smoke_test.py
└── test_hang_fix.py
```

---

## 🧪 Testing

```bash
python smoke_test.py        # CLI smoke test
python test_hang_fix.py     # Verify hang protection
```

See [RUN_AND_TEST.md](RUN_AND_TEST.md) for the full 36-item test checklist.

---

## 🛠 Tech Stack

| Layer | Tech |
|------|------|
| Backend | Flask + Flask-CORS + Gunicorn |
| Storage | SQLite |
| AI / NLP | Custom rule-based parser (intent + entity extraction, Hinglish-aware) |
| Real sources | Hacker News (Algolia), RemoteOK, GitHub REST |
| Frontend | Vanilla JS + modern CSS (no framework dependency) |
| Async | Threading for non-blocking workflows |
| Real-time | Server-Sent Events (SSE) |
| CI | GitHub Actions (lint + smoke test) |
| Deploy | Docker + Heroku + Render + Fly.io + VPS |

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 📜 License

[MIT](LICENSE) — use freely.

---

## 🏆 Built for Code Cubicle 6.0

**Problem Statement 01** — *AI-Powered Data Intelligence Platform*
- Understands natural-language data requirements ✓
- Dynamically designs and executes workflows ✓
- Cleans, structures, validates, deduplicates ✓
- Source-backed, traceable data ✓
- Manages collection tasks ✓
- Interactive dashboard ✓
- Workflow + dataset history ✓
- Search, filter, and export ✓
- **Plus:** dark/light theme, charts, voice prompt, A/B testing, schedules, webhooks, share links, watchlist, data quality, deploy support...