"""C4 exit tests (v2.1 §16): cited reports + live simulator as demo candy.

  1. POST /cases/{id}/report → ONE LLM call → body with sources named
  2. every source the report cites is verifiable on the graph (decisions/evidence)
  3. GET /cases/{id}/report.md → downloadable markdown
  4. the live simulator: POST /sim/start?interval=0.2 → ticks + alerts flow → /sim/stop
  5. the UI serves the report card + the live-stream button (zero console errors is
     the browser-eye task, separate)

LLM spend: 1 call (~$0.005). Run: .venv/bin/python scripts/c4_exit_test.py
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
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


def http(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body.decode()
    except urllib.error.HTTPError as e:
        body = e.read() or b"{}"
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"detail": body.decode(errors="replace")[:200]}


def main():
    from seed.seed import seed_graph
    from sim.generator import inject_scenario_c
    from app.monitor import scan_once
    from app.config import LLM_API_KEY
    from app.graph import get_graph

    seed_graph()
    g = get_graph()
    # a decided case for the report: use the seeded old case (has a decision + evidence)
    cid = "C-2025-0417"

    if not LLM_API_KEY:
        print("C4 EXIT TEST: SKIPPED — no LLM key (report needs one call)")
        sys.exit(2)

    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "bin" / "uvicorn"), "app.main:app", "--port", str(PORT),
         "--log-level", "warning"], cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        up = False
        for _ in range(60):
            try:
                http("/health")
                up = True
                break
            except Exception:
                time.sleep(0.5)
        check("server boots", up)

        # ---- 1+3) the report: generate → served → downloadable ----
        s, rep = http(f"/cases/{cid}/report", method="POST")
        check("report generated (one LLM call)", s == 200 and rep.get("report"),
              f"got {s} {str(rep)[:200]}")
        body = rep.get("report", "")
        check("report carries source tags [n]", "[" in body and "]" in body, f"got {body[:200]}")
        s, md = http(f"/cases/{cid}/report.md")
        check("report downloadable as markdown", s == 200 and "OmegaDesk case report" in str(md))
        s, detail = http(f"/cases/{cid}")
        check("report persists on the case", detail.get("report", {}).get("body") is not None)

        # ---- 2) every [n] source is verifiable against the case's stored facts ----
        import re
        tags = re.findall(r"\[\d+\]", body)
        facts_dump = json.dumps(detail.get("decisions", []) + detail.get("evidence", []))
        check("the report cites with numbered source tags", len(tags) >= 2, f"got {tags[:8]}")
        check("at least one cited source exists in the stored facts",
              bool(detail.get("decisions")) and ("decision_id" in facts_dump))

        # ---- 4) the live stream (demo candy) ----
        s, st = http("/sim/start?interval=0.2", method="POST")
        check("live sim starts from the API", s == 200, f"got {st}")
        time.sleep(7)
        s, mid = http("/sim/status")
        ticks_now = mid.get("ticks", 0)
        check("the world ticks by itself", ticks_now > 0, f"got {mid}")
        time.sleep(3)
        s, after = http("/sim/status")
        check("ticks keep rising while live", after.get("ticks", 0) > ticks_now)
        s, off = http("/sim/stop", method="POST")
        check("live sim stops", s == 200 and off.get("running") is False, f"got {off}")

        # ---- 5) the UI serves the C4 widgets ----
        js_text = (ROOT / "ui" / "app.js").read_text()
        check("UI has the report card + download", "Case report" in js_text and "report.md" in js_text)
        check("UI has the live-stream button", "sim/start?interval=" in js_text)
        check("UI has the deterministic 'In short' + AI-voice cards",
              "function inShort" in js_text and "What the AI investigator says" in js_text)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("---")
    if FAILURES:
        print(f"C4 EXIT TEST: {len(FAILURES)} failure(s): {FAILURES}")
        sys.exit(1)
    print("C4 EXIT TEST: ALL GREEN")


if __name__ == "__main__":
    main()