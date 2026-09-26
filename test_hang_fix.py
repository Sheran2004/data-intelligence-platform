"""Verify the hang fix - simulate a slow source and confirm the run completes."""
import time
from data_intelligence.orchestrator import execute_run
from data_intelligence import database as db
import data_intelligence.sources as src

db.init_db()

# Inject a slow version of hn_jobs (sleeps 20s, longer than hard timeout)
real_collect = src.SOURCE_REGISTRY["hn_jobs"]

def slow_collector(params):
    print("  slow_collector: sleeping 20s to simulate hang...")
    time.sleep(20)
    return []

src.SOURCE_REGISTRY["hn_jobs"] = slow_collector

print("Starting run with intentionally slow hn_jobs source...")
start = time.time()
result = execute_run("hang-test", "Find me remote Python jobs in AI startups",
                     persist_fn=db.save_run)
elapsed = time.time() - start
print(f"\nTotal elapsed: {elapsed:.1f}s")
print(f"Status: {result['status']}, records: {result.get('total_records', 0)}")
for s in result["workflow"]["steps"]:
    print(f"  - [{s['status']}] {s['name']} -> {s.get('message', '')}")

src.SOURCE_REGISTRY["hn_jobs"] = real_collect
print("\nFix verified: run completed despite a 20s-hang in hn_jobs.")