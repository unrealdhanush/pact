"""Vercel entrypoint: the whole FastAPI app (API + web UI) as one Python function."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pact.server import app  # noqa: E402,F401
