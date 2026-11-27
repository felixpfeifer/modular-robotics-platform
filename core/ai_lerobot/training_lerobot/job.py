"""Validate and execute a local, offline LeRobot training job."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Train a policy from a local LeRobot v3 dataset"
    )
    parser.add_argument("--policy", choices=["act", "smolvla", "groot"], default="act")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--repo-id",
        required=True,
        help="Local dataset identifier, namespace/name; no upload",
    )
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--steps", type=positive, default=1000)
    parser.add_argument("--batch-size", type=positive, default=8)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--chunk-size", type=positive, default=100)
    parser.add_argument(
        "--run-id", default=None, help="Optional canonical UUID; must not already exist"
    )
    parser.add_argument(
        "--base-model",
        type=Path,
        default=None,
        help="Existing pretrained_model directory to fine-tune from (local path only)",
    )
    parser.add_argument(
        "--label",
        default="",
        help="Operator label stored with the run, max 80 characters",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Small random ACT architecture for pipeline tests only",
    )
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", args.repo_id):
        parser.error("repo-id must use namespace/name syntax")
    if args.workers < 0 or args.workers > 16:
        parser.error("workers must be between 0 and 16")
    if len(args.label) > 80 or any(ord(c) < 32 for c in args.label):
        parser.error("label must be at most 80 printable characters")
    if args.policy != "act" and not args.base_model:
        parser.error("--base-model is required for smolvla and groot")
    if args.smoke and args.policy != "act":
        parser.error("--smoke is only available for act")
    if args.base_model is not None and args.smoke:
        parser.error(
            "--smoke builds a new tiny architecture and cannot be combined with --base-model"
        )
    if args.run_id:
        try:
            if str(uuid.UUID(args.run_id)) != args.run_id:
                raise ValueError
        except ValueError:
            parser.error("run-id must be a canonical UUID")
    else:
        args.run_id = str(uuid.uuid4())
    return args


def inspect_dataset(dataset: Path) -> dict:
    dataset = dataset.expanduser().resolve(strict=True)
    metadata = dataset / "meta" / "info.json"
    info = json.loads(metadata.read_text())
    if not str(info.get("codebase_version", "")).startswith("v3."):
        raise ValueError("expected a LeRobot v3 dataset")
    features = info.get("features", {})
    if "action" not in features or "observation.state" not in features:
        raise ValueError("dataset requires action and observation.state features")
    if not any(name.startswith("observation.images.") for name in features):
        raise ValueError("dataset requires at least one observation camera")
    if int(info.get("total_episodes", 0)) < 1 or int(info.get("total_frames", 0)) < 1:
        raise ValueError("dataset has no recorded episodes or frames")
    digest = hashlib.sha256(metadata.read_bytes()).hexdigest()
    return {"path": str(dataset), "info_sha256": f"sha256:{digest}", "info": info}


def inspect_base_model(path: Path, policy=None) -> dict:
    """Validate a complete local LeRobot pretrained_model directory."""
    path = path.expanduser().resolve(strict=True)
    required = [
        "config.json",
        "model.safetensors",
        "policy_preprocessor.json",
        "policy_postprocessor.json",
    ]
    missing = [name for name in required if not (path / name).is_file()]
    if missing:
        raise ValueError(f"base model is missing {missing}")
    config = json.loads((path / "config.json").read_text())
    if config.get("type") not in ("act", "smolvla", "groot"):
        raise ValueError("unsupported checkpoint policy type")
    if policy and config.get("type") != policy:
        raise ValueError(f"base model must be a {policy} policy")
    return {
        "path": str(path),
        "config_sha256": "sha256:"
        + hashlib.sha256((path / "config.json").read_bytes()).hexdigest(),
    }


def command(args, dataset, output):
    cmd = [
        "lerobot-train",
        f"--dataset.repo_id={args.repo_id}",
        f"--dataset.root={dataset}",
        *(
            [
                f"--policy.type=groot",
                f"--policy.base_model_path={args.base_model}",
                "--policy.embodiment_tag=new_embodiment",
            ]
            if getattr(args, "groot_foundation", False)
            else [f"--policy.path={args.base_model}"]
            if args.base_model
            else [f"--policy.type={args.policy}"]
        ),
        f"--policy.device={args.device}",
        "--policy.push_to_hub=false",
        *(
            [
                "--policy.pretrained_backbone_weights=null",
                f"--policy.chunk_size={args.chunk_size}",
                f"--policy.n_action_steps={args.chunk_size}",
            ]
            if args.policy == "act" and not args.base_model
            else []
        ),
        f"--output_dir={output}",
        f"--job_name=mrp-{args.policy}-{args.run_id[:8]}",
        f"--steps={args.steps}",
        f"--batch_size={args.batch_size}",
        f"--num_workers={args.workers}",
        f"--seed={args.seed}",
        "--wandb.enable=false",
        "--save_checkpoint=true",
        f"--save_freq={args.steps}",
        "--env_eval_freq=0",
    ]
    if args.smoke:
        cmd.extend(
            [
                "--policy.dim_model=64",
                "--policy.n_heads=4",
                "--policy.dim_feedforward=128",
                "--policy.n_encoder_layers=1",
                "--policy.n_decoder_layers=1",
                "--policy.n_vae_encoder_layers=1",
                "--policy.latent_dim=16",
            ]
        )
    return cmd


def write_json(path, payload):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def run(args):
    dataset = inspect_dataset(args.dataset)
    if args.base_model and args.policy == "groot":
        path = args.base_model.expanduser().resolve(strict=True)
        if not path.is_dir() or not (path / "config.json").is_file():
            raise ValueError(
                "GR00T base model must be a local model directory containing config.json"
            )
        config = json.loads((path / "config.json").read_text())
        if config.get("type") == "groot":
            base_model = inspect_base_model(path, "groot")
        else:
            base_model = {
                "path": str(path),
                "config_sha256": "sha256:"
                + hashlib.sha256((path / "config.json").read_bytes()).hexdigest(),
                "foundation_model": True,
            }
    else:
        base_model = (
            inspect_base_model(args.base_model, args.policy)
            if args.base_model
            else None
        )
    args.groot_foundation = bool(base_model and base_model.get("foundation_model"))
    if base_model:
        args.base_model = Path(base_model["path"])
    runs = args.runs_dir.expanduser().resolve()
    runs.mkdir(parents=True, exist_ok=True)
    run_dir = runs / args.run_id
    run_dir.mkdir(exist_ok=False)
    output = run_dir / "output"
    argv = command(args, dataset["path"], output)
    meta = {
        "schema_version": "mrp-training-job/v1",
        "run_id": args.run_id,
        "status": "running",
        "started_unix": time.time(),
        "framework": "lerobot",
        "framework_version": "0.6.1",
        "policy": args.policy,
        "device": args.device,
        "repo_id": args.repo_id,
        "dataset": dataset,
        "label": args.label,
        "base_model": base_model,
        "configuration": vars(args)
        | {
            "dataset": str(args.dataset),
            "runs_dir": str(args.runs_dir),
            "base_model": str(args.base_model) if args.base_model else None,
        },
        "command": argv,
        "synthetic_smoke": args.smoke,
    }
    write_json(run_dir / "job.json", meta)
    env = os.environ.copy()
    env.pop("HF_TOKEN", None)
    env.update(
        {
            "HF_HUB_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "WANDB_MODE": "disabled",
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }
    )
    try:
        with (run_dir / "train.log").open("w", buffering=1) as log:
            proc = subprocess.Popen(
                argv,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(line)
                print(line, end="", flush=True)
            proc.stdout.close()
            proc.wait()
        checkpoint = output / "checkpoints" / "last" / "pretrained_model"
        required = [
            "config.json",
            "model.safetensors",
            "policy_preprocessor.json",
            "policy_postprocessor.json",
        ]
        missing = [name for name in required if not (checkpoint / name).is_file()]
        meta.update(
            {
                "finished_unix": time.time(),
                "exit_code": proc.returncode,
                "checkpoint": str(checkpoint) if not missing else None,
                "missing_checkpoint_files": missing,
                "status": "complete"
                if proc.returncode == 0 and not missing
                else "failed",
            }
        )
    except (OSError, KeyboardInterrupt) as error:
        meta.update(
            {"finished_unix": time.time(), "status": "failed", "error": str(error)}
        )
    write_json(run_dir / "job.json", meta)
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "status": meta["status"],
                "run_dir": str(run_dir),
                "checkpoint": meta.get("checkpoint"),
            }
        ),
        flush=True,
    )
    return 0 if meta["status"] == "complete" else 1


def main():
    try:
        return run(parse_args())
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Training job failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
