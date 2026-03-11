#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run with sudo: sudo bash scripts/install_cloudflared_healthcheck.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CLOUDFLARED_PLIST="/Library/LaunchDaemons/com.cloudflare.cloudflared.plist"
HEALTHCHECK_PLIST_SRC="${PROJECT_ROOT}/deploy/launchd/com.cloudflare.cloudflared.healthcheck.plist"
HEALTHCHECK_PLIST_DST="/Library/LaunchDaemons/com.cloudflare.cloudflared.healthcheck.plist"
HEALTHCHECK_SCRIPT="${PROJECT_ROOT}/scripts/cloudflared_healthcheck.sh"

if [[ ! -f "${CLOUDFLARED_PLIST}" ]]; then
  echo "Missing ${CLOUDFLARED_PLIST}" >&2
  exit 1
fi

if [[ ! -f "${HEALTHCHECK_PLIST_SRC}" ]]; then
  echo "Missing ${HEALTHCHECK_PLIST_SRC}" >&2
  exit 1
fi

if [[ ! -f "${HEALTHCHECK_SCRIPT}" ]]; then
  echo "Missing ${HEALTHCHECK_SCRIPT}" >&2
  exit 1
fi

backup_path="${CLOUDFLARED_PLIST}.bak.$(date +%Y%m%d%H%M%S)"
cp "${CLOUDFLARED_PLIST}" "${backup_path}"

tmp_plist="$(mktemp)"
/usr/bin/python3 - "${CLOUDFLARED_PLIST}" "${tmp_plist}" <<'PY'
import plistlib
import sys

src = sys.argv[1]
dst = sys.argv[2]

with open(src, "rb") as f:
    data = plistlib.load(f)

args = list(data.get("ProgramArguments") or [])
if "--protocol" in args:
    i = args.index("--protocol")
    if i + 1 < len(args):
        args[i + 1] = "auto"
    else:
        args.append("auto")
else:
    args.extend(["--protocol", "auto"])

data["ProgramArguments"] = args

with open(dst, "wb") as f:
    plistlib.dump(data, f, sort_keys=False)
PY

install -m 644 "${tmp_plist}" "${CLOUDFLARED_PLIST}"
chown root:wheel "${CLOUDFLARED_PLIST}"
rm -f "${tmp_plist}"

chmod 755 "${HEALTHCHECK_SCRIPT}"
install -m 644 "${HEALTHCHECK_PLIST_SRC}" "${HEALTHCHECK_PLIST_DST}"
chown root:wheel "${HEALTHCHECK_PLIST_DST}"

launchctl bootout "system/com.cloudflare.cloudflared" >/dev/null 2>&1 || true
launchctl enable "system/com.cloudflare.cloudflared" >/dev/null 2>&1 || true
launchctl bootstrap system "${CLOUDFLARED_PLIST}"
launchctl kickstart -k "system/com.cloudflare.cloudflared"

launchctl bootout "system/com.cloudflare.cloudflared.healthcheck" >/dev/null 2>&1 || true
launchctl enable "system/com.cloudflare.cloudflared.healthcheck" >/dev/null 2>&1 || true
launchctl bootstrap system "${HEALTHCHECK_PLIST_DST}"
launchctl kickstart -k "system/com.cloudflare.cloudflared.healthcheck"

echo "Applied cloudflared protocol=auto and installed healthcheck."
echo "Backup: ${backup_path}"
launchctl print system/com.cloudflare.cloudflared | awk '/state =|pid =|last exit code|last terminating signal/ {print}'
launchctl print system/com.cloudflare.cloudflared.healthcheck | awk '/state =|pid =|last exit code|last terminating signal/ {print}'

