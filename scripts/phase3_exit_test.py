"""Phase 3 exit tests — v2 monitor (v2.1 §16 R3):

  1. A injected → exactly ONE fan_in alert, TRIGGERED_BY a Transaction; rescan never dups
  2. C injected → the merchant fan-in FIRES (v2 flip!) — clearing is downstream
  3. Noise-only ticks → zero alerts (no crying wolf)
  4. Journal shows the monitor creating only Alert nodes (+TRIGGERED_BY)
  5. Bonus: B (clean funnel) fires via shape alone — the pivot case

Run: .venv/bin/python scripts/phase3_exit_test.py
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.journal import JOURNAL_PATH  # noqa: E402
from app.graph import get_graph  # noqa: E402
from app.monitor import scan_once  # noqa: E402
from seed.seed import seed_graph  # noqa: E402
from sim.generator import inject_scenario_a, inject_scenario_b, inject_scenario_c, noise_tick  # noqa: E402

FAILURES = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def alert_total(g):
    return g.query("MATCH (a:Alert) RETURN count(a)").result_set[0][0]


def t1_fanin_on_a():
    print("--- exit 1: A → exactly one fan_in alert ---")
    g = get_graph()
    seed_graph()
    inject_scenario_a(g)
    scan_once(g)
    check("A: exactly one new alert (26 total incl. the 25 seeded alerts)",
          alert_total(g) == 26, f"got {alert_total(g)}")
    link = g.query(
        "MATCH (al:Alert {target_id:'A-EXIT'})-[tb:TRIGGERED_BY]->(t:Transaction) "
        "RETURN al.type, al.sender_count, count(tb)").result_set
    check("A: fan_in alert on A-EXIT, 5 senders, TRIGGERED_BY a Transaction",
          link == [["fan_in", 5, 1]], f"got {link}")
    scan_once(g)
    check("A: rescan does not duplicate (no status needed — type+target dedup)",
          alert_total(g) == 26, f"got {alert_total(g)}")


def t2_merchant_fanin_fires():
    print("--- exit 2: C (merchant fan-in) → FIRES (v2 flip) ---")
    g = get_graph()
    seed_graph()
    inject_scenario_c(g)
    scan_once(g)
    link = g.query(
        "MATCH (al:Alert {target_id:'A-MER-PAY'}) RETURN al.type, al.sender_count").result_set
    check("C: fan_in alert on the merchant account with 10 senders (cleared downstream, not here)",
          link == [["fan_in", 10]] and alert_total(g) == 26, f"got {link}")


def t3_noise_zero():
    print("--- exit 3: noise-only ticks → zero alerts ---")
    g = get_graph()
    seed_graph()
    rng = random.Random(7)
    for i in range(20):  # mirrors the live loop: tick → scan
        noise_tick(g, rng, i)
        scan_once(g)
    check("20 noise ticks + scans → zero new alerts (no crying wolf)",
          alert_total(g) == 25, f"got {alert_total(g)}")


def t4_journal():
    print("--- exit 4: journal shows monitor writing only Alert nodes ---")
    lines_before = 0
    if JOURNAL_PATH.exists():
        lines_before = len(JOURNAL_PATH.read_text(encoding="utf-8").splitlines())
    g = get_graph()
    seed_graph()
    inject_scenario_a(g)
    scan_once(g)
    entries = [json.loads(l) for l in
               JOURNAL_PATH.read_text(encoding="utf-8").splitlines()[lines_before:]]
    monitor_entries = [e for e in entries if e.get("actor") == "monitor"]
    check("journal: monitor scan recorded", len(monitor_entries) >= 1,
          f"got {len(monitor_entries)} monitor entries of {len(entries)} new")
    only_alerts = all(
        set(e.get("nodes_written", [])) <= {"Alert"}
        and set(e.get("edges_written", [])) <= {"TRIGGERED_BY"}
        for e in monitor_entries)
    check("journal: monitor writes ⊆ {Alert nodes, TRIGGERED_BY edges} — nothing rogue",
          only_alerts,
          f"got {[(e['nodes_written'], e['edges_written']) for e in monitor_entries]}")
    raised = [e for e in monitor_entries if e.get("alerts")]
    check("journal: scan entry carries the fan_in payload",
          any(any(a.get("type") == "fan_in" for a in e["alerts"]) for e in raised))


def t5_bonus_b():
    print("--- bonus: B (clean funnel, the pivot case) fires via shape alone ---")
    g = get_graph()
    seed_graph()
    inject_scenario_b(g)
    scan_once(g)
    link = g.query(
        "MATCH (al:Alert {target_id:'A-BT'}) RETURN al.type, al.sender_count").result_set
    check("B: fan_in on A-BT with 8 senders — no device fingerprints involved",
          link == [["fan_in", 8]] and alert_total(g) == 26, f"got {link}")


def main():
    t1_fanin_on_a()
    t2_merchant_fanin_fires()
    t3_noise_zero()
    t4_journal()
    t5_bonus_b()
    print("---")
    if FAILURES:
        print(f"PHASE 3 EXIT TEST (v2): {len(FAILURES)} failure(s): {FAILURES}")
        sys.exit(1)
    print("PHASE 3 EXIT TEST (v2): ALL GREEN")


if __name__ == "__main__":
    main()