"""Schema — architecture v2.1 §6 (single graph `desk`).

What changed from v1.3 (Rework Ledger R1):
- every transfer is a `Transaction` NODE: (Account)-[:SENT]->(Transaction)-[:TO]->(Account)
  — so evidence can point at the transfer itself (property graphs can't link edge→edge)
- freezes are `FreezeOrder` EVENTS; Account has NO status property (it is derived
  from FreezeOrder events, never mutated) — history replays exactly
- new desk nodes: `Decision` (with CITES/OVERRIDES precedent arrows) and `Signal`
  (the fixed pattern catalog); `Merchant` replaces Employer
- `HOLDS` renamed `OWNS`; `PAID_BY` replaced by `OPERATED_BY`
"""

NODE_LABELS = ["Person", "Account", "Device", "Merchant", "Transaction",
               "Alert", "Case", "Signal", "Decision", "FreezeOrder",
               "Analyst", "Regulation"]

EDGE_TYPES = ["SENT", "TO", "USED_DEVICE", "SAME_IDENTITY", "OWNS",
              "OPERATED_BY", "TRIGGERED_BY", "FOR_ALERT", "ABOUT",
              "EXHIBITS", "EVIDENCE", "FOR_CASE", "CITES", "OVERRIDES",
              "APPLIED_POLICY", "MADE_BY", "FREEZES", "ISSUED_BY", "ASSIGNED_TO"]

INDICES = [("Account", "id"), ("Person", "id"), ("Device", "id"),
           ("Merchant", "id"), ("Transaction", "id"), ("Alert", "id"),
           ("Case", "id"), ("Signal", "code"), ("Decision", "id"),
           ("FreezeOrder", "id"), ("Analyst", "name"), ("Regulation", "id")]


def reset_graph(g):
    g.query("MATCH (n) DETACH DELETE n")


def _create_index(g, label, prop):
    attempts = [
        f"CREATE INDEX FOR (n:{label}) ON (n.{prop})",
        f"CREATE INDEX ON :{label}({prop})",
    ]
    last_err = None
    for q in attempts:
        try:
            g.query(q)
            return
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if "already exists" in msg or "already indexed" in msg:
                return
            last_err = e
    raise last_err


def create_schema(g):
    reset_graph(g)
    for label, prop in INDICES:
        _create_index(g, label, prop)


def graph_counts(g):
    nodes = {label: g.query(f"MATCH (n:{label}) RETURN count(n)").result_set[0][0]
             for label in NODE_LABELS}
    edges = {et: g.query(f"MATCH ()-[r:{et}]->() RETURN count(r)").result_set[0][0]
             for et in EDGE_TYPES}
    return nodes, edges