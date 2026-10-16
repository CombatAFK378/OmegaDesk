"""OmegaDesk FastAPI service. API surface grows phase by phase (§17):
Phase 0 health · sim · monitor · C1 · C2 desk API + served UI at /. """
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api_cases import router as cases_router
from .config import GRAPH_NAME, LLM_MODEL
from .graph import get_graph
from .monitor import scan_once
from sim.api import router as sim_router

UI_DIR = Path(__file__).resolve().parent.parent / "ui"

app = FastAPI(title="OmegaDesk", version="0.2.0")
app.include_router(sim_router)
app.include_router(cases_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "omegadesk",
        "llm_model": LLM_MODEL,
        "graph_name": GRAPH_NAME,
    }


@app.get("/health/graph")
def health_graph():
    """Honest liveness: 503 if FalkorDB is unreachable."""
    try:
        get_graph().query("RETURN 1")
        return {"status": "ok", "graph": "up", "name": GRAPH_NAME}
    except Exception as exc:
        return JSONResponse({"status": "graph_down", "error": str(exc)}, status_code=503)


@app.post("/monitor/scan")
def monitor_scan():
    """Manual stream pass — every /sim tick and inject already auto-scans."""
    return scan_once()


@app.get("/monitor/alerts")
def monitor_alerts():
    rows = get_graph().query(
        "MATCH (a:Alert) RETURN a.id, a.type, a.target_id, a.created_at "
        "ORDER BY a.created_at DESC, a.id LIMIT 50"
    ).result_set
    return {"alerts": [{"id": r[0], "type": r[1], "target": r[2],
                        "created_at": r[3]} for r in rows]}  # v2: Alert has no status field


if UI_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(UI_DIR), html=True), name="ui")


@app.get("/", include_in_schema=False)
def root():
    if (UI_DIR / "index.html").exists():
        return JSONResponse({"desk_ui": "/app/index.html", "docs": "/docs",
                             "note": "the desk UI is mounted at /app"})
    return {"status": "ok", "docs": "/docs"}