import argparse
import os
from pathlib import Path

from .runtime import DemoRuntime
from .server import make_server
from .service import Application


def main():
    parser = argparse.ArgumentParser(description="MRP local recording dashboard")
    parser.add_argument("--mode", choices=["demo", "ros"], default=os.getenv("MRP_MODE", "demo"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument(
        "--allow-origin", action="append", default=os.getenv("MRP_ALLOWED_ORIGINS", "").split(",")
    )
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("MRP_DATA_DIR", ".data")))
    parser.add_argument("--workspace-config", default=os.getenv("MRP_WORKSPACE_CONFIG"))
    parser.add_argument("--exports-dir", default=os.getenv("MRP_EXPORTS_DIR"))
    parser.add_argument("--agent-url", default=os.getenv("MRP_AGENT_URL"))
    parser.add_argument("--user-data-dir", default=os.getenv("MRP_USER_DATA_DIR"))
    parser.add_argument("--runs-dir", default=os.getenv("MRP_RUNS_DIR"))
    parser.add_argument("--runtime-preset", default=os.getenv("MRP_RUNTIME_PRESET", "mock-so101"))
    args = parser.parse_args()
    runtime, snapshot, dataset_dir = DemoRuntime(), None, None
    if args.mode == "ros":
        if not args.workspace_config:
            parser.error("ROS mode requires --workspace-config.")
        try:
            from .network import configure_zenoh

            configure_zenoh()
            from .ros_runtime import DeferredRosRuntime

            runtime = DeferredRosRuntime(args.workspace_config)
            snapshot = runtime.snapshot()
            dataset_dir = snapshot["dataset_dir"]
        except (ImportError, ValueError, RuntimeError) as exc:
            parser.error(
                f"Cannot initialize ROS mode: {exc}. Source ROS Jazzy and the recorder/interfaces workspace."
            )
    app = Application(
        args.data_dir / args.mode,
        runtime,
        snapshot,
        dataset_dir,
        args.exports_dir,
        args.agent_url,
        args.runtime_preset,
        args.runs_dir,
        args.user_data_dir,
    )
    server = make_server(app, args.host, args.port, args.allow_host, filter(None, args.allow_origin))
    print(f"MRP {args.mode} dashboard: http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()
