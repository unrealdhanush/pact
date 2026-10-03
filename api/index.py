"""Vercel entrypoint: the whole FastAPI app (API + web UI) as one Python function."""
import ctypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Moss on Vercel: its Linux wheel is tagged glibc 2.35 but only uses <= 2.34 symbols (Vercel has
# 2.34); it does need GLIBCXX_3.4.30 (GCC 12), newer than the image's libstdc++. We ship the Linux
# Moss packages plus conda-forge's GCC 12 libstdc++ in vendor/linux and pre-load that libstdc++
# globally before anything imports Moss. If any of this fails, Pact falls back to labelled local memory.
_VENDOR = ROOT / "vendor" / "linux"
if sys.platform.startswith("linux") and _VENDOR.exists():
    try:
        ctypes.CDLL(str(_VENDOR / "lib" / "libstdc++.so.6"), mode=ctypes.RTLD_GLOBAL)
    except OSError as e:  # pragma: no cover - only on the serverless image
        print(f"pact: could not preload vendored libstdc++: {e}", file=sys.stderr)
    sys.path.append(str(_VENDOR))
    if os.environ.get("VERCEL"):  # only /tmp is writable; Moss caches its embedding model under HOME
        os.environ["HOME"] = "/tmp"
        os.environ.setdefault("XDG_CACHE_HOME", "/tmp/.cache")

from pact.server import app  # noqa: E402,F401
