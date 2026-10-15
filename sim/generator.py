"""R2 — event emitters ("the world", architecture v2.1 §3/§5).

Every event is written to the graph the moment it emits. All emitters are
deterministic (fixed ids + timestamps + seeded rng) so a scripted run replays
to identical counts — the §16 determinism gate.

v2 shape: each transfer is a Transaction node —
(Account)-[:SENT {ts}]->(:Transaction {id, amount, ts})-[:TO {ts}]->(Account)
"""
import random
from datetime import datetime, timedelta

from app.graph import get_graph

SUB_THRESHOLD = 50000                     # §5 reporting threshold
SIM_EPOCH = datetime(2026, 1, 1)          # sim clock origin; 1 tick = 1 sim hour
BASELINE_IDS = [f"A-{i:03d}" for i in range(1, 13)]
MERCHANT_ACCOUNT = "A-MER-PAY"

NOISE_TXN_PER_TICK = 2                    # exit-test math depends on these two
NOISE_DEVICE_EVERY = 10


def _tick_ts(tick_index, rng):
    t = SIM_EPOCH + timedelta(hours=tick_index, minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
    return t.strftime("%Y-%m-%dT%H:%M")


def _txn(g, tid, src, dst, amount, ts):
    g.query(
        """MATCH (s:Account {id:$src}), (d:Account {id:$dst})
           CREATE (s)-[:SENT {ts:$ts}]
                  ->(:Transaction {id:$tid, amount:$amount, ts:$ts})
                  -[:TO {ts:$ts}]->(d)""",
        {"tid": tid, "src": src, "dst": dst, "amount": amount, "ts": ts},
    )


def _new_person_account(g, pid, pname, kyc, aid, since="2026-01-01", acc_type="customer"):
    g.query(
        """CREATE (:Person {id:$pid, name:$pname, kyc_status:$kyc})
               -[:OWNS {ts:$since}]->
           (:Account {id:$aid, opened_at:$since, type:$acc_type})""",
        {"pid": pid, "pname": pname, "kyc": kyc, "aid": aid, "since": since, "acc_type": acc_type},
    )


def noise_tick(g, rng, tick_index):
    """One boring hour: 2 normal transfers; every 10th tick a device joins.
    Amounts stay ≤ ₹44,999: ALWAYS below the ₹45k SUB_THRESHOLD band floor →
    sub-threshold can never fire on noise; with ≤12 transfers per 6h velocity
    window the max noise outflow is 12 × ₹45k = ₹5.4L < the ₹6L cap → velocity
    can never fire on noise either. Math guarantees "no crying wolf" for ANY
    run length (found live after the 20-tick gate missed it, Oct 14)."""
    a, b, c, d = rng.sample(BASELINE_IDS, 4)
    for k, (src, dst) in enumerate(((a, b), (c, d)), start=1):
        _txn(g, f"TX-N{tick_index:04d}-{k}", src, dst,
             rng.randint(5000, 44999), _tick_ts(tick_index, rng))
    if tick_index % NOISE_DEVICE_EVERY == 0:
        g.query(
            """MATCH (acc:Account {id:$aid})
               CREATE (dev:Device {id:$did, fingerprint:$fp})
               CREATE (acc)-[:USED_DEVICE {ts:$ts}]->(dev)""",
            {"aid": rng.choice(BASELINE_IDS), "did": f"D-N{tick_index:04d}",
             "fp": f"fp-noise-{tick_index}", "ts": _tick_ts(tick_index, rng)},
        )


def noise_ticks(g, count, rng_seed=7):
    rng = random.Random(rng_seed)
    for i in range(count):
        noise_tick(g, rng, i)


def inject_scenario_a(g=None):
    """A — device ring: 5 fresh mules share device D1 (same device as the seeded
    2025 Decision), sub-threshold inflows, nightly funnel to an exit wallet.
    The D1 overlap is what makes the precedent-citation moment work."""
    g = g or get_graph()
    for pid, pname, kyc, aid in [
        ("P-F1", "Kunal Bagchi", True, "A-F1"), ("P-F2", "Reshma Shetty", True, "A-F2"),
        ("P-F3", "Arun Pillai", True, "A-F3"),
        ("P-M1", "Mule One", False, "A-M1"), ("P-M2", "Mule Two", False, "A-M2"),
        ("P-M3", "Mule Three", False, "A-M3"), ("P-M4", "Mule Four", False, "A-M4"),
        ("P-M5", "Mule Five", False, "A-M5"),
        ("P-EXIT", "Exit Wallet", False, "A-EXIT"),
    ]:
        _new_person_account(g, pid, pname, kyc, aid,
                            acc_type="exit" if pid == "P-EXIT" else "customer")
    inflows = [  # 6 sub-threshold drips from 3 feeders across 3 evenings
        ("A-F1", "A-M1", 49250, "2026-02-02T21:14", "TX-A001"),
        ("A-F1", "A-M2", 48900, "2026-02-02T22:03", "TX-A002"),
        ("A-F2", "A-M3", 49750, "2026-02-03T21:41", "TX-A003"),
        ("A-F2", "A-M4", 48300, "2026-02-03T22:58", "TX-A004"),
        ("A-F3", "A-M4", 47600, "2026-02-04T20:20", "TX-A005"),
        ("A-F3", "A-M5", 49100, "2026-02-04T23:12", "TX-A006"),
    ]
    funnel = [  # 5 consolidated night sweeps out of each mule (5 senders → exit)
        ("A-M1", 49000, "2026-02-05T03:07", "TX-A007"),
        ("A-M2", 48700, "2026-02-05T03:19", "TX-A008"),
        ("A-M3", 49500, "2026-02-05T03:26", "TX-A009"),
        ("A-M4", 95500, "2026-02-05T03:33", "TX-A010"),
        ("A-M5", 48900, "2026-02-05T03:41", "TX-A011"),
    ]
    for src, dst, amount, ts, tid in inflows:
        _txn(g, tid, src, dst, amount, ts)
    for src, amount, ts, tid in funnel:
        _txn(g, tid, src, "A-EXIT", amount, ts)
    for src, ts in [("A-M1", "2026-02-02T22:44"), ("A-M2", "2026-02-02T22:47"),
                    ("A-M3", "2026-02-03T23:01"), ("A-M4", "2026-02-03T23:35"),
                    ("A-M5", "2026-02-04T00:12")]:
        g.query(
            "MATCH (a:Account {id:$src}), (d:Device {id:'D1'}) "
            "CREATE (a)-[:USED_DEVICE {ts:$ts}]->(d)", {"src": src, "ts": ts})
    return {"nodes_added": 29, "edges_added": 36}
    # nodes: 9 persons + 9 accounts + 11 transactions
    # edges: OWNS 9 + SENT 11 + TO 11 + USED_DEVICE 5


def inject_scenario_b(g=None):
    """B — clean funnel (the pivot case): 8 distinct accounts, no device or
    identity overlap. Only money shape + timing — the device hypothesis must
    come back EMPTY during investigation."""
    g = g or get_graph()
    _new_person_account(g, "P-BT", "Target Wallet", False, "A-BT")
    names = ["Farida Sayed", "Govind Rao", "Hema Nair", "Imran Malik",
             "Jaya Iyer", "Kabir Saini", "Lata Dixit", "Manav Chopra"]
    for i, pname in enumerate(names, start=1):
        _new_person_account(g, f"P-B{i}", pname, True, f"A-B{i}")
    for i, (amount, hh, mm) in enumerate([
        (42000, 19, 12), (38500, 19, 26), (46500, 19, 51), (41500, 20, 7),
        (48200, 20, 22), (39600, 20, 41), (44800, 21, 3), (47300, 21, 28),
    ], start=1):
        _txn(g, f"TX-BT{i:03d}", f"A-B{i}", "A-BT", amount, f"2026-03-01T{hh:02d}:{mm:02d}")
    return {"nodes_added": 26, "edges_added": 25}
    # nodes: 9 persons + 9 accounts + 8 transactions
    # edges: OWNS 9 + SENT 8 + TO 8


def inject_scenario_c(g=None):
    """C — merchant fan-in (v2 false positive): 10 customers pay ONE KYC'd
    merchant account in one morning. The monitor honestly flags the fan-in;
    clearing happens DOWNSTREAM (analyst override → precedent)."""
    g = g or get_graph()
    for i in range(1, 11):
        _new_person_account(g, f"P-C{i:02d}", f"Meridian Customer {i:02d}", True,
                            f"A-C{i:02d}")
        _txn(g, f"TX-C{i:02d}", f"A-C{i:02d}", MERCHANT_ACCOUNT,
             44000 + i * 450, f"2026-03-15T09:{i:02d}")
    return {"nodes_added": 30, "edges_added": 30}
    # nodes: 10 persons + 10 accounts + 10 transactions
    # edges: OWNS 10 + SENT 10 + TO 10


if __name__ == "__main__":
    g = get_graph()
    noise_ticks(g, 10)
    print("scenario A →", inject_scenario_a(g))
    print("scenario B →", inject_scenario_b(g))
    print("scenario C →", inject_scenario_c(g))