# How to Run & Test - AI Data Intelligence Platform

## 1. Project Structure

```
data-intelligence-platform/
├── app.py                       # Flask entry-point (run this)
├── requirements.txt
├── run.bat                      # Windows one-click launcher
├── README.md
├── RUN_AND_TEST.md              # <- this file
├── .gitignore
├── data_intelligence/
│   ├── ai_engine.py             # Prompt -> Intent parser (Hinglish-aware)
│   ├── workflow_builder.py      # Intent -> Workflow plan
│   ├── orchestrator.py          # Executes workflows asynchronously
│   ├── data_processor.py        # Normalize / Validate / Dedupe / Enrich
│   ├── sources.py               # Real + mock data sources
│   ├── database.py              # SQLite persistence
│   ├── ai_summarizer.py         # Auto-generates natural-language insights
│   ├── demo.py                  # Pre-canned demo run seeder
│   └── scheduler.py             # Background scheduler for recurring runs
├── templates/
│   └── index.html               # Dashboard markup
├── static/
│   ├── css/style.css            # UI styles (dark + light themes)
│   └── js/app.js                # Dashboard logic (charts, voice, etc.)
├── smoke_test.py                # CLI smoke test (no browser needed)
└── test_hang_fix.py             # Verifies the hang-protection fix
```

## 2. Features Overview

| Feature | What it does |
|---------|-------------|
| **Prompt Understanding** | Plain-English (incl. Hinglish) → structured intent (type, skills, locations, industries, time window, count) |
| **Dynamic Workflows** | Auto-generates 3-source collect + process/validate/dedupe/enrich pipeline |
| **Multi-source Collection** | Real APIs (HN Algolia, GitHub, RemoteOK) + curated mocks as fallbacks |
| **Source Health** | Per-source latency, success rate, status indicator (green/yellow/red) |
| **AI Summary** | Auto-generates a narrative + insights (avg score, source-backed %, recent count, top skills, patterns, highlights) |
| **Visual Charts** | SVG donut (records by source) + bar chart (score distribution) - no external deps |
| **Dark/Light Theme** | Toggle in top-right corner, persists in localStorage |
| **Voice Prompt** | Web Speech API for browser-based speech-to-text (mic button on textarea) |
| **Load Demo** | One-click seeds 6 pre-canned runs across all data types for instant demo |
| **Schedules** | Cron-style recurring runs ("re-run every 1 hour") |
| **Webhooks** | Slack/Discord/Generic notifications when a run completes or fails |
| **Public Share Link** | Generate read-only URL to share a run's results |
| **Compare Runs** | Side-by-side metrics table for any 2 runs |
| **Search/Filter/Export** | Per-run record search by text/source/score + JSON/CSV export |
| **Replay & Delete** | Re-run any prompt or clean up old runs |

## 3. How to Run in VS Code

### Step 1 - Unzip
Extract `data-intelligence-platform.zip` anywhere. Open the folder in VS Code.

### Step 2 - Create virtual environment & install
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
Or just double-click **`run.bat`** on Windows.

### Step 3 - Run the server
```bash
python app.py
```
Open **http://localhost:5000** in your browser.

## 4. Test Checklist

### A. Theme + Bootstrap
| # | Test | Expected |
|---|------|----------|
| 1 | Open `http://localhost:5000` | Dashboard loads, dark theme |
| 2 | Click 🌙 in top-right | Switches to light mode; click ☀️ to switch back |
| 3 | Reload page | Theme persists (localStorage) |

### B. Load Demo (instant wow factor)
| # | Test | Expected |
|---|------|----------|
| 4 | Click "⚡ Load Demo" (sidebar or empty-state) | 6 runs are seeded instantly across all data types |
| 5 | Sidebar populates with 6 runs | Each with a different prompt (jobs, leads, sponsors, repos, market, news) |
| 6 | Click any demo run | Full workflow + summary + records + charts visible |

### C. AI Summary + Visual Charts
| # | Test | Expected |
|---|------|----------|
| 7 | Open any demo run | "AI-Generated Insights" card shows narrative + 6 insight tiles |
| 8 | Scroll to "Visual Analytics" | Donut chart of records by source + bar chart of score buckets |
| 9 | Toggle theme | Chart colors adapt automatically |
| 10 | "Source Health (this run)" card | Each source with green/yellow/red dot + latency in ms |

### D. Natural-language + Hinglish
Try these example chips (sidebar) or write your own:
| # | Test | Expected |
|---|------|----------|
| 11 | "Remote Python jobs (AI startups)" | Parsed correctly, runs workflow |
| 12 | "Mujhe remote Python developer ki naukri chahiye India me" | Hinglish parsed, `data_type=job`, locations=[remote, india] |
| 13 | "Mujhe AI startup ke liye sponsorship chahiye" | Hinglish parsed, `data_type=sponsor` |
| 14 | "Find me top 20 market data points for cybersecurity" | `data_type=market`, industry=cybersecurity, max=20 |

### E. Voice Prompt (Chrome/Edge)
| # | Test | Expected |
|---|------|----------|
| 15 | Click the 🎤 mic button on the empty-state textarea | Button turns red with pulsing animation, listens |
| 16 | Speak a prompt | Text appears in the textarea as you speak |
| 17 | Click mic again | Stops listening, button returns to normal |

### F. Schedules
| # | Test | Expected |
|---|------|----------|
| 18 | Sidebar → "Schedules" → "＋ Schedule recurring run" | Modal opens |
| 19 | Enter prompt + interval (e.g., 1 hour) → Save | Schedule appears in sidebar list |
| 20 | Wait for the scheduled run to fire | New run appears in "Recent Runs" sidebar |

### G. Webhooks (Slack/Discord)
| # | Test | Expected |
|---|------|----------|
| 21 | Sidebar → "Webhooks" → "＋ Add webhook" | Modal opens |
| 22 | Add a webhook URL (Slack, Discord, or generic) → Save | Webhook appears in sidebar |
| 23 | Trigger a run | Webhook gets fired on completion |

### H. Share + Compare
| # | Test | Expected |
|---|------|----------|
| 24 | Open a run → click "Share" | A share URL is generated, copied to clipboard, shown in a prompt |
| 25 | Open that URL in another browser/incognito | Public read-only view of the run |
| 26 | Open a run → click "Compare" | Modal opens, pick a second run from dropdown |
| 27 | Comparison table appears | Side-by-side metrics: status, records, avg score, sources |

### I. Live source-backed collection (existing tests)
| # | Test | Expected |
|---|------|----------|
| 28 | Run a **job** prompt | At least one `remoteok` or `hn_jobs` source with real records |
| 29 | Run a **repo** prompt | Real GitHub repos with `github.com/...` URLs |
| 30 | Record's **View source ↗** link | Opens the actual source URL |
| 31 | Wi-Fi OFF → run a prompt | Mock sources fill in, no failure |

### J. Export & management (existing)
| # | Test | Expected |
|---|------|----------|
| 32 | Click "Export JSON" / "Export CSV" | Downloads `dataset_<run-id>.{json,csv}` |
| 33 | Click "Replay" | New run starts with the same prompt |
| 34 | Click "Delete" + confirm | Removed from sidebar, counts drop |

### K. Robustness
| # | Test | Expected |
|---|------|----------|
| 35 | Run `python smoke_test.py` | All sections pass |
| 36 | Run `python test_hang_fix.py` | Even a 20s-hanging source completes in ~13s |

## 5. Quick API smoke test (no browser)
```bash
curl http://localhost:5000/api/stats
curl -X POST http://localhost:5000/api/preview -H "Content-Type: application/json" -d '{"prompt":"remote python jobs"}'
curl -X POST http://localhost:5000/api/runs -H "Content-Type: application/json" -d '{"prompt":"remote python jobs"}'
curl -X POST http://localhost:5000/api/demo/load            # seed demo runs
curl -X POST http://localhost:5000/api/schedules -H "Content-Type: application/json" -d '{"prompt":"AI jobs","interval_seconds":3600}'
curl -X POST http://localhost:5000/api/webhooks -H "Content-Type: application/json" -d '{"url":"https://example.com/hook","type":"slack","event":"run_done"}'
curl "http://localhost:5000/api/runs/compare?a=<id1>&b=<id2>"
```

## 6. Common gotchas
- **Port 5000 already in use?** macOS uses AirPlay on 5000. Disable it or change `port=5000` in `app.py`.
- **Voice input needs Chrome/Edge.** Firefox doesn't expose `SpeechRecognition`.
- **First run may take a few seconds** for live API calls (HN, GitHub, RemoteOK). Demo runs are instant.
- **`data/platform.db` is created on first run** and stores all data. Delete to reset.
- **Webhooks need a reachable URL.** Use a tunneling service (e.g. ngrok) for local testing.
- **Light theme + charts:** Charts re-render with appropriate colors when you toggle theme.

Enjoy! 🚀