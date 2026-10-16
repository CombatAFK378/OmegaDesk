"""C3 — analyst routing (§16 C3, "cheap, deterministic"):

escalated/frozen cases land on a named analyst's queue by RULE, not by chance:
  device-ring / identity cases → AN-PRIYA (device specialist)
  merchant / cadence cases     → AN-DEV (payments desk)
  everything else              → alternate by case number
Written as Case-[:ASSIGNED_TO]->(Analyst) + journaled. The UI shows the queue.
"""
from .graph import get_graph
from .journal import journal

RING_SIGNALS = {"SHARED_DEVICE", "SHARED_IDENTITY", "RING_MEMBER"}
MERCHANT_SIGNALS = {"BUSINESS_KYC", "REGULAR_CADENCE"}


def route_case(case_id, fired_signals, g=None):
    g = g or get_graph()
    codes = {s["code"] for s in (fired_signals or [])}
    if codes & RING_SIGNALS:
        analyst, why = "AN-PRIYA", "device-ring desk — pattern involves shared devices or identity"
    elif codes & MERCHANT_SIGNALS:
        analyst, why = "AN-DEV", "payments desk — the receiver is a registered business"
    else:
        seq = int(case_id.split("-")[-1]) if case_id.split("-")[-1].isdigit() else 0
        analyst, why = ("AN-PRIYA", "default queue (round-robin)") if seq % 2 else \
                       ("AN-DEV", "default queue (round-robin)")
    g.query(
        """MATCH (c:Case {id:$cid}), (an:Analyst {id:$aid})
           CREATE (c)-[:ASSIGNED_TO {ts:'2026-01-01', reason:$why}]->(an)""",
        {"cid": case_id, "aid": analyst, "why": why})
    journal("policy", "routed", case_id=case_id, to=analyst, basis=why)
    return {"analyst": analyst, "desk": why}