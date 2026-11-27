"""Opt-in acceptance check against the actual mock recording application.

Uses existing ROS/recorder/converter services. Produces real synthetic MCAP and
LeRobot artifacts; never substitutes unit-test bytes for those artifacts.
"""

import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8088")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    evidence = {"started": time.time(), "url": args.url}
    out = Path("artifacts")
    out.mkdir(exist_ok=True)

    def api(path, body=None):
        req = Request(
            args.url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=160) as response:
            return json.load(response)

    def wait(predicate, seconds=args.timeout):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(1)
        raise TimeoutError("Acceptance condition was not met. Inspect saved evidence and service logs.")

    try:
        initial = api("/api/v1/status")
        assert initial["mode"] == "ros", "Acceptance requires ROS mode."
        assert initial["configuration"]["id"] == "mock_so101_webcam", "Only the mock baseline is allowed."
        plan = api("/api/v1/cell/plan")
        services = plan["services"]
        assert services["leader"]["environment"]["BACKEND"] == "mock"
        assert services["follower"]["environment"]["BACKEND"] == "mock"
        assert not any(service.get("devices") or service.get("privileged") for service in services.values())
        evidence["plan"] = plan
        assert not initial["runtime"]["active_episode_id"], "Do not interrupt an existing episode."
        project = api("/api/v1/projects", {"name": "Mock acceptance " + time.strftime("%Y-%m-%d %H:%M")})
        api("/api/v1/cell/up", {"project_id": project["id"]})
        wait(lambda: api("/api/v1/status")["runtime"]["cell_running"])
        # Wait for the arbiter discovery instead of racing the first image/state.
        wait(lambda: api("/api/v1/status")["runtime"]["active_source"] == "none")
        api("/api/v1/control", {"source": "teleop"})
        wait(lambda: api("/api/v1/status")["runtime"]["ready"])
        request = {"request_id": str(uuid.uuid4()), "project_id": project["id"]}
        episode = api("/api/v1/sessions", request)
        evidence["session"] = episode
        assert api("/api/v1/sessions", request)["id"] == episode["id"], (
            "Duplicate request created another session."
        )
        time.sleep(max(7, initial["configuration"]["minimum_duration_seconds"] + 2))
        api(f"/api/v1/sessions/{episode['id']}/mark", {"kind": "success"})

        def finalized():
            rows = api("/api/v1/episodes")["episodes"]
            return next((row for row in rows if row["id"] == episode["id"] and row.get("validation")), None)

        artifact = wait(finalized)
        evidence["artifact"] = artifact
        assert artifact["status"] == "accepted", "Recorded fixture failed validation; inspect evidence."
        job = api(
            "/api/v1/exports",
            {
                "request_id": str(uuid.uuid4()),
                "project_id": project["id"],
                "episode_ids": [episode["id"]],
                "repo_id": "local/mock-acceptance",
            },
        )

        def exported():
            jobs = api("/api/v1/status")["jobs"]
            return next(
                (
                    item
                    for item in jobs
                    if item["id"] == job["id"] and item["state"] in ("complete", "failed", "interrupted")
                ),
                None,
            )

        evidence["export"] = wait(exported, seconds=3600)
        assert evidence["export"]["state"] == "complete", "Export did not complete."
        evidence["passed"] = True
        api("/api/v1/control", {"source": "none"})
        print("PASS: actual mock MCAP recorded, accepted and exported with dataset reopening verification.")
    except Exception as exc:
        evidence["passed"] = False
        evidence["error"] = str(exc)
        raise
    finally:
        (out / "record-export.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
