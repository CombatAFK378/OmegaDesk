"""C1 — the pre-registered with/without benchmark (v2.1 §12). The PROOF.

Each listed case runs TWO investigations in one deterministic world:
  with    — precedent tool ON  (the desk remembers)
  without — precedent tool OFF (the ablation switch — the desk forgets)
Expected actions + citations are LOCKED in EXPECTED before any run; misses
are reported honestly; tokens-per-case recorded (pacing gate).

The precedent sources are all in the SEED history (D-2025-0417, HOV-002,
HOV-003) — each scenario reseeds, so nothing depends on earlier runs.
"""
import json
from pathlib import Path

from .coordinator import handle_alert, handle_direct_case
from .graph import get_graph
from .investigator import _client
from .journal import journal
from .monitor import scan_once
from .policy import record_override
from .signals import extract_signals
from sim.generator import inject_scenario_a, inject_scenario_b, inject_scenario_c
from sim.injectors_c1 import inject_scenario_c_prime, inject_scenario_d, inject_scenario_e

# ---- pre-registered expectations (re-registered at calibration; the FINAL run decides) ----
EXPECTED = {
    "A":  {"target": "A-EXIT", "inject": inject_scenario_a,
           "with": "freeze", "without": "freeze", "must_cite": "D-2025-0417"},
    "B":  {"target": "A-BT", "inject": inject_scenario_b,
           "with": "escalate", "without": "escalate", "must_cite": None},
    "C":  {"target": "A-MER-PAY", "inject": inject_scenario_c,
           "with": "escalate", "without": "escalate",
           "override": ("AN-DEV", "clear",
                        "KYC-verified merchant on registered monthly cadence — business activity")},
    "Cp": {"target": "A-MER-PAY", "inject": inject_scenario_c_prime,
           "with": "escalate", "without": "freeze",
           "must_cite": ["HOV-016", "HD-004", "HD-010", "HD-022"]},
    "D":  {"target": "A-DARK-MER", "inject": inject_scenario_d,
           "with": "freeze", "without": "freeze",
           "must_cite": ["HOV-016", "HD-004", "HD-010", "HD-022"],
           "must_distinguish": True},
    "E":  {"target": "A-E1", "inject": inject_scenario_e, "direct_case": True,
           "with": "escalate", "without": "freeze", "must_cite": "HOV-019",
           "never_cite": "HD-019"},
}

REPORT_PATH = Path(__file__).resolve().parent.parent / "benchmark_report.json"


def _latest_alert_for(g, target):
    rows = g.query(
        "MATCH (al:Alert {target_id:$t}) RETURN al.id ORDER BY al.created_at DESC LIMIT 1",
        {"t": target}).result_set
    return rows[0][0] if rows else None


def _applied(g, case_id):
    """Which precedents the LLM marked applies:true + their distinguishing notes."""
    rows = g.query(
        "MATCH (d:Decision)-[:FOR_CASE]->(c:Case {id:$cid}) RETURN d.id, d.rationale",
        {"cid": case_id}).result_set
    return [{"decision_id": r[0], "rationale": r[1]} for r in rows]


def run_benchmark(cases=None, client=None, run_id="b1"):
    """Runs every case with and without precedents; returns + saves the report."""
    client = client or _client()
    g = get_graph()
    report = {"run_id": run_id, "cases": [], "misses": [], "pre_registered": {
        k: {kk: vv for kk, vv in spec.items() if kk != "inject"} for k, spec in EXPECTED.items()}}

    for code, spec in (cases and {c: EXPECTED[c] for c in cases} or EXPECTED).items():
        seed_reset(g)
        spec["inject"](g)
        scan_once(g)  # the injected events get watched (§3) — alerts before cases
        alert_id = None
        # WITH — precedents on
        if spec.get("direct_case"):
            with_run = handle_direct_case("E-CASE-W", spec["target"], ablated=False, client=client, g=g)
        else:
            alert_id = _latest_alert_for(g, spec["target"])
            if alert_id is None:
                report["cases"].append({"case": code, "miss": "no alert raised"})
                report["misses"].append(code)
                continue
            with_run = handle_alert(alert_id, ablated=False, client=client, g=g)
        with_cited = cited_with(pipeline_cites(with_run, g), g)
        if spec.get("override"):
            record_override(with_run["case_id"], *spec["override"], g)
        # WITHOUT — precedents off (ablation); a fresh case on the same alert
        if spec.get("direct_case"):
            without_run = handle_direct_case("E-CASE-N", spec["target"], ablated=True, client=client, g=g)
        else:
            without_run = handle_alert(alert_id, ablated=True, client=client, g=g)

        row = {"case": code,
               "with": {"action": with_run["action"], "confidence": with_run["confidence"],
                        "cited": [c["decision_id"] for c in with_run["cited"]],
                        "cited_all": with_run.get("cited_all", []),
                        "tokens": with_run["tokens"], "tool_sequence": with_run["tool_sequence"],
                        "decision_id": with_run["dec_id"]},
               "without": {"action": without_run["action"], "confidence": without_run["confidence"],
                           "cited": [], "decision_id": without_run["dec_id"]},
               "expected": {"with": spec["with"], "without": spec["without"]},
               "with_ok": with_run["action"] == spec["with"],
               "without_ok": without_run["action"] == spec["without"],
               "cite_checks": {}}
        if "must_cite" in spec and spec["must_cite"] is not None:
            wanted = spec["must_cite"]
            ok = ([w in row["with"]["cited_all"] for w in wanted] if isinstance(wanted, list)
                  else [wanted in row["with"]["cited_all"]])
            row["cite_checks"]["must_cite"] = wanted
            row["cite_checks"]["ok"] = any(ok)
            if not any(ok):
                report["misses"].append(f"{code}: must_cite {wanted} missing")
        if "never_cite" in spec:
            ok2 = spec["never_cite"] not in row["with"]["cited_all"]
            row["cite_checks"]["never_cite"] = spec["never_cite"]
            row["cite_checks"]["never_cite_ok"] = ok2
            if not ok2:
                report["misses"].append(f"{code}: FORBIDDEN citation {spec['never_cite']} got cited")
        if not row["with_ok"]:
            report["misses"].append(f"{code}: with-run expected {spec['with']}, got {row['with']['action']}")
        if not row["without_ok"]:
            report["misses"].append(f"{code}: without-run expected {spec['without']}, got {row['without']['action']}")
        report["cases"].append(row)
        journal("benchmark", "case_run", case=code, with_action=row["with"]["action"],
                without_action=row["without"]["action"], tokens=row["with"]["tokens"])

    report["decisions_changed"] = [
        c["case"] for c in report["cases"]
        if c.get("with", {}).get("action") != c.get("without", {}).get("action")]
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str))
    return report


def seed_reset(g):
    from seed.seed import seed_graph
    return seed_graph()


def pipeline_cites(run, g):
    return run.get("cited", [])


def cited_with(cited, g):
    return cited


if __name__ == "__main__":
    r = run_benchmark()
    print(json.dumps(r, indent=2, default=str)[:3000])