"""OmegaDesk FastAPI service. Phase 0: health endpoints only — API surface
grows phase by phase (§17)."""
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import GRAPH_NAME, LLM_MODEL
from .graph import get_graph

app = FastAPI(title="OmegaDesk", version="0.1.0")


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