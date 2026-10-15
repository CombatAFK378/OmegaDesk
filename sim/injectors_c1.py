"""C1 — benchmark scenario injectors (v2.1 §11): C′, D, E as runnable injections.

- C′  "similar merchant later": fresh customers → the SAME KYC merchant account
  → same shape as C; must cite HOV-003 (the analyst's clearance) and escalate.
- D   "look-alike without KYC": same fan-in shape into a NON-KYC merchant →
  must DISTINGUISH the clearance precedent and decide on evidence alone.
- E   "overruled trap": fresh account pass-through, shaped exactly like the
  case whose decision was later overruled (HD-019 → HOV-002); the overruled
  decision must never be cited.
All deterministic: fixed ids + timestamps.
"""
from app.graph import get_graph
from .generator import _new_person_account, _txn


def inject_scenario_c_prime(g=None):
    """C′ — same shape as C: 10 fresh customers pay the same KYC'd merchant."""
    g = g or get_graph()
    for i in range(1, 11):
        _new_person_account(g, f"P-CP{i:02d}", f"Meridian Cust {i:02d}", True, f"A-CP{i:02d}")
        _txn(g, f"TX-CP{i:02d}", f"A-CP{i:02d}", "A-MER-PAY",
             44100 + i * 100, f"2026-03-20T10:{i:02d}")
    return {"target": "A-MER-PAY"}


def inject_scenario_d(g=None):
    """D — look-alike WITHOUT KYC: a dark merchant + 10 payers. Same fan-in
    shape as C, but BUSINESS_KYC is absent."""
    g = g or get_graph()
    g.query("CREATE (:Merchant {id:'M-DARK', business_kyc:false, registered_cadence:'none'})")
    g.query("""MATCH (m:Merchant {id:'M-DARK'})
               CREATE (:Account {id:'A-DARK-MER', opened_at:'2026-03-01', type:'merchant'})
                      -[:OPERATED_BY {ts:'2026-03-01'}]->(m)""")
    for i in range(1, 11):
        _new_person_account(g, f"P-CD{i:02d}", f"Dark Cust {i:02d}", False, f"A-CD{i:02d}")
        _txn(g, f"TX-CD{i:02d}", f"A-CD{i:02d}", "A-DARK-MER",
             44100 + i * 100, f"2026-03-25T11:{i:02d}")
    return {"target": "A-DARK-MER"}


def inject_scenario_e(g=None):
    """E — the trap: fresh account receives 2 × ₹49k and forwards 96% within a
    day. Signals = PASS_THROUGH + NEW_ACCOUNT — exactly H-C019's bundle; its
    decision (HD-019) was corrected by HOV-002, so it must never be cited."""
    g = g or get_graph()
    _new_person_account(g, "P-E1", "Fresh Proxy", False, "A-E1", since="2026-03-19")
    _new_person_account(g, "P-E2", "Steady Sender", True, "A-E2", since="2025-01-15")
    _new_person_account(g, "P-E3", "Quiet Receiver", True, "A-E3", since="2025-01-15")
    _txn(g, "TX-E1", "A-E2", "A-E1", 49000, "2026-03-19T10:00")
    _txn(g, "TX-E2", "A-E2", "A-E1", 49000, "2026-03-19T10:10")
    _txn(g, "TX-E3", "A-E1", "A-E3", 95000, "2026-03-19T23:00")
    return {"target": "A-E1"}