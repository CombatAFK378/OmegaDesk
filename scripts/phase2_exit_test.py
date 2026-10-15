"""Phase 2 exit tests — v2 model (v2.1 §16 R2):

  1. Noise-only T ticks → exact predicted growth; zero new alerts
  2. Inject A → D1 device edges + funnel Transaction chains
  3. Same scripted sequence twice → identical counts (determinism)
  4. Inject C → 10 customers → merchant account via OPERATED_BY/KYC shape

Run: .venv/bin/python scripts/phase2_exit_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph import get_graph  # noqa: E402
from seed.schema import graph_counts  # noqa: E402
from seed.seed import seed_graph  # noqa: E402
from sim.generator import (  # noqa: E402
    NOISE_DEVICE_EVERY, NOISE_TXN_PER_TICK, inject_scenario_a,
    inject_scenario_b, inject_scenario_c, noise_ticks,
)

FAILURES = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def nonzeros(d):
    return {k: v for k, v in d.items() if v}


def deltas(now, base):
    return {k: now[k] - base[k] for k in now}


def t1_noise_growth():
    print("--- exit 1: noise-only growth ---")
    g = get_graph()
    base_n, base_e = seed_graph()
    ticks = 20
    noise_ticks(g, ticks)
    nodes, edges = graph_counts(g)
    dn, de = nonzeros(deltas(nodes, base_n)), nonzeros(deltas(edges, base_e))
    exp_devices = len([i for i in range(ticks) if i % NOISE_DEVICE_EVERY == 0])
    exp_dn = {"Device": exp_devices, "Transaction": NOISE_TXN_PER_TICK * ticks}
    exp_de = {"SENT": NOISE_TXN_PER_TICK * ticks, "TO": NOISE_TXN_PER_TICK * ticks,
              "USED_DEVICE": exp_devices}
    check(f"noise nodes grow exactly (+{NOISE_TXN_PER_TICK * ticks} transactions, {exp_devices} devices)",
          dn == exp_dn, f"got {dn}")
    check("noise edges grow exactly (+SENT/+TO/+USED_DEVICE only)", de == exp_de, f"got {de}")
    check("noise-only: zero new alerts (no crying wolf)", dn.get("Alert", 0) == 0, f"got {dn.get('Alert')}")


def t2_scenario_a():
    print("--- exit 2: scenario A — device ring on D1 ---")
    g = get_graph()
    base_n, base_e = seed_graph()
    inject_scenario_a(g)
    nodes, edges = graph_counts(g)
    dn, de = nonzeros(deltas(nodes, base_n)), nonzeros(deltas(edges, base_e))
    check("A: +29 nodes (9 persons + 9 accounts + 11 transactions)",
          dn == {"Person": 9, "Account": 9, "Transaction": 11}, f"got {dn}")
    check("A: +11 SENT +11 TO +9 OWNS +5 USED_DEVICE",
          de == {"OWNS": 9, "SENT": 11, "TO": 11, "USED_DEVICE": 5}, f"got {de}")
    d1_devices = g.query(
        "MATCH (:Account)-[:USED_DEVICE]->(:Device {id:'D1'}) RETURN count(*)"
    ).result_set[0][0]
    check("A: D1 device edges present (2 seed + 5 new = 7)", d1_devices == 7, f"got {d1_devices}")
    funnel = g.query(
        "MATCH (:Account)-[:SENT]->(t:Transaction)-[:TO]->(:Account {id:'A-EXIT'}) "
        "RETURN count(t), sum(t.amount)").result_set[0]
    check("A: nightly funnel → exit wallet (5 transactions, 291600 total)",
          funnel == [5, 291600], f"got {funnel}")
    sub_thr = g.query(
        "MATCH (:Account)-[:SENT]->(t:Transaction)-[:TO]->(:Account {id:'A-M4'}) "
        "WHERE t.amount < 50000 RETURN count(t)").result_set[0][0]
    check("A: sub-threshold transactions into mule (< 50k) present", sub_thr == 2, f"got {sub_thr}")


def t3_determinism():
    print("--- exit 3: full scripted sequence twice → identical ---")

    def run():
        g = get_graph()
        seed_graph()
        noise_ticks(g, 15)
        inject_scenario_a(g)
        inject_scenario_b(g)
        return graph_counts(g)

    r1 = run()
    g1 = get_graph()
    bdev = g1.query(
        "MATCH (:Device {id:'D1'})<-[:USED_DEVICE]-(a:Account) WHERE a.id STARTS WITH 'A-B' "
        "RETURN count(*)").result_set[0][0]
    check("B has no device overlap with the D1 ring", bdev == 0, f"got {bdev}")
    r2 = run()
    check("determinism: run twice → identical counts", r1 == r2, "differs")


def t4_scenario_c():
    print("--- exit 4: scenario C — merchant fan-in (v2 false positive) ---")
    g = get_graph()
    base_n, base_e = seed_graph()
    inject_scenario_c(g)
    nodes, edges = graph_counts(g)
    dn = nonzeros(deltas(nodes, base_n))
    de = nonzeros(deltas(edges, base_e))
    check("C: +30 nodes (10 customers + 10 accounts + 10 transactions)",
          nonzeros(dn) == {"Person": 10, "Account": 10, "Transaction": 10}, f"got {nonzeros(dn)}")
    check("C: +30 edges (OWNS/SENT/TO ×10)",
          de == {"OWNS": 10, "SENT": 10, "TO": 10}, f"got {de}")
    flags = g.query(
        "MATCH (a:Account {id:'A-MER-PAY'})-[:OPERATED_BY]->(m:Merchant) "
        "RETURN m.business_kyc, m.registered_cadence").result_set
    check("C: merchant business-KYC + monthly cadence present", flags == [[True, "monthly"]],
          f"got {flags}")
    senders = g.query(
        "MATCH (s:Account)-[:SENT]->(:Transaction)-[:TO]->(:Account {id:'A-MER-PAY'}) "
        "RETURN count(DISTINCT s)").result_set[0][0]
    check("C: 10 distinct payers into the merchant account (fan-in shape, fires at R3)",
          senders == 10, f"got {senders}")


def main():
    t1_noise_growth()
    t2_scenario_a()
    t3_determinism()
    t4_scenario_c()
    print("---")
    if FAILURES:
        print(f"PHASE 2 EXIT TEST (v2): {len(FAILURES)} failure(s): {FAILURES}")
        sys.exit(1)
    print("PHASE 2 EXIT TEST (v2): ALL GREEN")


if __name__ == "__main__":
    main()