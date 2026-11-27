#!/bin/bash
set -euo pipefail

# Variants: cpu (ros image, amd64+arm64), cuda (amd64), jetson (Orin, arm64).
declare -A upstream=([cpu]="$ROS_BASE_UPSTREAM_IMAGE" [cuda]="$CUDA_BASE_UPSTREAM_IMAGE" [jetson]="$JETSON_BASE_UPSTREAM_IMAGE")
declare -A suffix=([cpu]="" [cuda]="-cuda" [jetson]="-jetson")
declare -A archs=([cpu]="amd64 arm64" [cuda]="amd64" [jetson]="arm64")
declare -A digest resolved

mkdir -p artifacts
rebuild=true
[[ "$CI_PIPELINE_SOURCE" == schedule && "${ROS_BASE_FORCE_REBUILD:-false}" != true ]] && rebuild=false

for variant in cpu cuda jetson; do
    skopeo inspect --raw "docker://${upstream[$variant]}" > "artifacts/ros-base-upstream-${variant}.json"
    digest[$variant]="sha256:$(sha256sum "artifacts/ros-base-upstream-${variant}.json" | cut -d ' ' -f 1)"
    resolved[$variant]="${upstream[$variant]%@*}@${digest[$variant]}"

    # Scheduled runs rebuild only when an upstream image changed or a published variant is missing/stale.
    if [[ "$rebuild" == false ]]; then
        for arch in ${archs[$variant]}; do
            metadata="artifacts/ros-base-${variant}-${arch}.json"
            if ! skopeo inspect --override-arch "$arch" "docker://docker.io/${DOCKERHUB_IMAGE}${suffix[$variant]}:jazzy" > "$metadata"; then
                rebuild=true
            elif ! jq --exit-status --arg digest "${digest[$variant]}" --arg revision "$CI_COMMIT_SHA" --arg arch "$arch" \
                '.Architecture == $arch and .Labels["platform.ros-base.digest"] == $digest and .Labels["org.opencontainers.image.revision"] == $revision' "$metadata" > /dev/null; then
                rebuild=true
            fi
        done
    fi
done

if [[ "$rebuild" == true ]]; then
    rolling=false
    if [[ "${CI_COMMIT_BRANCH:-}" == "$CI_DEFAULT_BRANCH" && -z "${CI_COMMIT_TAG:-}" ]]; then
        rolling=true
    fi
    jq --null-input --arg digest_cpu "${digest[cpu]}" --arg base_cpu "${resolved[cpu]}" \
        --arg digest_cuda "${digest[cuda]}" --arg base_cuda "${resolved[cuda]}" \
        --arg digest_jetson "${digest[jetson]}" --arg base_jetson "${resolved[jetson]}" \
        --arg revision "$CI_COMMIT_SHA" --arg release "${CI_COMMIT_TAG:-}" --arg rolling "$rolling" --arg image "$DOCKERHUB_IMAGE" \
        '{include: [{local: ".gitlab/ros-base-build.yml"}], variables: {DOCKERHUB_IMAGE: $image,
          ROS_BASE_IMAGE_cpu: $base_cpu, ROS_BASE_DIGEST_cpu: $digest_cpu,
          ROS_BASE_IMAGE_cuda: $base_cuda, ROS_BASE_DIGEST_cuda: $digest_cuda,
          ROS_BASE_IMAGE_jetson: $base_jetson, ROS_BASE_DIGEST_jetson: $digest_jetson,
          INTERFACE_REVISION: $revision, ROS_BASE_RELEASE_TAG: $release, ROS_BASE_PUBLISH_ROLLING: $rolling}}' \
        > artifacts/ros-base-child.yml
    printf 'Building interface revision %s on cpu/cuda/jetson bases\n' "$CI_COMMIT_SHA"
else
    jq --null-input --arg runner "$AMD64_RUNNER_TAG" \
        '{stages: ["check"], "ros-base:unchanged": {stage: "check", image: "quay.io/buildah/stable:v1.40.1", tags: [$runner], script: ["echo Published base images already match all variants; no rebuild needed"]}}' \
        > artifacts/ros-base-child.yml
    printf 'Published base images are current; skipping native builds.\n'
fi
