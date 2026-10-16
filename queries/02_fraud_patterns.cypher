// 02 — the fraud shapes (§7), one query each.
// FAN_IN: many-to-one accumulation into one account (alerts fire at >=5 senders/3h)
MATCH (s:Account)-[:SENT]->(t1:Transaction)-[:TO]->(a:Account)
WITH a, count(DISTINCT s) AS senders, sum(t1.amount) AS total
WHERE senders >= 5
RETURN a.id, senders, total ORDER BY senders DESC;

// SUB_THRESHOLD: same pair dripping inside 90-99% of the reporting line (50k)
MATCH (s:Account)-[:SENT]->(t:Transaction)-[:TO]->(a:Account)
WHERE t.amount >= 45000 AND t.amount <= 49500
RETURN s.id, a.id, collect(t.id) AS drips, count(*) AS repeats
ORDER BY repeats DESC;

// PASS_THROUGH: inflow forwarded onward the same day
MATCH (x:Transaction)-[:TO]->(mid:Account)-[:SENT]->(y:Transaction)-[:TO]->(out:Account)
RETURN mid.id, sum(x.amount) AS inflow, sum(y.amount) AS outflow;

// SHARED DEVICE RING: accounts clustered by one fingerprint
MATCH (a:Account)-[:USED_DEVICE]->(d:Device)<-[:USED_DEVICE]-(b:Account)
WHERE a.id < b.id
RETURN d.fingerprint, collect(a.id + ' + ' + b.id) AS pairs;