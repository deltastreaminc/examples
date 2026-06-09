#!/usr/bin/env bash
set -euo pipefail

CLIENT_BIN="/Users/richardcurtis/deltastream/deltastreamv2/client/build/clientv2"
SERVER_URL="${DS_SERVER:-https://api.local.deltastream.io/v2}"
ORG_ID="${DS_ORG:-}"
API_TOKEN="${DS_API_TOKEN:-${DS_TOKEN:-}}"
DROP_DATABASE="${DROP_DATABASE:-false}"
DATABASE_NAME="${DATABASE_NAME:-stablecoin_payment_demo}"

if [[ ! -x "${CLIENT_BIN}" ]]; then
  echo "Error: client not executable at ${CLIENT_BIN}" >&2
  exit 1
fi

if [[ -z "${API_TOKEN}" ]]; then
  echo "Error: API token missing. Set DS_API_TOKEN (or DS_TOKEN)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEARDOWN_FILE="${ROOT_DIR}/dsql/99_teardown.sql"

if [[ ! -f "${TEARDOWN_FILE}" ]]; then
  echo "Error: teardown file missing at ${TEARDOWN_FILE}" >&2
  exit 1
fi

CLI_ARGS=(--server "${SERVER_URL}" --insecure --api-token "${API_TOKEN}")
if [[ -n "${ORG_ID}" ]]; then
  CLI_ARGS+=(--org "${ORG_ID}")
fi

echo "Listing stablecoin demo query versions..."
"${CLIENT_BIN}" "${CLI_ARGS[@]}" -c "SELECT id, name, version, current_state FROM deltastream.sys.\"queries\" WHERE name LIKE 'stablecoin_demo_%' LIMIT 100;" || true

echo "Running teardown SQL from ${TEARDOWN_FILE}"
teardown_failures=0
while IFS= read -r stmt; do
  trimmed="${stmt##[[:space:]]}"
  if [[ -z "${trimmed}" || "${trimmed}" == --* ]]; then
    continue
  fi

  echo "Executing: ${trimmed}"
  if ! output=$("${CLIENT_BIN}" "${CLI_ARGS[@]}" -c "${trimmed}" 2>&1); then
    if [[ "${output}" == *" not found"* ]]; then
      echo "Skipping missing resource for statement: ${trimmed}"
      continue
    fi

    echo "Warning: statement failed: ${trimmed}" >&2
    echo "${output}" >&2
    teardown_failures=$((teardown_failures + 1))
    continue
  fi

  echo "${output}"
done <"${TEARDOWN_FILE}"

if [[ "${DROP_DATABASE}" == "true" ]]; then
  echo "Dropping database ${DATABASE_NAME}"
  "${CLIENT_BIN}" "${CLI_ARGS[@]}" -c "DROP DATABASE ${DATABASE_NAME};" || {
    echo "Warning: DROP DATABASE ${DATABASE_NAME} failed" >&2
    teardown_failures=$((teardown_failures + 1))
  }
fi

if [[ ${teardown_failures} -gt 0 ]]; then
  echo "Teardown completed with ${teardown_failures} failed statements." >&2
  exit 1
fi

echo "Teardown completed."
