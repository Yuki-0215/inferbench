#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="${PYTHON_BIN}"
elif [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

cd "${ROOT_DIR}"

echo "[verify] repository harness"
"${PYTHON_BIN}" scripts/check_repo_harness.py

echo "[verify] Python tests"
"${PYTHON_BIN}" -m pytest -q

if ! command -v node >/dev/null 2>&1; then
  echo "[verify] node is required for frontend syntax validation" >&2
  exit 1
fi

echo "[verify] frontend JavaScript syntax"
node --check inferbench/static/app.js

echo "[verify] Helm chart"
INFERBENCH_PYTHON="${PYTHON_BIN}" ./scripts/verify-helm.sh

echo "[verify] all checks passed"
