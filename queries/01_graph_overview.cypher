// 01 — the whole desk, human-readable
// Run in FalkorDB Browser (:3000, host: desk) — or READONLY in Swagger-free REPL.
MATCH (n)
OPTIONAL MATCH (n)-[r]->(m)
RETURN count(DISTINCT n) AS nodes, count(DISTINCT r) AS edges;