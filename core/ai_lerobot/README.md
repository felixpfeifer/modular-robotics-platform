# ai_lerobot

Train and serve LeRobot ACT, SmolVLA and GR00T checkpoints. The image includes
LeRobot's model-specific extras. SmolVLA and GR00T paths are experimental and
have not been validated end to end on this cell. GR00T requires an NVIDIA GPU
and a compatible N1.7 foundation model; N1.5 is unsupported. See upstream
[SmolVLA](https://huggingface.co/docs/lerobot/smolvla) and
[GR00T](https://huggingface.co/docs/lerobot/groot) documentation.

The ROS `control_arbiter` package supplies `policy_source`, which constructs
observations from the cell topics and publishes policy intents to the arbiter.
The server accepts a checkpoint with one RGB camera, six joint positions and six
absolute joint-position outputs. The camera must be the same view and resolution
used in training; multi-camera and other robot configurations are not supported.

## Use from the MRP platform

`./start.sh` builds this image as `mrp-ai-lerobot:dev`. The deployment agent then runs
[training.compose.yaml](training.compose.yaml) (offline `train`, and `hub_import` using the `import`
command) and [policy.compose.yaml](policy.compose.yaml) (`act_server` plus the ROS `policy_source`).
Before each training run the agent checks that PyTorch inside this image can use an NVIDIA GPU. If so,
the run uses `training.gpu.compose.yaml` and `--device cuda`; if not, the UI shows why and trains on the
CPU only after the user confirms.
The server listens on `0.0.0.0` only inside the private policy network and publishes no port.

## Build on x86-64 NVIDIA GPU

```sh
docker build -t ai_lerobot:cuda .
docker run --rm --gpus all ai_lerobot:cuda doctor --require-cuda
```

The Dockerfile starts from PyTorch 2.11 / CUDA 12.8 and retains its PyTorch and
TorchVision. LeRobot 0.6.1 and the remaining dependencies come from the included
lock file. A compatible NVIDIA driver and container runtime are required.

## Train and keep local checkpoints

Mount a local LeRobot v3 dataset read-only and a writable output directory.
Replace `/absolute/path/to/dataset` and `/absolute/path/to/output` with your
actual paths (make the output directory first). This example is offline:

```sh
mkdir -p /absolute/path/to/output
docker run --rm --gpus all --network none \
  -v /absolute/path/to/dataset:/dataset:ro \
  -v /absolute/path/to/output:/output \
  ai_lerobot:cuda train --policy act --dataset /dataset \
  --repo-id local/task --runs-dir /output --device cuda \
  --steps 1000 --batch-size 8 --chunk-size 100
```

`/output/RUN_ID/output/checkpoints/last/pretrained_model` contains the final
model and processors. Each run also writes `job.json` and `train.log`; output is
streamed to container logs. The run ID appears in the final JSON. To see all
trainer options, run `docker run --rm --entrypoint python3 ai_lerobot:cuda -m
training_lerobot.job --help`. `--smoke` is a tiny test model, not a trained
policy. Local output is always retained, including when upload fails.

For SmolVLA, download the LeRobot-formatted base checkpoint and its tokenizer /
backbone assets into the local Hugging Face cache before running offline. Mount
the checkpoint and cache into the container and use `--policy smolvla
--base-model /model`. For GR00T use `--policy groot --base-model /model`, where
`/model` is a local N1.7 foundation model directory (uses `new_embodiment`)
or an existing LeRobot GR00T checkpoint. Mount all required cached model assets:
training sets Hugging Face offline mode. Model requirements and compatible
checkpoint files vary; a failed load is reported in `train.log`. The base
checkpoint must match the dataset and robot.

## Optional automatic upload

Set a Hugging Face write token in your shell without adding it to a file or
command history, and use a network-enabled container. Add `-e HF_TOKEN` and
`--hub-repo YOUR_ACCOUNT/YOUR_MODEL` to the training command and omit
`--network none`. Training itself remains offline; the completed checkpoint is
uploaded afterward. A missing token stops the job before training starts.

New repositories are private by default. `--hub-public` creates a new public
repository; uploading to an existing repository does not change its visibility.
The token is not written to run metadata and is not passed to the training
process. Treat the token as sensitive: Docker administrators can inspect a
container's environment while it runs. An upload failure returns a nonzero exit
code but leaves the local checkpoint intact. Retry without retraining:

```sh
docker run --rm -e HF_TOKEN -v /absolute/path/to/output:/output:ro \
  ai_lerobot:cuda upload --hub-repo YOUR_ACCOUNT/YOUR_MODEL \
  --checkpoint /output/RUN_ID/output/checkpoints/last/pretrained_model
```

Only specify a Hub repository when you intend to publish that checkpoint to
your account. A write token must have permission for that account or organization.

## Local inference

```sh
docker run --rm --gpus all --network host \
  -v /absolute/path/to/output:/output:ro \
  ai_lerobot:cuda serve --policy act --device cuda \
  --checkpoint /output/RUN_ID/output/checkpoints/last/pretrained_model
```

For SmolVLA or GR00T select `--policy smolvla` or `--policy groot` and add
`--task "the task description used for training"`. Provide the model's required
cached tokenizer and backbone assets. Only use a checkpoint fine-tuned for the
cell's joint order, units, camera and absolute actions.

The server binds `127.0.0.1:8092`, has no authentication, and is intended for a
trusted local host. In a ROS environment where `control_arbiter` is built and sourced:

```sh
ros2 launch control_arbiter control.launch.py mode:=none
ros2 run control_arbiter policy_source
ros2 param set /control_arbiter active_source policy
# Stop forwarding:
ros2 param set /control_arbiter active_source none
```

The source defaults to `/joint_states` and `/image/compressed`, and checks source
timestamps, state/image skew, response identity, joint limits and per-step delta.
Change topics using ROS parameters, for example `--ros-args -p
camera_topic:=/my_camera/image/compressed`. The node sends no intents unless policy
is selected, and resets model state when selection changes or observations fail.
The arbiter retains its handover gate and watchdog. Test in simulation before
connecting hardware; the source currently uses SO-101 joint order and limits.
The server and ROS node need to share localhost (or configure `server_url` for a
trusted network). Inference exceeding the freshness timeout is discarded.


## Jetson Orin and Thor

The arm64 image is built FROM `mrp-ros-base-jetson` (Ubuntu 24.04, CUDA 13, JetPack 7.2 on the
device) and installs the pinned PyTorch from the CUDA wheel index in `TORCH_INDEX_URL`. Override
`BASE_IMAGE` / `TORCH_INDEX_URL` to build against another base on the target:

```sh
docker build --build-arg BASE_IMAGE=docker.io/<user>/mrp-ros-base-jetson:latest \
  --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu130 -t ai_lerobot:jetson .
docker run --rm --runtime nvidia ai_lerobot:jetson doctor --require-cuda
```

This path is **experimental and not yet validated on Orin or Thor**. The chosen
base must include Python 3.12, CUDA PyTorch and matching TorchVision compatible
with the pinned LeRobot and TorchCodec versions; the doctor check verifies the
video decoder can load and CUDA is visible but is not a training test. PyTorch
versions and ABI differ across NVIDIA JetPack releases, so the build or doctor
check may fail until a specific combination is tested. Follow the
[NVIDIA Jetson PyTorch compatibility table](https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform-release-notes/pytorch-jetson-rel.html),
then run one-step training and inference on the actual device before use.

## Checks

```sh
python3 -m unittest discover -s tests -v
```
