#!/usr/bin/env python3
"""One-command launcher for the till UI (also the hosting entry point).

    python app.py                 # http://127.0.0.1:8080, starts the bundled mock if nothing is listening
    python app.py --flaky         # the mock injects 429s / terminal 503s (default for a real demo is calm)

Hosting (Render etc.): binds 0.0.0.0:$PORT. The mock is in memory, so state lives in a fresh temp dir
per start unless ELUNO_STATE_DIR is set; keeping them together avoids invoice numbers that continue
from an old run. Set ELUNO_UI_PASSWORD to put the whole UI behind a password.
"""

import argparse
import atexit
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--mock-port", type=int, default=8787)
    ap.add_argument("--flaky", action="store_true", default=os.environ.get("ELUNO_FLAKY") == "1")
    args = ap.parse_args()

    if os.environ.get("ELUNO_USE_SHOPIFY") != "1":  # the demo runs against the mock, whatever the shell has set
        for k in ("SHOPIFY_SHOP", "SHOPIFY_ACCESS_TOKEN", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET"):
            os.environ.pop(k, None)
    if "PORT" in os.environ and "HOST" not in os.environ:
        args.host = "0.0.0.0"  # a platform told us the port: it also needs us reachable
    os.environ.setdefault("ELUNO_MOCK_SERVER_URL", f"http://127.0.0.1:{args.mock_port}")
    if "ELUNO_STATE_DIR" not in os.environ:
        os.environ["ELUNO_STATE_DIR"] = tempfile.mkdtemp(prefix="eluno-state-")

    mock_url = os.environ["ELUNO_MOCK_SERVER_URL"]

    def up() -> bool:
        try:
            urllib.request.urlopen(f"{mock_url}/health", timeout=2).read()
            return True
        except Exception:
            return False

    if not up():
        cmd = [sys.executable, str(BASE / "starter-kit" / "mock-apis" / "mock_server.py"), "--port", str(args.mock_port)]
        if not args.flaky:
            cmd.append("--no-flake")
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        atexit.register(proc.terminate)
        for _ in range(60):
            if up():
                break
            time.sleep(0.1)
        else:
            sys.exit("Could not start the bundled mock server.")
        print(f"[mock] started ({'flaky' if args.flaky else 'calm'}) at {mock_url}")
    else:
        print(f"[mock] using the server already running at {mock_url}")

    from pos.web import run_web
    run_web(args.port, args.host)


if __name__ == "__main__":
    main()
