# Built FROM an MRP base image so the platform ROS messages are already installed:
# mrp-ros-base-cuda on amd64, mrp-ros-base-jetson on Jetson Orin (arm64). Fully qualified:
# podman/buildah refuse short names without a TTY.
ARG BASE_IMAGE=docker.io/felixpfeifer/mrp-ros-base-cuda:latest
FROM ${BASE_IMAGE}
# PyTorch wheels pinned in uv.lock are installed from this index (CUDA build matching the base).
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /uvx /bin/
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --frozen --no-dev --no-hashes --no-emit-package torch --no-emit-package torchvision \
      --format requirements-txt > /tmp/requirements.txt && \
    UV_HTTP_TIMEOUT=300 uv pip install --python python3 --system --break-system-packages --no-deps \
      -r /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "$TORCH_INDEX_URL" ]; then \
      uv export --frozen --no-dev --no-hashes --format requirements-txt \
        | grep -E '^(torch|torchvision)==' | cut -d';' -f1 | sed 's/[+ ].*//' | sort -u > /tmp/torch.txt && \
      test "$(wc -l < /tmp/torch.txt)" -eq 2 && \
      UV_HTTP_TIMEOUT=900 UV_CONCURRENT_DOWNLOADS=4 uv pip install --python python3 --system --break-system-packages \
        --index-url "$TORCH_INDEX_URL" -r /tmp/torch.txt; \
    fi && \
    python3 -c 'import torch, torchvision; print("torch", torch.__version__, "torchvision", torchvision.__version__)'
WORKDIR /app
COPY ai_lerobot /app/ai_lerobot
COPY training_lerobot /app/training_lerobot
COPY policy_lerobot /app/policy_lerobot
RUN for package in git git-man; do if dpkg -s "$package" >/dev/null 2>&1; then apt-get purge -y "$package" || exit 1; fi; done && ! command -v git
ENV PYTHONPATH=/app WANDB_MODE=disabled HF_HUB_DISABLE_TELEMETRY=1
ENTRYPOINT ["/platform_entrypoint.sh", "python3", "-m", "ai_lerobot"]
