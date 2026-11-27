# Local CI

Run `./ci.local` inside a component repository to run its normal local checks and build the images defined in its GitLab pipeline. Run the workspace root `./ci.local` to run all components in order. Docker and Docker Compose, network access, and substantial disk space are needed; the tests install dependencies in containers and may take a long time. Run `./ci.local --help` for options. Test outputs and build directories are written to the component checkout; container jobs may create files owned by root.

Images are built for the local Docker host's architecture and tagged `local/<image>:local` by default. To publish, first authenticate with `docker login`, then use, for example:

```bash
./ci.local --push --namespace mydockerhubname --tag dev
```

`DOCKERHUB_USERNAME` can replace `--namespace` and `CI_LOCAL_TAG` can set the default tag. All tests and image builds in a component must pass before its images are pushed. A workspace run publishes each component as it completes; a later failure does not undo earlier pushes. This builds single-architecture images, unlike the CI multi-architecture manifests; choose a non-production tag to avoid replacing a published manifest. Published base images default to `felixpfeifer`; `MRP_BASE_NAMESPACE` changes configurable base-image owners, but several Dockerfiles hard-code their base image. The backend agent build requires the surrounding workspace and `core/cell_config`; SO-101 requires initialized submodules.

Local runs do not perform GitLab security templates, release or registry maintenance, scheduled jobs, manual hardware tests, or the optional real-backend browser and integration jobs. Camera manager runs its explicit Trivy and Hadolint checks; its image scan needs the default Docker socket. ROS interfaces uses its existing `make verify` (which clears previous generated `artifacts/`) and does not locally publish the protected ROS base-image pipeline. The GitLab pipelines remain authoritative for releases.

LeRobot uses `MRP_AI_BASE_IMAGE` when set. If its published CUDA or Jetson base is unavailable and the workspace contains `core/ros-interfaces`, the script builds the architecture-appropriate base locally; this requires a large NVIDIA image download.

Camera manager stores the Trivy vulnerability database in the Docker volume `mrp-local-ci-trivy-cache`, shared by its source and image scans.

Camera manager writes `trivy-source.json`, `trivy-image.json`, and `image-sbom.cdx.json` in its repository. Its image security gate fails on high or critical findings, including findings inherited from the ROS base.
