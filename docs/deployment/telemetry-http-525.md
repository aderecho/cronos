# Troubleshooting stale Cronos telemetry: HTTP 525

Date: 23 October 2026  
Monitored server: ORS (`172.18.1.114`)  
AppGuard internal address: `172.18.1.93`  
Agent API URL: `https://appguard.upcebu.edu.ph/api/v1`

## Symptoms

Cronos displays **Unknown**, stale resource readings, and unknown required services even though the monitored server is running. In the supplied screenshot, ORS showed **Stale · 21h ago**.

The agent journal repeatedly reports:

```text
WARNING Telemetry rejected (HTTP 525)
```

This indicates failed delivery of monitoring data. It does not establish that ORS or its required services have stopped.

## Confirmed findings

User-supplied command output established:

| Check from ORS | Result |
| --- | --- |
| Configured agent destination | `https://appguard.upcebu.edu.ph/api/v1` |
| Public HTTPS health request through Cloudflare | HTTP 525 |
| Direct HTTPS request to `172.18.1.93`, preserving the hostname | HTTP 200, `{"status":"ok"}` |
| Origin certificate verification | Successful; certificate matches `appguard.upcebu.edu.ph` |

Cloudflare defines [HTTP 525](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-525/) as a failed TLS handshake between Cloudflare and the origin server. The direct internal test proves that AppGuard's HTTPS liveness endpoint was reachable from ORS at the time of the test. It does not prove authenticated telemetry ingestion or identify which part of the public origin path is misconfigured.

## 1. Inspect the agent on ORS

Run on the monitored server:

```bash
sudo systemctl status cronos-agent --no-pager -l
sudo journalctl -u cronos-agent -n 80 --no-pager
sudo awk '/^CRONOS_API_URL=/' /etc/cronos-agent.env
```

Do not print or share the full environment file: it contains the agent token.

## 2. Compare public and internal HTTPS routes

Run on ORS before adding the hosts override:

```bash
curl -v --connect-timeout 10 --max-time 20 \
  https://appguard.upcebu.edu.ph/api/v1/health/live

curl -v --connect-timeout 10 --max-time 20 \
  --resolve appguard.upcebu.edu.ph:443:172.18.1.93 \
  https://appguard.upcebu.edu.ph/api/v1/health/live
```

The second command connects directly to the internal address while retaining TLS hostname verification. Do not add `-k`. `ping` accepts an IP address or hostname, not a complete URL, and a successful ping does not verify HTTPS.

## 3. Route ORS to AppGuard internally

Use this workaround only on hosts that can reach AppGuard at `172.18.1.93`. It bypasses Cloudflare for this hostname on that machine and depends on the internal address remaining correct.

Check existing mappings, back up the file, and open it:

```bash
grep -n 'appguard.upcebu.edu.ph' /etc/hosts
sudo cp -p /etc/hosts "/etc/hosts.cronos-backup.$(date +%Y%m%d-%H%M%S)"
sudo nano /etc/hosts
```

Add the following line, or update an existing mapping for this hostname. Avoid duplicate or conflicting entries. Preserve localhost, ORS, and IPv6 entries.

```text
172.18.1.93 appguard.upcebu.edu.ph
```

In nano, press **Ctrl+O**, **Enter**, then **Ctrl+X**.

Keep the agent API URL as `https://appguard.upcebu.edu.ph/api/v1`; do not replace the hostname with the IP address.

## 4. Verify delivery

### Downloadable configuration helper

After deploying `agent/update-host.sh` and the updated backend artifact allowlist,
the helper is available through the existing fixed-name download endpoint.
On ORS, with the internal hosts mapping already available or public HTTPS repaired:

```bash
wget --https-only --max-redirect=0 --timeout=20 \
  -O update-cronos-host.sh \
  'https://appguard.upcebu.edu.ph/api/v1/agent/files/update-host.sh'
sudo bash update-cronos-host.sh appguard.upcebu.edu.ph 172.18.1.93
```

If public HTTPS still returns 525 and the hosts mapping is not yet present,
bootstrap the download using the verified internal TLS route:

```bash
curl --fail --show-error --connect-timeout 10 --max-time 20 \
  --resolve appguard.upcebu.edu.ph:443:172.18.1.93 \
  -o update-cronos-host.sh \
  'https://appguard.upcebu.edu.ph/api/v1/agent/files/update-host.sh'
sudo bash update-cronos-host.sh appguard.upcebu.edu.ph 172.18.1.93
```

The helper verifies origin HTTPS before editing, backs up `/etc/hosts`, replaces
only mappings for the requested hostname while preserving other aliases, checks
normal HTTPS resolution, and restarts `cronos-agent`. It does not change the
agent token or API URL. If a post-edit check fails, inspect the error and use the
printed backup for rollback; the helper does not automatically restore it.

Run on ORS:

```bash
getent ahostsv4 appguard.upcebu.edu.ph

curl --connect-timeout 10 --max-time 20 \
  https://appguard.upcebu.edu.ph/api/v1/health/live

sudo systemctl restart cronos-agent
sudo journalctl -u cronos-agent --since "2 minutes ago" --no-pager
```

Expected results:

- Hostname resolution includes `172.18.1.93`.
- The health endpoint returns `{"status":"ok"}`.
- New agent log entries show **Telemetry accepted**. Allow at least one reporting interval, normally 30 seconds; use `sudo journalctl -u cronos-agent -f` to watch subsequent reports and **Ctrl+C** to stop watching.
- Cronos shows a recent **Last agent report** and fresh metrics for ORS.

If required services remain unknown after fresh reports arrive, investigate their configured systemd names and agent visibility separately.

## 5. Repair and retest the public path

The hosts override does not repair Cloudflare access. On the AppGuard origin, inspect:

```bash
sudo nginx -t
sudo ss -ltnp 'sport = :443'
sudo tail -n 80 /var/log/nginx/error.log
```

Check that Cloudflare's configured origin destination and any NAT/port forwarding reach the intended AppGuard HTTPS listener. Inspect the certificate, TLS settings, and any intervening proxy or firewall against the actual failing route before changing them.

Retest public HTTPS from a machine without the hosts override. A successful request on ORS after the override tests the internal route only.

## Rollback

After the public path is verified, edit `/etc/hosts` on ORS and remove only the AppGuard mapping added for this workaround. If a prior mapping was changed, restore that mapping from the saved backup. Preserve unrelated entries.

Then run:

```bash
getent ahostsv4 appguard.upcebu.edu.ph
curl --connect-timeout 10 --max-time 20 \
  https://appguard.upcebu.edu.ph/api/v1/health/live
sudo systemctl restart cronos-agent
sudo journalctl -u cronos-agent --since "2 minutes ago" --no-pager
```

## Status at documentation time

Public HTTP 525 and successful direct internal HTTPS are confirmed by supplied output. Saving the hosts override, successful telemetry acceptance afterward, refreshed dashboard readings, and public-route recovery have not yet been confirmed.
