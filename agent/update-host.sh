#!/usr/bin/env bash
# Update internal AppGuard routing without changing agent credentials.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
[[ $# -eq 2 ]] || { echo 'Usage: sudo bash update-host.sh HOSTNAME IPV4' >&2; exit 1; }
command -v python3 >/dev/null
command -v curl >/dev/null
command -v systemctl >/dev/null
python3 - "$1" "$2" <<'PY'
import ipaddress, re, sys
host, address = sys.argv[1:]
if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', host):
    raise SystemExit('Invalid hostname')
ipaddress.IPv4Address(address)
PY
# Verify the intended origin and its certificate before modifying routing.
curl --fail --silent --show-error --connect-timeout 10 --max-time 20 \
  --resolve "$1:443:$2" "https://$1/api/v1/health/live"
python3 - "$1" "$2" <<'PY'
import datetime, pathlib, shutil, sys
host, address = sys.argv[1:]
path = pathlib.Path('/etc/hosts')
original = path.read_text()
lines = []
for line in original.splitlines():
    body, marker, comment = line.partition('#')
    fields = body.split()
    if len(fields) > 1 and any(v.lower() == host.lower() for v in fields[1:]):
        aliases = [v for v in fields[1:] if v.lower() != host.lower()]
        if aliases:
            lines.append(fields[0] + '\t' + ' '.join(aliases) + (' #' + comment if marker else ''))
        elif marker:
            lines.append('#' + comment)
    else:
        lines.append(line)
lines.append(address + '\t' + host)
updated = '\n'.join(lines) + '\n'
if updated != original:
    backup = pathlib.Path('/etc/hosts.cronos-backup.' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(path, backup)
    path.write_text(updated)
    print('\nBackup:', backup)
print('Configured:', address, host)
PY
curl --fail --silent --show-error --connect-timeout 10 --max-time 20 \
  "https://$1/api/v1/health/live"
systemctl restart cronos-agent
echo
echo 'Agent restarted. Confirm new Telemetry accepted entries:'
journalctl -u cronos-agent --since '1 minute ago' --no-pager -n 20
