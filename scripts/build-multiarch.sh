#!/usr/bin/env bash
set -euo pipefail

# Build and optionally publish a manifest list for the two primary server
# architectures. Override IMAGE, TAG, PLATFORMS or BUILDER when needed.
IMAGE="${IMAGE:-uhub.service.ucloud.cn/openbayes_common/inferbench}"
TAG="${TAG:-v0.1.5}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
BUILDER="${BUILDER:-inferbench-multiarch}"
PUSH="${PUSH:-1}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FULL_IMAGE="${IMAGE}:${TAG}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

if ! docker buildx inspect "${BUILDER}" >/dev/null 2>&1; then
  docker buildx create --name "${BUILDER}" --driver docker-container --use
fi
docker buildx inspect "${BUILDER}" --bootstrap >/dev/null

# The local Docker image store cannot load a multi-platform manifest. A
# non-publishing run therefore validates the current host architecture only.
if [[ "${PUSH}" != "1" && "${PUSH}" != "true" ]]; then
  HOST_PLATFORM="$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')"
  PLATFORMS="${HOST_PLATFORM}"
  FULL_IMAGE="${IMAGE}:${TAG}-local"
fi

args=(
  buildx build
  --builder "${BUILDER}"
  --platform "${PLATFORMS}"
  --tag "${FULL_IMAGE}"
  --file "${ROOT_DIR}/Dockerfile"
  "${ROOT_DIR}"
)

if [[ "${PUSH}" == "1" || "${PUSH}" == "true" ]]; then
  args+=(--push)
else
  args+=(--load)
fi

echo "Building ${FULL_IMAGE} for ${PLATFORMS} (builder: ${BUILDER})"
docker "${args[@]}"

if [[ "${PUSH}" == "1" || "${PUSH}" == "true" ]]; then
  echo "Published multi-architecture image: ${FULL_IMAGE}"
else
  echo "Built locally (single loaded platform): ${FULL_IMAGE}"
fi
