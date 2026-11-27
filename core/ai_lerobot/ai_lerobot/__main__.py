"""Run one policy adapter for training, serving, or checkpoint upload."""

import argparse
import os
import re
import sys
from pathlib import Path

from training_lerobot import job


def upload(checkpoint, repo_id, token, private=True):
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repo_id
    ):
        raise ValueError("Hub repository must have the form namespace/model-name")
    if not token:
        raise ValueError("Set HF_TOKEN to a Hugging Face write token")
    job.inspect_base_model(checkpoint)
    # Import after clearing offline mode: huggingface_hub reads it at import time.
    os.environ["HF_HUB_OFFLINE"] = "0"
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo_id=repo_id, repo_type="model", private=private, exist_ok=True)
    api.upload_folder(repo_id=repo_id, repo_type="model", folder_path=str(checkpoint))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Train or serve a robot policy without connecting a robot driver"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser(
        "train", help="Train a policy and optionally upload its final checkpoint"
    )
    train.add_argument("--policy", choices=["act", "smolvla", "groot"], default="act")
    train.add_argument(
        "--hub-repo", help="Upload the final checkpoint to namespace/model"
    )
    train.add_argument(
        "--hub-public", action="store_true", help="Create a new Hub repo as public"
    )
    serve = sub.add_parser(
        "serve", help="Serve a LeRobot checkpoint to the ROS 2 policy bridge"
    )
    serve.add_argument("--policy", choices=["act", "smolvla", "groot"], default="act")
    publish = sub.add_parser(
        "upload", help="Retry an upload from an existing LeRobot checkpoint"
    )
    publish.add_argument("--checkpoint", type=Path, required=True)
    publish.add_argument("--hub-repo", required=True)
    publish.add_argument("--hub-public", action="store_true")
    sub.add_parser(
        "import",
        help="Download a checkpoint from the Hugging Face Hub into the runs directory",
    )
    doctor = sub.add_parser(
        "doctor", help="Check PyTorch, video decoding and GPU compatibility"
    )
    doctor.add_argument("--require-cuda", action="store_true")
    args, remaining = parser.parse_known_args(argv)

    if args.command == "doctor":
        if remaining:
            parser.error("unrecognized arguments: " + " ".join(remaining))
        import platform
        import torch
        import torchvision
        from torchcodec.decoders import VideoDecoder  # noqa: F401; checks the native library

        print(
            f"arch={platform.machine()} torch={torch.__version__} torchvision={torchvision.__version__} "
            f"cuda={torch.version.cuda} available={torch.cuda.is_available()}"
        )
        return 1 if args.require_cuda and not torch.cuda.is_available() else 0
    if args.command == "import":
        from training_lerobot import hub_import

        return hub_import.run(hub_import.parse_args(remaining))
    if args.command == "serve":
        from policy_lerobot.server import main as serve_main

        sys.argv = [sys.argv[0], "--policy", args.policy, *remaining]
        return serve_main() or 0
    if args.command == "upload" and remaining:
        parser.error("unrecognized arguments: " + " ".join(remaining))
    if args.command == "train":
        options = job.parse_args(["--policy", args.policy, *remaining])
        if args.hub_repo and not os.environ.get("HF_TOKEN"):
            parser.error("--hub-repo requires HF_TOKEN")
        if args.hub_repo and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", args.hub_repo
        ):
            parser.error("--hub-repo must have the form namespace/model-name")
        result = job.run(options)
        if result or not args.hub_repo:
            return result
        checkpoint = (
            options.runs_dir
            / options.run_id
            / "output/checkpoints/last/pretrained_model"
        )
    else:
        checkpoint = args.checkpoint
    try:
        upload(
            checkpoint, args.hub_repo, os.environ.get("HF_TOKEN"), not args.hub_public
        )
    except Exception as exc:
        # Avoid including credentials or HTTP request details in logs.
        print(
            f"Upload failed ({type(exc).__name__}); local checkpoint retained.",
            file=sys.stderr,
        )
        return 1
    print(f"Uploaded checkpoint to https://huggingface.co/{args.hub_repo}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
