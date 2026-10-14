# OmegaDesk — central config. Everything from .env; no config logic here.
# Model swap (architecture §10) = edit the LLM_* lines in .env only, zero code change.
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# --- Active LLM (OpenAI-compatible endpoint) ---
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-oss-120b")

# --- Graph (single source of truth, architecture §4) ---
GRAPH_HOST = os.getenv("FALKORDB_HOST", "localhost")
GRAPH_PORT = int(os.getenv("FALKORDB_PORT", "6379"))
GRAPH_NAME = os.getenv("GRAPH_NAME", "desk")