"""C3 — "algorithms as tools" (§16 C3): graph structure the agent can call.

hub_centrality = betweenness on the money graph, ranked around a case's scope:
WHO is the funnel's heart (money from everywhere converges here / exits here).
Computed INSIDE FalkorDB with its built-in algo.betweenness over the money
model (Account + Transaction nodes, SENT/TO edges) — the graph measures itself;
the code only picks the accounts in the case's neighborhood.
"""
from ..graph import get_graph
from ..journal import journal
from .registry import register

BETWEENNESS_Q = """CALL algo.betweenness({nodeLabels: ['Account', 'Transaction'],
                                         relationshipTypes: ['SENT', 'TO']})
                   YIELD node, score
                   WITH node, score WHERE node:Account AND node.id IN $ids
                   RETURN node.id, score ORDER BY score DESC, node.id"""


@register("read",
          "HUB DETECTION: betweenness centrality on the money paths around this "
          "case's accounts — which single account is the funnel's heart "
          "(money converges into it / leaves it). Use to point at the operator.",
          {"case_id": "case id", "k": "optional: neighborhood expansion hops, ≤2"})
def hub_centrality(case_id, k=1):
    g = get_graph()
    k = max(1, min(int(k or 1), 2))
    scope = [r[0] for r in g.query(
        "MATCH (c:Case {id:$cid})-[:ABOUT]->(a:Account) RETURN a.id",
        {"cid": case_id}).result_set]
    if not scope:
        return {"found": False, "error": "case has no scope"}

    # neighborhood: the scope's accounts ± k transaction hops (bounded, deterministic)
    near = {r[0] for r in g.query(
        f"""MATCH (a:Account)-[:SENT|TO*1..{2 * k}]-(b:Account)
            WHERE a.id IN $scope RETURN DISTINCT b.id""",
        {"scope": scope}).result_set} | set(scope)
    ranked = g.query(BETWEENNESS_Q, {"ids": sorted(near)}).result_set
    if not ranked or len(near) < 2:
        return {"found": False, "error": "no money path around this case"}

    deg = {r[0]: (r[1], r[2]) for r in g.query(
        """MATCH (a:Account) WHERE a.id IN $ids
           OPTIONAL MATCH (s:Account)-[:SENT]->(:Transaction)-[:TO]->(a) WHERE s.id IN $ids
           WITH a, count(DISTINCT s) AS n_in
           OPTIONAL MATCH (a)-[:SENT]->(:Transaction)-[:TO]->(o:Account) WHERE o.id IN $ids
           RETURN a.id, n_in, count(DISTINCT o)""",
        {"ids": sorted(near)}).result_set}
    hub_id, hub_score = ranked[0]
    shape = "pass-through hub"
    if hub_score == 0:
        # nothing sits BETWEEN payers and payees (pure fan-in / fan-out): no money
        # flows through any node, so name the drain — the most inbound sources
        hub_id = max(sorted(deg), key=lambda a: (deg[a][0], -deg[a][1]))
        shape = "drain (no account passes money through)"
    n_in, n_out = deg.get(hub_id, (0, 0))
    journal("agent", "hub_centrality", case_id=case_id, hub=hub_id,
            score=round(hub_score, 4), algo="falkordb algo.betweenness")
    return {
        "found": True, "case_id": case_id, "algorithm": "algo.betweenness (FalkorDB)",
        "hub": hub_id, "shape": shape, "betweenness": round(hub_score, 4),
        "in_degree": n_in, "out_degree": n_out,
        "accounts_in_neighborhood": len(near),
        "plain": f"the money from this pattern funnels hardest through {hub_id} — "
                 f"{n_in} sources in, {n_out} moving out",
        "top5": [{"account": a, "betweenness": round(s, 4),
                  "in": deg.get(a, (0, 0))[0], "out": deg.get(a, (0, 0))[1]}
                 for a, s in ranked[:5]],
    }
