// 04 — evidence replay (§6 rule: every claim is a replayable query)
// The evidence chain of one case:
MATCH (c:Case)-[ev:EVIDENCE]->(n)
RETURN c.id, ev.query_id, ev.tool, ev.snapshot, n.id, ev.as_of
ORDER BY c.created_at DESC, ev.query_id LIMIT 20;

// Token/cost trail is in journal.jsonl (actor 'investigator' → 'llm_run').

// Who is frozen right now, and by which decision (status derived from events, §6):
MATCH (fo:FreezeOrder)-[:FREEZES]->(a:Account)
RETURN a.id, fo.id, fo.ts ORDER BY fo.ts DESC;