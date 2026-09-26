"""Quick smoke test - run the orchestrator end-to-end without the web server."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_intelligence.ai_engine import get_engine
from data_intelligence.workflow_builder import WorkflowBuilder
from data_intelligence.orchestrator import execute_run
from data_intelligence import database as db
from data_intelligence import data_processor as dp_mod

# 1. AI engine
print("=" * 60)
print("TEST 1: AI Engine")
print("=" * 60)
engine = get_engine()
tests = [
    "Find me remote Python developer jobs in AI startups, posted in the last 7 days",
    "Collect SaaS leads in fintech from USA, top 30 companies",
    "Get sponsorship opportunities for AI conferences, give me 15 results",
    "Find trending Rust open source repos with more than 1000 stars",
    "Find me top 20 market data points for cybersecurity spend growth",
]
for prompt in tests:
    intent = engine.parse(prompt)
    print(f"\nPrompt: {prompt}")
    print(f"  -> type={intent.data_type}, skills={intent.skills[:5]}, locs={intent.locations}, ind={intent.industries}, max={intent.max_results}")
    print(f"  -> time_window_hours={intent.time_window_hours}, freshness={intent.freshness}")

# 2. Workflow builder
print("\n" + "=" * 60)
print("TEST 2: Workflow Builder")
print("=" * 60)
intent = engine.parse(tests[0])
wf = WorkflowBuilder().build(intent)
print(f"Workflow: {wf.name}")
print(f"Steps ({len(wf.steps)}):")
for s in wf.steps:
    print(f"  - [{s.type}] {s.name} (source={s.source})")

# 3. End-to-end orchestrator with mock sources only (no network)
print("\n" + "=" * 60)
print("TEST 3: End-to-end (using mocks only, fast)")
print("=" * 60)
db.init_db()

def persist(run_meta, records):
    db.save_run(run_meta, records)

result = execute_run("test01", "Find me top 10 Python jobs in USA", persist_fn=persist)
print(f"Status: {result['status']}")
print(f"Total records: {result['total_records']}")
print(f"\nFirst 3 records:")
for r in result['records'][:3]:
    print(f"  - [{r['source']}] {r['title']} (score={r['score']})")

# 4. Dedup + validate
print("\n" + "=" * 60)
print("TEST 4: Data processor stats")
print("=" * 60)
sample = result['records'] + result['records'][:5]  # add duplicates
valid, invalid = dp_mod.validate(sample)
print(f"Input: {len(sample)}, Valid: {len(valid)}, Invalid: {len(invalid)}")
unique, removed = dp_mod.dedupe(valid)
print(f"After dedup: {len(unique)}, Removed: {removed}")

# 5. Stats
print("\n" + "=" * 60)
print("TEST 5: DB stats")
print("=" * 60)
print(db.stats())

print("\nAll smoke tests passed.")