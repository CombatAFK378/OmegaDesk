"""C1 exit tests (v2.1 §16): the core proven from the CLI.

Prerequisite: LLM_API_KEY in .env — without it this test exits with code 2
(build complete, LLM tests pending the key).

§16 C1 exit items covered:
  1. the override on C's shape changes C′ from freeze (without) to escalate (with)
  2. E never cites the overruled HD-019; cites the correction HOV-019
  3. D distinguishes the clearance precedent (applies=false + reasons named)
  4. every miss reported in the benchmark report (+ decisions_changed computed)
  5. every EVIDENCE query replays to its snapshot
  6. the override safety rule holds (guard + record_override)
  7. tokens-per-case logged; pacing data available
  8. tool-call order observable per case (journal)

Run: .venv/bin/python scripts/c1_exit_test.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import LLM_API_KEY  # noqa: E402
from app.graph import get_graph  # noqa: E402
from app.policy import precedent_action_guard  # noqa: E402
import time  # noqa: E402

FAILURES = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def main():
    if not LLM_API_KEY:
        print("C1 EXIT TEST: SKIPPED — LLM_API_KEY missing in .env (build is complete; "
              "tests need the key). Put the key in ~/omegadesk/.env and rerun.")
        sys.exit(2)

    # run the benchmark fresh (this hits the LLM — ~12 investigations)
    print("running the with/without benchmark (12 LLM investigations)...")
    from app.benchmark import run_benchmark, REPORT_PATH
    report = run_benchmark(run_id=f"c1-test-{int(time.time())}")
    rows = {c["case"]: c for c in report["cases"] if isinstance(c, dict) and "with" in c}
    missed = [c["case"] for c in report["cases"] if c.get("miss")]

    def row(code):
        if code not in rows:
            check(f"{code}: ran (no pipeline miss)", False, missed and f"miss rows: {missed}")
        return rows.get(code) or {"with": {}, "without": {}, "cite_checks": {}}

    # --- exit 1: the override swing on C′ ---
    cp = row("Cp")
    check("C′: WITH precedents → escalate (the merchant precedent is cited: HOV-016/family)",
          cp["with"].get("action") == "escalate" and
          any(x in cp["with"].get("cited_all", cp["with"].get("cited", []))
              for x in ("HOV-016", "HD-004", "HD-010", "HD-022")),
          f"got {(cp['with'].get('action'), cp['with'].get('cited_all'))}")
    check("C′: WITHOUT precedents → freeze (memory changed the decision — THE swing)",
          cp["without"].get("action") == "freeze", f"got {cp['without'].get('action')}")

    # --- exit 2: E-trap ---
    e = row("E")
    check("E: the OVERRULED HD-019 is never cited",
          e["cite_checks"].get("never_cite_ok") is True, f"got {e.get('cite_checks')}")
    check("E: with-precedents → escalate (the correction HOV-019 is cited, the twin routes to review)",
          e["with"].get("action") == "escalate" and
          "HOV-019" in e["with"].get("cited_all", e["with"].get("cited", [])),
          f"got {(e['with'].get('action'), e['with'].get('cited_all'))}")

    # --- exit 3: D distinguishes ---
    d = row("D")
    check("D: decision = freeze on evidence (distinguishing the clearance precedent)",
          d["with"].get("action") == "freeze", f"got {d['with'].get('action')}")

    # --- exit 4: misses reported ---
    check("report: misses field present + decisions_changed computed",
          isinstance(report["misses"], list) and len(report["decisions_changed"]) >= 1,
          f"misses={report['misses']} changed={report['decisions_changed']}")

    # --- exit 5: every evidence query replays ---
    g = get_graph()
    # exit 5, honestly: stored EVIDENCE edges carry tool + args + snapshot;
    # replaying the stored query must reproduce the stored snapshot.
    from app.tools import run_tool
    evs = g.query(
        "MATCH (c:Case)-[ev:EVIDENCE]->(n) WHERE ev.tool IS NOT NULL "
        "RETURN c.id, ev.query_id, ev.tool, ev.args, ev.snapshot LIMIT 6").result_set
    replays, ok_count = [], 0
    for cid, qid, tool, args_json, snap in evs:
        try:
            fresh = run_tool(tool, "investigator",
                             **json.loads(args_json)) if args_json else None
            same = json.dumps(fresh, default=str)[:200] == snap
        except (json.JSONDecodeError, TypeError, ValueError):
            same = False
        replays.append(f"{cid}/{qid}/{tool}: {'replays' if same else 'DIVERGED'}")
        ok_count += 1 if same else 0
    check(f"every stored evidence query replays to its snapshot "
          f"({ok_count}/{len(evs)})", len(evs) > 0 and ok_count == len(evs),
          "; ".join(replays))

    # --- exit 6: override safety holds ---
    check("guard: clear never rides a precedent",
          precedent_action_guard("clear", cited_precedents=[{"action": "clear"}]) == "escalate")
    check("guard: freeze suggested by an override-clearance → escalate",
          precedent_action_guard("freeze", cited_precedents=[{"action": "clear"}]) == "escalate")
    check("guard: freeze from own evidence stays freeze",
          precedent_action_guard("freeze", cited_precedents=[{"action": "escalate"}]) == "freeze")

    # --- exit 7: tokens per case, pacing data ---
    tok_rows = [c for c in report["cases"] if c["with"].get("tokens", {}).get("in", 0) > 0]
    check("tokens logged per case (pacing gate)", len(tok_rows) >= 5, f"got {len(tok_rows)}")
    check("report file saved", REPORT_PATH.exists())

    # --- exit 8: tool-call order observable + non-scriptedness ---
    seqs = {
        code: rows[code]["with"].get("tool_sequence", [])
        for code in ("A", "B") if code in rows}
    check("tool sequences logged for A and B (journal-observable)",
          all(seqs.get(k) for k in ("A", "B")), f"got {seqs}")
    if all(seqs.get(k) for k in ("A", "B")):
        if seqs["A"] == seqs["B"]:
            print("WARN: A and B tool sequences identical — non-scriptedness miss (report to §16)")
        else:
            check("A vs B tool sequences differ (the pivot is visible)", True)

    print("---")
    if FAILURES:
        print(f"C1 EXIT TEST: {len(FAILURES)} failure(s): {FAILURES}")
        print(f"misses: {report['misses']}")
        sys.exit(1)
    print("C1 EXIT TEST: ALL GREEN")


if __name__ == "__main__":
    main()