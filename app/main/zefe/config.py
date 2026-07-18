import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
SESSION_SECRET = os.environ.get(
    "SESSION_SECRET",
    "zefe-dev-secret-key-change-in-production-please",
)
SESSION_COOKIE = "zefe_session"
SESSION_MAX_AGE = 60 * 60 * 8
PORT = int(os.environ.get("PORT", 5000))
HOST = os.environ.get("HOST", "0.0.0.0")
RELOAD = os.environ.get("RELOAD", "1") == "1"