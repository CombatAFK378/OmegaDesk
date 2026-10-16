"""C3 — "algorithms as tools" (§16 C3): graph structure the agent can call.

hub_centrality = betweenness on the money subgraph around a case's scope: WHO
is the funnel's heart (money from everywhere converges here / exits here).
Implemented with networkx on a small neighborhood — cheap, deterministic,
replayable (the graph answers, the code measures).
"""
import networkx as nx

from ..graph import get_graph
from ..journal import journal
from .registry import register


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
    rows = g.query(
        f"""MATCH p = (a:Account)-[:SENT|TO*1..{2 * k}]-(b:Account)
            WHERE a.id IN $scope
            RETURN [n IN nodes(p) | n.id],
                   [r IN relationships(p) | type(r)]""",
        {"scope": scope}).result_set
    G = nx.DiGraph()
    for ids, rels in rows:
        prev = None
        for i, nid in enumerate(ids):
            if prev is not None and i - 1 < len(rels):
                rel = rels[i - 1]
                if rel == "SENT":
                    G.add_edge(prev, nid)
                else:
                    G.add_edge(nid, prev)
            prev = nid
    if not G.nodes:
        return {"found": False, "error": "no money path around this case"}

    bc = nx.betweenness_centrality(G, normalized=True)
    in_deg = dict(G.in_degree())
    out_deg = dict(G.out_degree())
    ranked = sorted(bc.items(), key=lambda kv: (-kv[1], kv[0]))
    hub_id = ranked[0][0]
    journal("agent", "hub_centrality", case_id=case_id, hub=hub_id,
            score=round(ranked[0][1], 4))
    return {
        "found": True, "case_id": case_id,
        "hub": hub_id, "betweenness": round(ranked[0][1], 4),
        "in_degree": in_deg.get(hub_id, 0), "out_degree": out_deg.get(hub_id, 0),
        "accounts_in_neighborhood": len(G.nodes),
        "plain": f"the money from this pattern funnels hardest through {hub_id} — "
                 f"{in_deg.get(hub_id, 0)} sources in, {out_deg.get(hub_id, 0)} moving out",
        "top5": [{"account": a, "betweenness": round(s, 4),
                  "in": in_deg.get(a, 0), "out": out_deg.get(a, 0)}
                 for a, s in ranked[:5]],
    }