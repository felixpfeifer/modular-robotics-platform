# Development image: build mrp-episode-recorder from core/recorder first.
ARG BASE_IMAGE=mrp-episode-recorder
FROM ${BASE_IMAGE}
WORKDIR /app
COPY requirements.txt requirements-media.txt /app/
RUN apt-get update && apt-get install -y --no-install-recommends python3-pip \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --no-cache-dir --break-system-packages --ignore-installed -r /app/requirements.txt -r /app/requirements-media.txt
COPY backend /app/backend
RUN for package in git git-man; do if dpkg -s "$package" >/dev/null 2>&1; then apt-get purge -y "$package" || exit 1; fi; done && ! command -v git
ENV PYTHONPATH=/app/backend MRP_MODE=ros MRP_DATA_DIR=/data/application
ENTRYPOINT ["/bin/bash", "/ws/entrypoint.sh", "python3", "-m", "mrp_app"]
