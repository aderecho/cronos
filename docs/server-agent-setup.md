# Install the Cronos reporting service on a Linux server

## 1. Make Cronos reachable

Deploy the Django backend behind HTTPS, for example `https://monitor.example.com`. Keep its MySQL database and Redis private. The frontend preview at `127.0.0.1:9100` is only on your Mac; another server's `127.0.0.1` refers to that server itself.

The monitored server needs outbound HTTPS access to your Cronos host and package repositories. No inbound agent port, SSH key, or server root password is added to Cronos. Run the Cronos worker and scheduler on the monitoring host so missing-heartbeat and application checks continue independently.

Download endpoints are served by Django and must pass through the same reverse proxy as `/api/`:

- `/api/v1/agent/install.sh`
- `/api/v1/agent/files/manifest.json`
- `/api/v1/agent/files/cronos_agent.py`
- `/api/v1/agent/files/requirements.txt`
- `/api/v1/agent/files/cronos-agent.service`

These endpoints contain public installation code only. Tokens are generated separately through authenticated server enrollment.

## 2. Register the target in Cronos

1. Sign in to the deployed Cronos application as an administrator.
2. Servers → Add server: enter a name and hostname/IP.
3. Configure filesystem paths (for example `/` and `/data`) and required systemd services (for example `nginx` and `mysql`). Use service names that actually exist on the target; RHEL may use `mysqld` or `mariadb` instead.
4. Optionally add an independent HTTP(S) or TCP probe to detect reachability separately from the agent.
5. Save, open the server, and choose Generate token. Copy that token. It belongs to this server only; generating another token revokes the previous one.

The server detail screen provides a Copy install command button with its configured filesystem/service names. Local previews show a domain placeholder that must be replaced with a deployed HTTPS hostname.

## 3. Run the wget installer on the target server

Supported initial targets: Ubuntu/Debian with apt-get, or RHEL-family systems with dnf, running systemd. Python 3.10+ is required. For Ubuntu 22.04+/Debian 12+ the installer installs the Python/venv dependencies; dnf targets use Python 3.11 packages. Unsupported distributions stop with an explanation.

Replace `YOUR-CRONOS-DOMAIN` with the actual backend hostname. Adjust filesystem/service names to match step 2:

```bash
# Ubuntu/Debian, only if wget is not installed:
sudo apt-get update
sudo apt-get install -y wget ca-certificates

wget --https-only --max-redirect=0 \
  -O install-cronos-agent.sh \
  'https://YOUR-CRONOS-DOMAIN/api/v1/agent/install.sh'

sudo bash install-cronos-agent.sh \
  --api-url 'https://YOUR-CRONOS-DOMAIN/api/v1' \
  --filesystems '/,/data' \
  --services 'nginx,mysql' \
  --interval 30
```

For a server that only needs its root filesystem and no required-service checks:

```bash
sudo bash install-cronos-agent.sh \
  --api-url 'https://YOUR-CRONOS-DOMAIN/api/v1' \
  --filesystems '/' \
  --services ''
```

Paste the token at the hidden prompt. The token is not part of the command, terminal history, or installer output.

The installer downloads and verifies package SHA-256 hashes over the configured HTTPS origin, installs Python dependencies, creates an unprivileged `cronos-agent` account, writes a root-owned configuration file, and enables/starts the `cronos-agent.service` systemd service. Files:

```text
/opt/cronos-agent/cronos_agent.py
/opt/cronos-agent/.venv/
/opt/cronos-agent/requirements.txt
/etc/cronos-agent.env                       root:root, mode 600
/etc/systemd/system/cronos-agent.service    root:root, mode 644
```

The service reads `/etc/cronos-agent.env` through systemd and sends telemetry every 30 seconds. The service user cannot modify its installed code or token file. Service startup does not itself prove that the backend accepted a report: verify receipt below.

## 4. Verify

```bash
sudo systemctl is-enabled cronos-agent
sudo systemctl status cronos-agent --no-pager
sudo journalctl -u cronos-agent -n 50 --no-pager
sudo journalctl -u cronos-agent -f
```

Look for **Telemetry accepted**, then confirm that Cronos → Servers → your server shows a recent **Last agent report** and populated resource metrics. Missing required measurements produce Unknown health; they are not treated as zero usage.

Reported data includes CPU/load, RAM/swap, filesystem space/inodes, disk I/O counters, network counters/rates, uptime, OS name, and the configured service states. Application URLs are checked independently by the Cronos worker; configure them under Applications.

Default alert behavior is below 50% for three fresh samples, or missing reports after 90 seconds for Agent offline. Independent probe failures determine the separate endpoint/server-unreachable incident. Live alerts require RabbitMQ, the Cronos ASGI notification gateway, and device registration. Browsers must remain open; the Android native monitoring service supports background/locked-screen alarms while connected.

## Maintenance and token rotation

```bash
sudo systemctl restart cronos-agent
sudo systemctl stop cronos-agent
sudo systemctl disable --now cronos-agent
```

To rotate a token or update installed agent files, generate a new token in Cronos and rerun the same installer. It replaces the environment file and restarts the existing service rather than creating another service. Match filesystem/service flags again on reruns; omitted flags use `/` and no required services.

For unattended installation, supply `--token-file /root/cronos-agent-token` instead of using the prompt. That file must be a root-owned regular file with mode 600. Provision its contents through your deployment secret manager; never put the token in shell arguments or commit it. Remove the staging token file after successful installation; the service retains its protected `/etc/cronos-agent.env`.

## Troubleshooting

- Download fails: verify DNS, HTTPS certificate, outbound firewall, and that the reverse proxy forwards `/api/v1/agent/` to Django. Redirects and invalid certificates are rejected.
- HTTP 401/403 in the journal: wrong/revoked token or retired server. Generate a new token for the correct target and rerun setup.
- HTTP 400: confirm system time synchronization, selected mount paths, and valid configuration. Samples older than 120 seconds or more than 30 seconds in the future are rejected.
- Unknown health: configured service names/mounts must match what the agent can read. Check that the service account can inspect required resources; don't change it to root just to hide a permission issue.
- Service active but no data: inspect its journal and confirm the API URL ends `/api/v1`, not the frontend URL or `/agent/telemetry`.
- Data stops while the monitored host is down: the separate Cronos scheduler detects missing reports. Host outages cannot be reported by an agent running on the failed host itself.

Download-only package validation (no root installation or token needed):

```bash
bash install-cronos-agent.sh --check \
  --api-url 'https://YOUR-CRONOS-DOMAIN/api/v1' \
  --filesystems '/' --services ''
```

For developer tests only, `--check --allow-local-http --api-url http://127.0.0.1:8100/api/v1` allows loopback HTTP. Remote installation always requires HTTPS.

## Validation boundary

Shell syntax, artifact distribution/checksums, tamper rejection, HTTPS URL validation, API tests, and the frontend enrollment UI are validated locally. This macOS workspace cannot execute a Linux systemd service; live installation/service reporting must still be verified on the target Linux server. No remote server was accessed or modified by creating this installer.
