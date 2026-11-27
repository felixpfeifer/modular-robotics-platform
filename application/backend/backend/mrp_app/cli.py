"""CLI client for the same API used by the browser."""

import argparse
import json
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description="MRP recording application CLI")
    parser.add_argument("--url", default="http://127.0.0.1:8088")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("episodes")
    project = commands.add_parser("project")
    project.add_argument("name")
    cell = commands.add_parser("cell")
    cell.add_argument("action", choices=["plan", "status", "up", "down"])
    source = commands.add_parser("source")
    source.add_argument("source", choices=["none", "teleop"])
    start = commands.add_parser("start")
    start.add_argument("project_id")
    start.add_argument("--request-id", default=None)
    mark = commands.add_parser("mark")
    mark.add_argument("episode_id")
    mark.add_argument("kind", choices=["success", "failure", "annotation", "cancel"])
    mark.add_argument("--annotation", default="")
    export = commands.add_parser("export")
    export.add_argument("episode_ids", nargs="+")
    export.add_argument("--repo-id", default="local/mock-so101")
    export.add_argument("--request-id", default=None)
    args = parser.parse_args()
    body = None
    if args.command in ("status", "episodes"):
        path = "/api/v1/" + args.command
    elif args.command == "project":
        path, body = "/api/v1/projects", {"name": args.name}
    elif args.command == "cell":
        path = "/api/v1/cell/" + args.action
        body = {} if args.action in ("up", "down") else None
    elif args.command == "source":
        path, body = "/api/v1/control", {"source": args.source}
    elif args.command == "start":
        path, body = (
            "/api/v1/sessions",
            {"project_id": args.project_id, "request_id": args.request_id or str(uuid.uuid4())},
        )
    elif args.command == "mark":
        path, body = (
            f"/api/v1/sessions/{args.episode_id}/mark",
            {"kind": args.kind, "annotation": args.annotation},
        )
    else:
        path, body = (
            "/api/v1/exports",
            {
                "episode_ids": args.episode_ids,
                "repo_id": args.repo_id,
                "request_id": args.request_id or str(uuid.uuid4()),
            },
        )
    if body and "request_id" in body:
        print("Request ID: " + body["request_id"], file=sys.stderr)
    request = Request(
        args.url.rstrip("/") + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=160) as response:
            print(json.dumps(json.load(response), indent=2))
    except HTTPError as exc:
        print(exc.read().decode(), file=sys.stderr)
        return 1
    except (URLError, TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
