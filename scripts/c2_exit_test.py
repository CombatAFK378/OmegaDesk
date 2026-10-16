"""C2 exit tests (v2.1 §16): "a fresh clone runs end to end from the README alone."

Checks the desk API + served UI against a REAL uvicorn process (subprocess),
so the test exercises the exact thing the demo uses. NO LLM spend here —
the investigate endpoint is shape-checked only (404/400 paths).

Run: .venv/bin/python scripts/c2_exit_test.py
"""
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORT = 8199
BASE = f"http://127.0.0.1:{PORT}"
FAILURES = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:   # 4xx/5xx are DATA for the checks, not crashes
        body = e.read() or b"{}"
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"detail": body.decode(errors="replace")[:200]}


def raw(path):
    """Static assets: read as text, no JSON parsing."""
    return urllib.request.urlopen(BASE + path, timeout=30).read().decode()


def post(path, payload, expect_error=False):
    req = urllib.request.Request(BASE + path,
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main():
    from seed.seed import seed_graph   # §16: every exit test starts from the seed reset
    counts = seed_graph()
    print(f"seed reset → {sum(counts[0].values())} nodes / {sum(counts[1].values())} edges")
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "bin" / "uvicorn"), "app.main:app", "--port", str(PORT),
         "--log-level", "warning"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        # wait for boot
        up = False
        for _ in range(60):
            try:
                get("/health")
                up = True
                break
            except Exception:
                time.sleep(0.5)
        check("uvicorn boots from the repo", up)
        if not up:
            return

        # health + UI
        s, h = get("/health")
        check("GET /health ok", s == 200 and h["service"] == "omegadesk")
        s, hg = get("/health/graph")
        check("GET /health/graph ok (FalkorDB up)", s == 200 and hg["status"] == "ok",
              f"got {hg}")
        with urllib.request.urlopen(BASE + "/app/", timeout=30) as r:
            html = r.read().decode()
            check("UI served at /app/ (dark desk html)",
                  "OmegaDesk" in html and "style.css" in html)
        css = raw("/app/style.css")
        check("UI stylesheet has the dark tokens", "--bg: #0b0f14" in css)
        js = raw("/app/app.js")
        check("UI script served (no build step)", "investigate" in js and "override" in js)

        # alerts + cases (the world from the seed)
        s, alerts = get("/monitor/alerts")
        check("GET /monitor/alerts lists seeded alerts", s == 200 and len(alerts["alerts"]) >= 25)
        s, cases = get("/cases")
        check("GET /cases lists the seeded old case", s == 200 and
              any(c["case_id"] == "C-2025-0417" for c in cases["cases"]), f"got {len(cases['cases'])} cases")
        old = next(c for c in cases["cases"] if c["case_id"] == "C-2025-0417")
        s, detail = get(f"/cases/C-2025-0417")
        has_decision = any(d["decision_id"] == "D-2025-0417" for d in detail["decisions"])
        check("GET /cases/{id} returns decisions for the old case", s == 200 and has_decision,
              f"got {[(d['decision_id']) for d in detail['decisions']]}")
        check("the old case carries a freeze order + policy lineage",
              any("D-2025-0417" == f["issued_by"] for f in detail["freeze_orders"]) and
              any(d["decision_id"] == "D-2025-0417" for d in detail["decisions"]))
        check("old case evidence replays are recorded", len(detail["evidence"]) >= 1)

        # benchmark report served (C1 wrote it)
        s, bench = get("/benchmark/last")
        check("GET /benchmark/last serves the §12 report",
              s == 200 and "decisions_changed" in bench and len(bench["cases"]) >= 5)

        # the investigate endpoint's guard rails (NO LLM call here)
        s, r = post("/cases/investigate", {"alert_id": "MISSING"})
        check("POST investigate: unknown alert → 404", s == 404)
        s, r = post("/cases/investigate", {})
        check("POST investigate: empty body → 400", s == 400)

        # the override endpoint's guard rails (deterministic, graph-backed)
        s, r = post("/cases/C-2025-0417/override",
                    {"analyst_id": "AN-DEV", "action": "clear", "reason": ""})
        check("POST override: empty reason → 400 (§10)", s == 400)
        s, r = post("/cases/C-2025-0417/override",
                    {"analyst_id": "AN-DEV", "action": "detonate", "reason": "x"})
        check("POST override: bad action → 400", s == 400)
        s, r = post("/cases/NOPE/override",
                    {"analyst_id": "AN-DEV", "action": "clear", "reason": "x"})
        check("POST override: unknown case → 400", s == 400)

        # README consistency (fresh-clone contract)
        readme = (ROOT / "README.md").read_text()
        have = [p.name for p in (ROOT).glob("*") if p.is_file()] + \
               ["docs/demo_script.md", "queries/01_graph_overview.cypher"]
        for token in ["requirements.txt", "queries/", "c1_exit_test.py", "c2_exit_test.py",
                      ".env.example", "docker compose up -d", "python -m seed.seed",
                      "uvicorn app.main:app", "disclosure"]:
            check(f"README covers {token!r}", token in readme)
        check("README's commands match the repo files",
              (ROOT / "requirements.txt").exists() and (ROOT / ".env.example").exists()
              and (ROOT / "docker-compose.yml").exists())
        check("requirements.txt parses + covers the app imports",
              all(pkg.split(">")[0].split("[")[0] in ("fastapi", "uvicorn", "falkordb",
                                                      "openai", "python-dotenv", "redis")
                  for line in (ROOT / "requirements.txt").read_text().splitlines()
                  if line and not line.startswith("#")
                  for pkg in [line]))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("---")
    if FAILURES:
        print(f"C2 EXIT TEST: {len(FAILURES)} failure(s): {FAILURES}")
        sys.exit(1)
    print("C2 EXIT TEST: ALL GREEN")


if __name__ == "__main__":
    main()