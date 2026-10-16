// 03 — the desk's MEMORY (what C1 reads): decisions, citations, corrections.
// Every historical decision on cases that share this case's signals:
MATCH (c:Case)-[:EXHIBITS]->(s:Signal)<-[:EXHIBITS]-(pc:Case)-[:FOR_CASE]-(d:Decision)
WHERE c.status = 'open'
RETURN c.id, d.id, d.action, collect(DISTINCT s.code) AS shared;

// The override chain — what an analyst corrected, and why:
MATCH (ov:Decision)-[o:OVERRIDES]->(old:Decision)-[:FOR_CASE]->(c:Case)
RETURN ov.id, o.reason, old.id, c.id ORDER BY ov.ts;

// The freeze provenance path (why is THIS account frozen?):
MATCH p=(fo:FreezeOrder)-[:FREEZES]->(a:Account)-[:ISSUED_BY]->(d:Decision)-[:APPLIED_POLICY]->(r:Regulation)
RETURN p;

// A decision and the precedents it cited (applies vs distinguished):
MATCH (d:Decision)-[c:CITES]->(pd:Decision)
RETURN d.id, pd.id, c.applies, c.distinguishing;