import copy
import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from cell_config.model import InvalidConfig, validate
from cell_config.server import Store, serve

EXAMPLE = json.loads((Path(__file__).parents[1] / "examples/cell.json").read_text())


def test_validation():
    validate(EXAMPLE)
    for mutate in (
        lambda d: d["robots"][1].update(id="leader"),
        lambda d: d["control_links"][0].update(leader="follower"),
        lambda d: d["cameras"][0].update(attached_to="missing"),
        lambda d: d["cameras"][0]["connection"].update(path="relative"),
        lambda d: d.update(version=True),
    ):
        doc = copy.deepcopy(EXAMPLE)
        mutate(doc)
        with pytest.raises(InvalidConfig):
            validate(doc)


def test_http_persistence_and_concurrency(tmp_path):
    path = tmp_path / "data" / "cell.json"
    server = serve("127.0.0.1", 0, path)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port)

    def request(method, path, body=None, headers=None):
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), json.loads(response.read())

    try:
        assert request("GET", "/api/v1/cell")[0] == 404
        status, headers, _ = request(
            "PUT", "/api/v1/cell", json.dumps(EXAMPLE), {"If-None-Match": "*"}
        )
        assert status == 200
        tag = headers["ETag"]
        assert Store(path).read()[0] == EXAMPLE
        assert (
            request("PUT", "/api/v1/cell", json.dumps(EXAMPLE), {"If-None-Match": "*"})[
                0
            ]
            == 412
        )
        changed = copy.deepcopy(EXAMPLE)
        changed["name"] = "Changed"
        assert (
            request("PUT", "/api/v1/cell", json.dumps(changed), {"If-Match": tag})[0]
            == 200
        )
        assert (
            request("PUT", "/api/v1/cell", json.dumps(EXAMPLE), {"If-Match": tag})[0]
            == 412
        )
        assert request("GET", "/api/v1/cell")[2]["name"] == "Changed"
        assert request("PUT", "/api/v1/cell", "{}")[0] == 400
        assert request("GET", "/health")[0] == 200
    finally:
        connection.close()
        server.shutdown()
        thread.join()
        server.server_close()


def test_deployment_plan():
    from cell_config.deploy import PlanError, render

    plan = render(EXAMPLE)
    assert plan["services"]["robot_leader"]["environment"]["BACKEND"] == "real"
    assert (
        plan["services"]["robot_follower"]["environment"]["USB_PORT"]
        == "/dev/serial/by-id/follower"
    )
    assert (
        "image/compressed:=/wrist_camera/image/compressed"
        in plan["services"]["camera_wrist_camera"]["command"]
    )
    simulated = copy.deepcopy(EXAMPLE)
    simulated["robots"][0]["connection"] = {"type": "simulated"}
    assert (
        render(simulated)["services"]["robot_leader"]["environment"]["BACKEND"]
        == "mock"
    )
    simulated["robots"][0]["driver"] = "unknown"
    with pytest.raises(PlanError):
        render(simulated)
    collision = copy.deepcopy(EXAMPLE)
    collision["robots"][1]["namespace"] = "/leader"
    with pytest.raises(PlanError):
        render(collision)


def test_demo_deployment_plan():
    from cell_config.deploy import render

    demo = json.loads((Path(__file__).parents[1] / "examples/demo.json").read_text())
    services = render(demo)["services"]
    assert len(services) == 4
    for name in ("robot_leader", "robot_follower"):
        assert services[name]["environment"]["BACKEND"] == "mock"
        assert "volumes" not in services[name]
    for name, topic in (
        ("camera_wrist", "/wrist_camera/image/compressed"),
        ("camera_overview", "/overview_camera/image/compressed"),
    ):
        camera = services[name]
        assert camera["environment"]["CAMERA_TOPIC"] == topic
        assert "devices" not in camera and "privileged" not in camera
        assert camera["healthcheck"]["disable"]


def test_deployment_http(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import subprocess

    calls = []

    def run(command, **kwargs):
        plan = json.loads(Path(command[command.index("--file") + 1]).read_text())
        calls.append((command, plan))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    server = serve("127.0.0.1", 0, tmp_path / "cell.json", "test-cell")
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port)

    def request(method, path, body=None, headers=None):
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        data = response.read()
        return response.status, dict(response.getheaders()), data

    try:
        assert request("GET", "/docs")[0] == 200
        assert (
            "/api/v1/deployment/up"
            in json.loads(request("GET", "/openapi.json")[2])["paths"]
        )
        assert request("POST", "/api/v1/deployment/up")[0] == 404
        _, headers, _ = request("PUT", "/api/v1/cell", json.dumps(EXAMPLE))
        assert (
            request("POST", "/api/v1/deployment/up", headers={"If-Match": '"stale"'})[0]
            == 412
        )
        assert not calls
        assert (
            request(
                "POST", "/api/v1/deployment/up", headers={"If-Match": headers["ETag"]}
            )[0]
            == 200
        )
        assert (
            calls[-1][0][-5:]
            == ["up", "-d", "--remove-orphans", "--no-build", "--pull", "never"][-5:]
        )
        assert calls[-1][1]["services"]["robot_leader"]["image"] == "mrp-robot-so101"
        assert request("GET", "/api/v1/deployment/status")[0] == 200
        assert request("POST", "/api/v1/deployment/down")[0] == 200
        assert all("test-cell" in call[0] for call in calls)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(
                returncode=1, stdout="", stderr="daemon unavailable"
            ),
        )
        assert request("POST", "/api/v1/deployment/down")[0] == 502
    finally:
        connection.close()
        server.shutdown()
        thread.join()
        server.server_close()
