"""Run the sibling backend with disposable demo data for browser tests."""

import signal
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "backend"))
from mrp_app.runtime import DemoRuntime
from mrp_app.server import make_server
from mrp_app.service import Application


def stop_server(_signum, _frame):
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, stop_server)

with tempfile.TemporaryDirectory(prefix="mrp-e2e-") as directory:
    app = Application(Path(directory), DemoRuntime())
    server = make_server(app, port=18088)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()
