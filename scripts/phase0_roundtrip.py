"""Phase 0 exit tests 2 & 3 — FalkorDB probe (§17).

  write: create probe node + report the redis data dir (checks volume target)
  read:  match the probe node, assert exact values (create/match round-trip)
  clean: delete the probe node (run once persistence is verified)

Run: .venv/bin/python scripts/phase0_roundtrip.py <write|read|clean>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph import get_db, get_graph  # noqa: E402

PROBE_ID = "p0"
EXPECTED = ("ada", 36)


def _cell(v):
    return v.decode() if isinstance(v, bytes) else v


def write() -> int:
    g = get_graph()
    g.query(
        "MERGE (p:Phase0Probe {id: $id}) SET p.name = $name, p.age = $age",
        {"id": PROBE_ID, "name": EXPECTED[0], "age": EXPECTED[1]},
    )
    print("CONFIG dir =", get_db().execute_command("CONFIG", "GET", "dir"))
    print("WRITE ok: Phase0Probe created")
    return 0


def read() -> int:
    rows = get_graph().query(
        "MATCH (p:Phase0Probe {id: $id}) RETURN p.name, p.age",
        {"id": PROBE_ID},
    ).result_set
    ok = len(rows) == 1 and tuple(_cell(v) for v in rows[0]) == EXPECTED
    print("READ rows =", rows)
    print("PASS: round-trip exact" if ok else f"FAIL: expected {EXPECTED}, got {rows}")
    return 0 if ok else 1


def clean() -> int:
    get_graph().query("MATCH (p:Phase0Probe) DELETE p")
    print("CLEAN ok: probe removed")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fns = {"write": write, "read": read, "clean": clean}
    if cmd not in fns:
        sys.exit(f"usage: {sys.argv[0]} <write|read|clean>")
    sys.exit(fns[cmd]())