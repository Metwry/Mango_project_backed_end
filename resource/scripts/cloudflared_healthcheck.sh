#!/usr/bin/env bash
set -euo pipefail

LABEL="${CLOUDFLARED_LABEL:-system/com.cloudflare.cloudflared}"
METRICS_URL="${CLOUDFLARED_METRICS_URL:-http://127.0.0.1:20241/metrics}"
TIMEOUT_SECONDS="${CLOUDFLARED_CHECK_TIMEOUT_SECONDS:-2}"
LOCK_FILE="${CLOUDFLARED_HEALTHCHECK_LOCK_FILE:-/tmp/cloudflared-healthcheck.lock}"
STATE_FILE="${CLOUDFLARED_HEALTHCHECK_STATE_FILE:-/tmp/cloudflared-healthcheck.state}"
MIN_HA_CONNECTIONS="${CLOUDFLARED_MIN_HA_CONNECTIONS:-1}"
FAIL_THRESHOLD="${CLOUDFLARED_FAIL_THRESHOLD:-2}"

exec 9>"${LOCK_FILE}"
if command -v flock >/dev/null 2>&1; then
  flock -n 9 || exit 0
fi

job_dump="$(launchctl print "${LABEL}" 2>/dev/null || true)"
state="$(printf "%s\n" "${job_dump}" | awk -F' = ' '/^[[:space:]]*state =/{print $2; exit}')"
pid="$(printf "%s\n" "${job_dump}" | awk -F' = ' '/^[[:space:]]*pid =/{print $2; exit}')"

need_restart=0
reason=""
metrics_text=""
ha_connections=""
if [[ "${state}" != "running" ]]; then
  need_restart=1
  reason="job_state_${state:-unknown}"
elif [[ -z "${pid}" || "${pid}" == "0" ]]; then
  need_restart=1
  reason="missing_pid"
else
  metrics_text="$(curl -fsS --max-time "${TIMEOUT_SECONDS}" "${METRICS_URL}" 2>/dev/null || true)"
  if [[ -z "${metrics_text}" ]]; then
    need_restart=1
    reason="metrics_unreachable"
  else
    ha_connections="$(
      printf "%s\n" "${metrics_text}" |
      awk '/^cloudflared_tunnel_ha_connections[[:space:]]/{print $2; exit}'
    )"
    if [[ -z "${ha_connections}" ]]; then
      need_restart=1
      reason="metrics_missing_ha_connections"
    elif ! awk -v c="${ha_connections}" -v m="${MIN_HA_CONNECTIONS}" 'BEGIN { exit !(c+0 >= m+0) }'; then
      need_restart=1
      reason="ha_connections_low_${ha_connections}"
    fi
  fi
fi

fail_count=0
if [[ -f "${STATE_FILE}" ]]; then
  fail_count="$(cat "${STATE_FILE}" 2>/dev/null || echo 0)"
fi
if [[ ! "${fail_count}" =~ ^[0-9]+$ ]]; then
  fail_count=0
fi

if [[ "${need_restart}" == "1" ]]; then
  fail_count=$((fail_count + 1))
  echo "${fail_count}" > "${STATE_FILE}"
  if (( fail_count >= FAIL_THRESHOLD )); then
    launchctl kickstart -k "${LABEL}" >/dev/null 2>&1 || true
    echo 0 > "${STATE_FILE}"
    printf "[%s] restarted %s reason=%s fail_count=%s threshold=%s\n" \
      "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${LABEL}" "${reason}" "${fail_count}" "${FAIL_THRESHOLD}" >&2
  fi
else
  if [[ "${fail_count}" != "0" ]]; then
    echo 0 > "${STATE_FILE}"
  fi
fi
