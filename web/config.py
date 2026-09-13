from __future__ import annotations

import os
from pathlib import Path

from src.config import CATALOG_PATH

DB_PATH = Path("data/media_transcribe.db")
HOST = "0.0.0.0"
PORT = 8420
CORS_ORIGINS = ["http://localhost:5173", "http://localhost:8420"]

AGENT_HOST = os.getenv("AGENT_HOST", "100.66.194.100")
AGENT_PORT = int(os.getenv("AGENT_PORT", "8421"))
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")

CATALOG_JSON_PATH = CATALOG_PATH
