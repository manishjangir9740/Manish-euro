import os
import sys
import tempfile
import threading
from pathlib import Path
from http.server import HTTPServer

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# Ensure state dir is in writable /tmp for serverless environment
if "ELUNO_STATE_DIR" not in os.environ:
    os.environ["ELUNO_STATE_DIR"] = os.path.join(tempfile.gettempdir(), "eluno-state")
os.makedirs(os.environ["ELUNO_STATE_DIR"], exist_ok=True)

# Start bundled mock server on port 8787 in background thread if not already running
MOCK_PORT = 8787
os.environ.setdefault("ELUNO_MOCK_SERVER_URL", f"http://127.0.0.1:{MOCK_PORT}")

_mock_started = False
_mock_lock = threading.Lock()

def _start_mock():
    try:
        import importlib.util
        mock_path = BASE / "starter-kit" / "mock-apis" / "mock_server.py"
        spec = importlib.util.spec_from_file_location("mock_server", str(mock_path))
        if spec and spec.loader:
            mock_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mock_mod)
            mock_mod.FLAKE = False
            server = HTTPServer(("127.0.0.1", MOCK_PORT), mock_mod.H)
            server.serve_forever()
    except Exception as e:
        print(f"Mock server background thread failed: {e}", file=sys.stderr)

def _ensure_mock():
    global _mock_started
    if not _mock_started:
        with _mock_lock:
            if not _mock_started:
                t = threading.Thread(target=_start_mock, daemon=True)
                t.start()
                _mock_started = True

_ensure_mock()

from pos.web import WebHandler

class handler(WebHandler):
    pass
