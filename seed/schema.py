"""Phase 1 — graph schema (architecture §4): labels, indices, reset.

Node labels and edge types live here so every phase creates the same shapes.
The single graph is named `desk` (app/config.py).
"""

# §4 node labels — exactly these eight, nothing else
NODE_LABELS = ["Person", "Account", "Device", "Employer", "Alert", "Case", "Regulation", "Analyst"]

# §4 edges — the only relationship types the product uses
EDGE_TYPES = [
    "SENT", "USED_DEVICE", "SAME_IDENTITY", "PAID_BY", "TRIGGERED",
    "INVESTIGATED", "EVIDENCE", "RESOLVED_AS", "FROZEN_BY", "CITED_BY",
    "ASSIGNED_TO", "HOLDS",  # HOLDS: Person→Account ownership — §4 gap, flagged (see phase report)
]

# Lookup properties worth an index (every tool lookup key §6 relies on)
INDICES = [
    ("Account", "id"), ("Person", "name"), ("Device", "id"),
    ("Employer", "id"), ("Alert", "id"), ("Case", "id"),
    ("Regulation", "id"), ("Analyst", "name"),
]


def reset_graph(g):
    """Wipe all data — `down/up` persistence keeps the volume; reset rebuilds content."""
    g.query("MATCH (n) DETACH DELETE n")


def _create_index(g, label, prop):
    """FalkorDB first, legacy RedisGraph syntax as fallback; tolerate re-runs."""
    attempts = [
        f"CREATE INDEX FOR (n:{label}) ON (n.{prop})",
        f"CREATE INDEX ON :{label}({prop})",
    ]
    last_err = None
    for q in attempts:
        try:
            g.query(q)
            return
        except Exception as e:  # noqa: BLE001 — redis client raises bare ResponseError
            msg = str(e).lower()
            if "already exists" in msg or "already indexed" in msg:
                return
            last_err = e
    raise last_err


def create_schema(g):
    reset_graph(g)
    for label, prop in INDICES:
        _create_index(g, label, prop)