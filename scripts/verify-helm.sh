#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELM_BIN="${HELM_BIN:-helm}"
INFERBENCH_PYTHON="${INFERBENCH_PYTHON:-python3}"

if ! command -v "${HELM_BIN}" >/dev/null 2>&1; then
  echo "helm is required for chart validation" >&2
  exit 1
fi

SOURCE_VERSION="$(cd "${ROOT_DIR}" && "${INFERBENCH_PYTHON}" -c 'from inferbench import __version__; print(__version__)')"
IMAGE_TAG="v${SOURCE_VERSION}"
TASK_TMP_DIR="$(mktemp -d /tmp/inferbench-helm.XXXXXX)"
trap 'rm -rf -- "${TASK_TMP_DIR}"' EXIT
export KUBECONFIG="${TASK_TMP_DIR}/kubeconfig"
touch "${KUBECONFIG}"
chmod 600 "${KUBECONFIG}"

"${HELM_BIN}" lint "${ROOT_DIR}/charts/inferbench" --set-string image.tag="${IMAGE_TAG}"

"${HELM_BIN}" template inferbench "${ROOT_DIR}/charts/inferbench" \
  --namespace inferbench \
  --set-string image.tag="${IMAGE_TAG}" \
  >"${TASK_TMP_DIR}/default.yaml"

grep -q 'type: Recreate' "${TASK_TMP_DIR}/default.yaml"
grep -q 'helm.sh/resource-policy: keep' "${TASK_TMP_DIR}/default.yaml"
grep -q "inferbench:${IMAGE_TAG}" "${TASK_TMP_DIR}/default.yaml"

"${HELM_BIN}" template inferbench "${ROOT_DIR}/charts/inferbench" \
  --namespace inferbench \
  --set-string image.tag="${IMAGE_TAG}" \
  --set persistence.existingClaim=inferbench-data \
  --set volumePermissions.enabled=true \
  --set apiKey.existingSecret=inferbench-api \
  --set 'imagePullSecrets[0].name=uhub-credentials' \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set 'ingress.hosts[0].host=bench.example.com' \
  --set 'ingress.hosts[0].paths[0].path=/' \
  --set 'ingress.hosts[0].paths[0].pathType=Prefix' \
  >"${TASK_TMP_DIR}/configured.yaml"

grep -q 'claimName: inferbench-data' "${TASK_TMP_DIR}/configured.yaml"
grep -q 'secretKeyRef:' "${TASK_TMP_DIR}/configured.yaml"
grep -q 'name: uhub-credentials' "${TASK_TMP_DIR}/configured.yaml"
grep -q 'ingressClassName: nginx' "${TASK_TMP_DIR}/configured.yaml"
grep -q 'name: volume-permissions' "${TASK_TMP_DIR}/configured.yaml"

if "${HELM_BIN}" template inferbench "${ROOT_DIR}/charts/inferbench" \
  >"${TASK_TMP_DIR}/missing-tag.log" 2>&1; then
  echo "chart unexpectedly accepted an empty image tag" >&2
  exit 1
fi
grep -q 'image.tag' "${TASK_TMP_DIR}/missing-tag.log"

if "${HELM_BIN}" template inferbench "${ROOT_DIR}/charts/inferbench" \
  --set-string image.tag="${IMAGE_TAG}" \
  --set replicaCount=2 \
  >"${TASK_TMP_DIR}/replicas.log" 2>&1; then
  echo "chart unexpectedly accepted multiple SQLite writers" >&2
  exit 1
fi
grep -q 'replicaCount' "${TASK_TMP_DIR}/replicas.log"

"${HELM_BIN}" template inferbench "${ROOT_DIR}/charts/inferbench" \
  --set-string image.tag="${IMAGE_TAG}" \
  --set persistence.enabled=false \
  >"${TASK_TMP_DIR}/ephemeral.yaml"
grep -Fq 'emptyDir: {}' "${TASK_TMP_DIR}/ephemeral.yaml"
if grep -q 'kind: PersistentVolumeClaim' "${TASK_TMP_DIR}/ephemeral.yaml"; then
  echo "ephemeral mode unexpectedly rendered a PVC" >&2
  exit 1
fi

if "${HELM_BIN}" template inferbench "${ROOT_DIR}/charts/inferbench" \
  --set-string image.tag="${IMAGE_TAG}" \
  --set-string apiKey.value=plaintext-secret \
  >"${TASK_TMP_DIR}/plaintext-secret.log" 2>&1; then
  echo "chart unexpectedly accepted a plaintext API Key value" >&2
  exit 1
fi
grep -Eq "Additional property value is not allowed|additional properties 'value' not allowed" \
  "${TASK_TMP_DIR}/plaintext-secret.log"

echo "[helm] lint, default render, configured render and guardrails passed"
