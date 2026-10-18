// 05 — hub centrality (app/tools/graph_algos.py): FalkorDB's built-in betweenness
// over the money model. Transactions are nodes, so a path is
// Account -SENT-> Transaction -TO-> Account; a high score = money flows THROUGH it.
CALL algo.betweenness({nodeLabels: ['Account', 'Transaction'],
                       relationshipTypes: ['SENT', 'TO']})
YIELD node, score
WITH node, score WHERE node:Account
RETURN node.id, score ORDER BY score DESC, node.id LIMIT 10;
