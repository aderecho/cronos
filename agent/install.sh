#!/usr/bin/env bash
# Cronos Linux/systemd installer. Run from a downloaded file, never with a token in argv.
set +x
set -euo pipefail
umask 077
API_URL=''
FILESYSTEMS='/'
SERVICES=''
INTERVAL='30'
TOKEN_FILE=''
CHECK_ONLY=false
ALLOW_LOCAL_HTTP=false
STAGE=''
cleanup() { [[ -z "$STAGE" ]] || rm -rf -- "$STAGE"; }
trap cleanup EXIT
fail() { printf 'Cronos: %s\n' "$*" >&2; exit 1; }
usage() {
  cat <<'HELP'
Usage: sudo bash install-cronos-agent.sh --api-url https://monitor.example.com/api/v1 [options]
  --filesystems /,/data       Selected mounts; match the server settings in Cronos
  --services nginx,mysql      Required systemd services; match the server settings
  --interval 30               Seconds between reports (minimum 10)
  --token-file /root/token    Read a token from a root-owned mode-600 regular file
  --check                    Download and validate the package without installing
  --allow-local-http         Development only: permit HTTP on 127.0.0.1/localhost
  --help                     Show this help
Without --token-file, the installer securely prompts for the enrollment token.
Supported install targets: Linux with systemd, Python 3.10+, apt-get or dnf.
HELP
}
while (($#)); do
  case "$1" in
    --api-url|--filesystems|--services|--interval|--token-file)
      (($# >= 2)) || fail "Missing value for $1"
      case "$1" in
        --api-url) API_URL="${2%/}";;
        --filesystems) FILESYSTEMS="$2";;
        --services) SERVICES="$2";;
        --interval) INTERVAL="$2";;
        --token-file) TOKEN_FILE="$2";;
      esac
      shift 2;;
    --check) CHECK_ONLY=true; shift;;
    --allow-local-http) ALLOW_LOCAL_HTTP=true; shift;;
    --help|-h) usage; exit 0;;
    *) fail "Unknown option: $1";;
  esac
done
[[ -n "$API_URL" ]] || { usage; fail 'An API URL is required.'; }
# Validate the URL before passing it to wget or any privileged operation.
if [[ "$API_URL" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?/api/v1$ ]]; then
  :
elif $ALLOW_LOCAL_HTTP && [[ "$API_URL" =~ ^http://(127\.0\.0\.1|localhost)(:[0-9]+)?/api/v1$ ]]; then
  :
else
  fail 'Use https://YOUR-CRONOS-HOST/api/v1 without credentials, query parameters, or fragments.'
fi
[[ "$INTERVAL" =~ ^[0-9]{1,4}$ ]] && ((10#$INTERVAL >= 10 && 10#$INTERVAL <= 3600)) || fail 'Interval must be 10–3600 seconds.'
if ! $CHECK_ONLY; then
  [[ "$(uname -s)" == Linux ]] || fail 'Installation requires Linux.'
  [[ $EUID -eq 0 ]] || fail 'Run this installer with sudo.'
  command -v systemctl >/dev/null || fail 'systemd is required.'
  [[ -d /run/systemd/system ]] || fail 'systemd must be the running service manager.'
fi
command -v wget >/dev/null || fail 'Install wget first (for example: sudo apt-get install wget).'
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/cronos-agent.XXXXXXXX")"
fetch() {
  local url="$1" destination="$2"
  if [[ "$url" == https://* ]]; then
    wget --quiet --https-only --max-redirect=0 --timeout=30 --tries=3 -O "$destination" "$url" || fail 'Package download failed. Check the Cronos URL, DNS, TLS certificate, and firewall.'
  else
    wget --quiet --max-redirect=0 --timeout=30 --tries=3 -O "$destination" "$url" || fail 'Local package download failed.'
  fi
}
fetch "$API_URL/agent/files/manifest.json" "$STAGE/manifest.json"
for artifact in cronos_agent.py requirements.txt cronos-agent.service; do
  fetch "$API_URL/agent/files/$artifact" "$STAGE/$artifact"
done
if ! $CHECK_ONLY; then
  if command -v apt-get >/dev/null; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip python3-dev build-essential ca-certificates
  elif command -v dnf >/dev/null; then
    dnf install -y python3.11 python3.11-pip python3.11-devel gcc ca-certificates
  else
    fail 'Supported automatic dependency installation requires apt-get or dnf.'
  fi
fi
PYTHON=''
for candidate in python3 python3.12 python3.11 python3.10; do
  if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,10))' 2>/dev/null; then
    PYTHON="$candidate"; break
  fi
done
[[ -n "$PYTHON" ]] || fail 'Python 3.10 or newer is required.'
"$PYTHON" - "$STAGE" "$FILESYSTEMS" "$SERVICES" <<'PY'
import hashlib, json, pathlib, re, sys
stage=pathlib.Path(sys.argv[1])
manifest=json.loads((stage/'manifest.json').read_text())
for name in ['cronos_agent.py','requirements.txt','cronos-agent.service']:
    actual=hashlib.sha256((stage/name).read_bytes()).hexdigest()
    if actual != manifest.get('files',{}).get(name):
        raise SystemExit('Cronos: package checksum mismatch. Download the installer again.')
compile((stage/'cronos_agent.py').read_text(), 'cronos_agent.py', 'exec')
mounts=sys.argv[2].split(',')
services=[s for s in sys.argv[3].split(',') if s]
if len(mounts)>32 or any(not m.startswith('/') or len(m)>200 or any(ord(c)<32 for c in m) for m in mounts) or len(set(mounts))!=len(mounts):
    raise SystemExit('Cronos: use up to 32 unique absolute filesystem paths, comma-separated.')
if len(services)>32 or any(not re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}',s) for s in services) or len(set(services))!=len(services):
    raise SystemExit('Cronos: use up to 32 unique systemd service names, comma-separated.')
print('Cronos: package checksums and configuration validated.')
PY
if $CHECK_ONLY; then
  printf 'Cronos: check complete. No packages, users, files, or services were installed.\n'
  exit 0
fi
TOKEN=''
if [[ -n "$TOKEN_FILE" ]]; then
  "$PYTHON" - "$TOKEN_FILE" <<'PY'
import os, stat, sys
p=sys.argv[1]
s=os.lstat(p)
if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or stat.S_IMODE(s.st_mode)!=0o600:
    raise SystemExit('Cronos: token file must be a root-owned regular file with mode 600.')
PY
  TOKEN="$(cat -- "$TOKEN_FILE")"
else
  [[ -r /dev/tty ]] || fail 'No terminal available. Use --token-file with a root-owned mode-600 file.'
  read -r -s -p 'Paste the server enrollment token from Cronos: ' TOKEN </dev/tty
  printf '\n'
fi
[[ "$TOKEN" =~ ^[A-Za-z0-9_-]{32,256}$ ]] || fail 'Invalid token format. Generate a server enrollment token in Cronos.'
# Secret input goes through stdin rather than process arguments or logs.
printf '%s' "$TOKEN" | "$PYTHON" -c '
import json,sys,pathlib
value=sys.stdin.read()
path=pathlib.Path(sys.argv[1]);path.write_text("CRONOS_AGENT_TOKEN="+json.dumps(value)+"\n");path.chmod(0o600)
' "$STAGE/agent.env"
unset TOKEN
"$PYTHON" - "$STAGE/agent.env" "$API_URL" "$FILESYSTEMS" "$SERVICES" "$INTERVAL" "$ALLOW_LOCAL_HTTP" <<'PY'
import json,sys
values=dict(zip(['CRONOS_API_URL','CRONOS_FILESYSTEMS','CRONOS_SERVICES','CRONOS_INTERVAL','CRONOS_ALLOW_LOCAL_HTTP'],sys.argv[2:]))
with open(sys.argv[1],'a') as f:
    for name,value in values.items(): f.write(name+'='+json.dumps(value,ensure_ascii=False)+'\n')
PY
if ! getent group cronos-agent >/dev/null; then groupadd --system cronos-agent; fi
if ! id cronos-agent >/dev/null 2>&1; then
  NOLOGIN="$(command -v nologin || printf '/usr/sbin/nologin')"
  useradd --system --gid cronos-agent --home-dir /nonexistent --no-create-home --shell "$NOLOGIN" cronos-agent
fi
install -d -o root -g root -m 0755 /opt/cronos-agent
umask 022
"$PYTHON" -m venv /opt/cronos-agent/.venv
/opt/cronos-agent/.venv/bin/python -m pip install --disable-pip-version-check -r "$STAGE/requirements.txt"
umask 077
install -o root -g root -m 0644 "$STAGE/cronos_agent.py" /opt/cronos-agent/cronos_agent.py
install -o root -g root -m 0644 "$STAGE/requirements.txt" /opt/cronos-agent/requirements.txt
install -o root -g root -m 0600 "$STAGE/agent.env" /etc/cronos-agent.env
install -o root -g root -m 0644 "$STAGE/cronos-agent.service" /etc/systemd/system/cronos-agent.service
systemctl daemon-reload
systemctl enable cronos-agent.service
systemctl restart cronos-agent.service
systemctl is-active --quiet cronos-agent.service || fail 'Service did not start. Check: sudo journalctl -u cronos-agent -n 50 --no-pager'
printf '\nCronos agent service started; reports are sent every %s seconds.\n' "$INTERVAL"
printf 'Confirm receipt in Cronos → Servers → your server → Last agent report.\n'
printf 'View logs: sudo journalctl -u cronos-agent -f\n'
printf 'Service status: sudo systemctl status cronos-agent --no-pager\n'
