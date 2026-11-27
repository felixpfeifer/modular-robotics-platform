"""Local LeRobot inference server for explicitly selected checkpoints."""

import argparse
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .contract import JOINTS, MAX_IMAGE_BYTES, observation, vector


class LeRobotPolicy:
    def __init__(self, checkpoint, device, policy="act", task=""):
        import torch
        from lerobot.policies import make_pre_post_processors
        from lerobot.policies.factory import get_policy_class
        from training_lerobot.job import inspect_base_model

        checkpoint = Path(checkpoint).resolve(strict=True)
        if not checkpoint.is_dir():
            raise ValueError("Checkpoint must be an existing local directory.")
        self.torch = torch
        self.device = torch.device(device)
        inspect_base_model(checkpoint, policy)
        self.policy = policy
        self.task = task
        if policy != "act" and not task.strip():
            raise ValueError("A task instruction is required for VLA policies.")
        self.model = (
            get_policy_class(policy)
            .from_pretrained(str(checkpoint))
            .to(self.device)
            .eval()
        )
        self.pre, self.post = make_pre_post_processors(
            self.model.config,
            pretrained_path=str(checkpoint),
            preprocessor_overrides={"device_processor": {"device": device}},
        )
        inputs = self.model.config.input_features
        cameras = [key for key in inputs if key.startswith("observation.images.")]
        provenance = {
            "observation.source_timestamp_ns",
            "observation.receive_timestamp_ns",
            "observation.state_skew_ms",
        }
        if len(cameras) != 1 or set(inputs) - provenance != {
            "observation.state",
            cameras[0],
        }:
            raise ValueError(
                "Checkpoint must expect one RGB camera and a six-joint state."
            )
        self.image_feature = cameras[0]
        image_shape = tuple(inputs[self.image_feature].shape)
        if (
            tuple(inputs["observation.state"].shape) != (6,)
            or len(image_shape) != 3
            or image_shape[0] != 3
            or any(not isinstance(n, int) or n < 1 for n in image_shape[1:])
        ):
            raise ValueError("Checkpoint observation shape does not match this cell.")
        self.image_shape = (image_shape[1], image_shape[2], 3)
        if tuple(self.model.config.output_features["action"].shape) != (6,):
            raise ValueError("Checkpoint must output six joint positions.")

    def reset(self):
        self.model.reset()

    def infer(self, state, image):
        import cv2
        import numpy as np

        frame = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None or frame.shape != self.image_shape:
            raise ValueError(f"Expected a JPEG image with shape {self.image_shape}.")
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        batch = {
            "observation.state": self.torch.tensor(state, dtype=self.torch.float32),
            self.image_feature: self.torch.from_numpy(rgb).permute(2, 0, 1).float()
            / 255.0,
        }
        if self.task:
            batch["task"] = self.task
        with self.torch.inference_mode():
            result = self.post(self.model.select_action(self.pre(batch)))
        return vector(result.squeeze(0).detach().cpu().tolist())


def make_server(policy, host="127.0.0.1", port=8092):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body):
            raw = json.dumps(body, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path != "/health":
                return self.reply(404, {"error": "not found"})
            return self.reply(
                200,
                {
                    "ready": True,
                    "policy": getattr(policy, "policy", "act"),
                    "joints": JOINTS,
                    "image_feature": policy.image_feature,
                },
            )

        def do_POST(self):
            if self.path not in ("/act", "/reset"):
                return self.reply(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if (
                    self.headers.get_content_type() != "application/json"
                    or not 0 < length <= MAX_IMAGE_BYTES * 2
                ):
                    raise ValueError("Invalid request size or content type.")
                self.connection.settimeout(5)
                body = json.loads(self.rfile.read(length))
                with lock:
                    if self.path == "/reset":
                        if body != {}:
                            raise ValueError("Reset accepts an empty JSON object.")
                        policy.reset()
                        return self.reply(200, {"reset": True})
                    state, image = observation(body)
                    action = policy.infer(state, image)
                return self.reply(
                    200,
                    {
                        "request_id": body["request_id"],
                        "image_stamp_ns": body["image_stamp_ns"],
                        "action": action,
                    },
                )
            except (ValueError, TypeError, KeyError) as exc:
                return self.reply(400, {"error": str(exc)})
            except Exception:
                logging.exception("Policy inference failed")
                return self.reply(
                    500, {"error": "Inference failed; inspect server logs."}
                )

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(
        description="Serve a local LeRobot checkpoint for the policy source"
    )
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--policy", choices=("act", "smolvla", "groot"), default="act")
    parser.add_argument(
        "--task", default="", help="Task instruction for VLA checkpoints"
    )
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address; use 0.0.0.0 only inside a private container network (no authentication)",
    )
    parser.add_argument("--port", type=int, default=8092)
    args = parser.parse_args()
    policy = LeRobotPolicy(args.checkpoint, args.device, args.policy, args.task)
    server = make_server(policy, host=args.host, port=args.port)
    print(f"Policy server listening on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
