"""
One-shot DB fix - drops watchlist + notifications tables so init_db() can
recreate them with the correct schema on next Flask start.
"""
import os
import sqlite3

DB_PATH = os.path.join("data", "platform.db")
if not os.path.exists(DB_PATH):
    print(f"Database file not found at {DB_PATH} - nothing to fix.")
    raise SystemExit(0)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Show what tables currently exist
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print(f"Existing tables: {tables}")

# Show current watchlist schema (if any)
try:
    cur.execute("SELECT sql FROM sqlite_master WHERE name='watchlist'")
    row = cur.fetchone()
    print(f"Current watchlist schema: {row[0] if row else '(does not exist)'}")
except Exception as e:
    print(f"watchlist schema read error: {e}")

# Drop both tables - init_db() will recreate them with correct schema
for t in ("watchlist", "notifications"):
    try:
        cur.execute(f"DROP TABLE IF EXISTS {t}")
        print(f"  dropped {t}")
    except Exception as e:
        print(f"  could not drop {t}: {e}")

conn.commit()
conn.close()
print("DONE. Restart Flask and init_db() will recreate the tables.")