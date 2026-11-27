"""Resolve and check the selected devices before a cell starts."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

import devices as hw
from cell_plan import Devices, Document, camera_of, camera_settings, sdk_ros_args
from mrp_app import cameras as camera_models

Runner = Callable[..., CompletedProcess[str]]
LEGACY_CAMERA_TITLES = {"webcam": ("Camera", "camera"), "side": ("Side camera", "side_camera")}


def real_slots(cell: Document) -> list[Document]:
    """Every component that uses a host device: real arms and USB cameras."""
    slots = []
    for arm in cell["arms"]:
        if arm["backend"] == "real":
            label = arm["role"] if arm["id"] == arm["role"] else f"{arm['role']} '{arm['id']}'"
            slots.append({"key": arm["id"], "kind": arm["role"], "service": arm["service"],
                          "label": label, "entry": arm.get("device") or {}})  # fmt: skip
    for camera in cell["cameras"]:
        if camera["source"] == "opencv_usb":
            slots.append({"key": camera["id"], "kind": "camera", "service": camera["service"],
                          "label": f"camera '{camera['id']}'", "entry": camera.get("device") or {}})  # fmt: skip
        elif camera_models.is_real(camera["source"]):
            # Found by serial number by the driver itself; there is no host node to resolve.
            slots.append({"key": camera["id"], "kind": "sdk_camera", "service": camera["service"],
                          "label": f"camera '{camera['id']}'", "entry": camera.get("device") or {},
                          "model": camera["source"]})  # fmt: skip
    return slots


def selection(cell: Document, sys_root: str) -> Devices | None:
    """Resolve and validate the requested devices against a fresh scan. Returns a dict or None."""
    resolved: Devices = {}
    for slot in real_slots(cell):
        if slot["kind"] == "sdk_camera":
            item = {k: v for k, v in slot.items() if k != "entry"}
            entry = slot["entry"]
            found_by = entry.get("serial") or entry.get("address") or "first found"
            item.update(entry, path=f"{slot['model']}:{found_by}")
            resolved[slot["key"]] = item
            continue
        field = "device" if slot["kind"] == "camera" else "port"
        if not slot["entry"].get(field):
            raise ValueError(f"Select the {slot['label']} device first.")
        item = {k: v for k, v in slot.items() if k != "entry"}
        item.update(slot["entry"], path=hw.resolve(slot["entry"], slot["kind"], sys_root))
        resolved[slot["key"]] = item
    paths = [item["path"] for item in resolved.values()]
    if len(set(paths)) != len(paths):
        raise ValueError("Each selected device must be a different device.")
    return resolved or None


def fingerprint(ident: str, resolved: Devices | None, cell: Document) -> str:
    parts = [ident] + [
        f"{key}:{item['path']}:{item.get('serial', '')}:{item.get('calibration', '')}:"
        + (json.dumps(camera_settings(camera_of(cell, key))) if "camera" in item["kind"] else "")
        for key, item in sorted((resolved or {}).items())
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def connection_test(
    ident: str,
    resolved: Devices,
    cell: Document,
    root: Path,
    overlay_dir: Path,
    sys_root: str,
    runner: Runner,
) -> Document:
    """Read-only checks of every selected real device. Returns a checklist."""
    checks: list[Document] = []

    def add(name: str, ok: object, detail: str, level: str | None = None, **extra: Any) -> None:
        checks.append(
            {
                "name": name,
                "ok": bool(ok),
                "detail": detail,
                "level": level or ("ok" if ok else "error"),
                **extra,
            }
        )

    reports: dict[str, Any] = {}
    arms = {key: item for key, item in resolved.items() if item["kind"] in hw.ROLES}
    calibrations = hw.list_calibrations(runner) if arms else []
    for key, item in arms.items():
        title = item["label"][:1].upper() + item["label"][1:]
        report = hw.probe_arm(item["path"], root / "driver", "scan", run=runner)
        reports[key] = report
        add(
            f"{title} port",
            "servos" in report,
            item["path"] if "servos" in report else report.get("error", "no answer"),
        )
        if "servos" not in report:
            continue
        add(
            f"{title} servos",
            report["ok"],
            "6 STS3215 servos answer" if report["ok"] else " ".join(report["problems"]),
        )
        volts = report.get("voltage_v")
        add(
            f"{title} supply",
            volts is not None and 4.5 <= volts <= 13.0,
            f"{volts} V" if volts else "no voltage reading",
        )
        calibration = item["calibration"]
        add(
            f"{title} calibration",
            calibration in calibrations,
            calibration
            if calibration in calibrations
            else f"{calibration} not found: run the calibration wizard or import a file",
        )
        if item["kind"] == "follower":
            add(
                f"{title} torque",
                True,
                "off (will be enabled when the cell starts)"
                if not report["torque_enabled"]
                else "already on",
                "ok" if not report["torque_enabled"] else "warn",
            )
    for arm in cell["arms"]:
        leader, follower = reports.get(arm.get("leader")), reports.get(arm["id"])
        if arm["role"] != "follower" or not leader or not follower:
            continue
        if "servos" not in leader or "servos" not in follower:
            continue
        gaps = [
            abs((a["position"] - b["position"] + 2048) % 4096 - 2048) * 6.283185 / 4096
            for a, b in zip(leader["servos"], follower["servos"])
            if a.get("position") is not None and b.get("position") is not None
        ]
        worst = max(gaps) if gaps else None
        if worst is not None:
            pair = "Leader/follower" if not cell["multi_arm"] else f"{arm['leader']}/{arm['id']}"
            add(
                f"{pair} pose",
                worst <= 0.15,
                f"largest difference {worst:.2f} rad"
                + (
                    ""
                    if worst <= 0.15
                    else " (>0.15 rad: match the leader to the follower before enabling teleop)"
                ),
                "ok" if worst <= 0.15 else "warn",
            )
    for key, item in resolved.items():
        if item["kind"] != "camera":
            continue
        camera = camera_of(cell, key)
        # The original two cameras keep their titles and roles, which the setup page reads.
        title, role = LEGACY_CAMERA_TITLES.get(key, (f"Camera '{key}'", key))
        wanted = camera_settings(camera)
        report = hw.probe_camera(
            item["path"],
            root / "driver",
            wanted["width"],
            wanted["height"],
            wanted["fps"],
            3.0,
            True,
            run=runner,
        )
        if report.get("ok"):
            add(f"{title} opens", True, f"{report['width']}x{report['height']}")
            add(
                f"{title} resolution",
                report["resolution_ok"],
                f"{report['width']}x{report['height']}"
                + ("" if report["resolution_ok"] else f" (need {wanted['width']}x{wanted['height']})"),
            )
            add(
                f"{title} frame rate", report["fps"] >= 0.9 * wanted["fps"],
                f"{report['fps']} fps (need {wanted['fps']})",
                role=role, camera_id=key, measured_fps=report["fps"], target_fps=wanted["fps"],
            )  # fmt: skip
            checks.append(
                {
                    "name": f"{title} snapshot",
                    "ok": True,
                    "level": "ok",
                    "detail": "preview",
                    "jpeg_base64": hw.snapshot_b64(report),
                }
            )
        else:
            add(f"{title} opens", False, report.get("error", "failed"))
    for key, item in resolved.items():
        if item["kind"] != "sdk_camera":
            continue
        title, role = LEGACY_CAMERA_TITLES.get(key, (f"Camera '{key}'", key))
        model = camera_models.models()[item["model"]]
        image = model["image"]
        built = hw.image_present(image, runner)
        add(
            f"{title} driver image",
            built,
            image
            if built
            else f"{image} is not built. "
            + (
                "Put the IDS Software Suite in driver/camera_ids/sdk/ and run ./start.sh."
                if item["model"] == "ids_ueye"
                else "Get it: ./start.sh."
                if model.get("origin", "builtin") == "builtin"
                else "Pull it on the Cell page (camera type > Pull image) or run docker pull."
            ),
        )
        found = (
            None
            if model["access"] == "network"
            else hw.sdk_cameras(item["model"], sys_root, model.get("usb"))
        )
        serial = item.get("serial")
        matches: bool | list[Document]
        if found is None:
            # Network camera, or a custom model without a USB id: only opening it tells.
            matches = True
            add(f"{title} connected", True, "Checked by opening the camera below.", level="warn")
        else:
            # Before the IDS firmware upload the camera reports no serial number, so only count it.
            matches = [d for d in found if not serial or not d["serial"] or d["serial"] == serial]
            add(
                f"{title} connected",
                bool(matches),
                f"{len(found)} {model['label']} USB device(s) found"
                if matches
                else f"No {model['label']} on USB"
                + (f" with serial {serial}" if serial and found else "")
                + ": plug it in (on WSL attach it with usbipd).",
            )
        if not built or not matches:
            continue
        # Open it for real: the cell's driver and settings in a throwaway, network-less container.
        camera = camera_of(cell, key)
        wanted = camera_settings(camera)
        report = hw.probe_sdk_camera(
            image,
            [*model["probe_command"], *sdk_ros_args(camera, "/mrp_probe/image/compressed")],
            "/mrp_probe/image/compressed",
            wanted["width"],
            wanted["height"],
            wanted["fps"],
            overlay_dir,
            run=runner,
            access=model["access"],
        )
        if not report.get("ok"):
            tail = " | ".join((report.get("log") or [])[-3:])
            add(
                f"{title} opens",
                False,
                report.get("error", "failed") + (f" Driver log: {tail}" if tail else ""),
            )
            continue
        add(f"{title} opens", True, f"{report['width']}x{report['height']}, {report['frames']} images")
        add(
            f"{title} resolution",
            report["resolution_ok"],
            f"{report['width']}x{report['height']}"
            + ("" if report["resolution_ok"] else f" (need {wanted['width']}x{wanted['height']})"),
        )
        fps_ok = report["fps"] >= 0.9 * wanted["fps"]
        flexible = item["model"] == "ids_ueye"
        add(
            f"{title} frame rate", fps_ok if not flexible else report["frames"] > 1,
            f"{report['fps']} fps (target {wanted['fps']})",
            level="warn" if flexible and not fps_ok and report["frames"] > 1 else None,
            role=role, camera_id=key, measured_fps=report["fps"], target_fps=wanted["fps"],
        )  # fmt: skip
        if report.get("jpeg_base64"):
            checks.append(
                {"name": f"{title} snapshot", "ok": True, "level": "ok", "detail": "preview",
                 "jpeg_base64": hw.snapshot_b64(report)}
            )  # fmt: skip
    passed = all(c["ok"] or c["level"] == "warn" for c in checks)
    return {"passed": passed, "checks": checks, "fingerprint": fingerprint(ident, resolved, cell)}
