"""Shared FalkorDB connection — the ONLY way any component touches data.

The graph is the evidence room (architecture §2.1): simulator, monitor,
agents and UI all read/write through this client. One connection, cached.
"""
from functools import lru_cache

from falkordb import FalkorDB

from .config import GRAPH_HOST, GRAPH_NAME, GRAPH_PORT


@lru_cache(maxsize=1)
def get_db() -> FalkorDB:
    return FalkorDB(host=GRAPH_HOST, port=GRAPH_PORT)


@lru_cache(maxsize=1)
def get_graph():
    """Graph handle for the single 'desk' graph (architecture §4)."""
    return get_db().select_graph(GRAPH_NAME)