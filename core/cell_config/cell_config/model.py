"""Validation for the version 1 robot cell document."""

import re


class InvalidConfig(ValueError):
    pass


def validate(doc):
    def fail(message):
        raise InvalidConfig(message)

    def string(value, name):
        if not isinstance(value, str) or not value.strip():
            fail(f"{name} must be a non-empty string")

    def fields(obj, required, optional, name):
        if not isinstance(obj, dict):
            fail(f"{name} must be an object")
        missing = required - obj.keys()
        extra = obj.keys() - required - optional
        if missing or extra:
            fail(f"{name}: missing {sorted(missing)}, unknown {sorted(extra)}")

    fields(
        doc, {"version", "name", "robots", "cameras", "control_links"}, set(), "cell"
    )
    if type(doc["version"]) is not int or doc["version"] != 1:
        fail("version must be 1")
    string(doc["name"], "name")
    for key in ("robots", "cameras", "control_links"):
        if not isinstance(doc[key], list):
            fail(f"{key} must be an array")
    ids = set()
    robots = {}
    for kind in ("robots", "cameras"):
        for item in doc[kind]:
            required = {"id", "name", "driver", "connection"}
            optional = (
                {"role", "namespace"} if kind == "robots" else {"topic", "attached_to"}
            )
            if kind == "robots":
                required |= {"role", "namespace"}
            else:
                required |= {"topic"}
            fields(item, required, optional, kind)
            for key in required - {"connection"}:
                string(item[key], f"{kind}.{key}")
            ident = item["id"]
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", ident) or ident in ids:
                fail(f"invalid or duplicate device id: {ident}")
            ids.add(ident)
            connection = item["connection"]
            fields(
                connection, {"type"}, {"path", "address", "port"}, f"{ident}.connection"
            )
            if connection["type"] not in ("serial", "usb", "network", "simulated"):
                fail(f"{ident}: unsupported connection type")
            if connection["type"] in ("serial", "usb"):
                string(connection.get("path"), f"{ident}.connection.path")
                if not connection["path"].startswith("/dev/"):
                    fail(f"{ident}: device path must start with /dev/")
            if connection["type"] == "network":
                string(connection.get("address"), f"{ident}.connection.address")
                port = connection.get("port")
                if port is not None and (
                    type(port) is not int or not 1 <= port <= 65535
                ):
                    fail(f"{ident}: invalid port")
            allowed = (
                {"type", "path"}
                if connection["type"] in ("serial", "usb")
                else (
                    {"type", "address", "port"}
                    if connection["type"] == "network"
                    else {"type"}
                )
            )
            if connection.keys() - allowed:
                fail(f"{ident}: fields do not match connection type")
            if kind == "robots":
                if item["role"] not in ("leader", "follower"):
                    fail(f"{ident}: role must be leader or follower")
                if not item["namespace"].startswith("/"):
                    fail(f"{ident}: namespace must be absolute (use / for root)")
                robots[ident] = item
            else:
                if not item["topic"].startswith("/"):
                    fail(f"{ident}: topic must be absolute")
                if "attached_to" in item:
                    string(item["attached_to"], f"{ident}.attached_to")
    for camera in doc["cameras"]:
        if "attached_to" in camera and camera["attached_to"] not in robots:
            fail(f"{camera['id']}: attached_to must reference a robot")
    links = set()
    for link in doc["control_links"]:
        fields(link, {"leader", "follower"}, set(), "control link")
        for role in ("leader", "follower"):
            string(link[role], role)
            if link[role] not in robots or robots[link[role]]["role"] != role:
                fail(f"{role} must reference a robot with that role")
        pair = (link["leader"], link["follower"])
        if pair in links:
            fail("duplicate control link")
        links.add(pair)
    return doc
