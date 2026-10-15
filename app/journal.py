"""Phase 3 — write journal (architecture §6: every write journaled).

One JSONL line per write action: who (actor), what (action), exactly which
node labels / edge types it created. The Phase 4 tool layer reuses journal()
for every tool call; the journal is the audit backbone for "nothing rogue".
"""
import json
from datetime import datetime

from .config import BASE_DIR

JOURNAL_PATH = BASE_DIR / "journal.jsonl"


def journal(actor, action, alerts=None, nodes=None, edges=None, **details):
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "actor": actor,
        "action": action,
        "nodes_written": nodes or [],
        "edges_written": edges or [],
        "alerts": alerts or [],
        **details,
    }
    with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry