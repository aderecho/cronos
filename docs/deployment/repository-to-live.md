# Cronos Repository to Go Live Deployment Guide

Follow these steps in order on Ubuntu 24.04 LTS. Nginx terminates HTTPS, serves the frontend and forwards API and WebSocket traffic to Docker Compose. The production hostname and repository URL below are placeholders; replace them before executing commands. Run each block separately and stop if a command fails.

## 1. Prepare the repository domain and access

Before connecting to the server, confirm the remote repository contains the complete application, including compose.yaml, backend/Dockerfile, backend/requirements.txt, frontend/package-lock.json, .env.example and docs/deployment/nginx.conf.example. A Git clone downloads only committed and pushed files. The current local checkout has no configured Git remote; obtain your actual repository URL and push the intended source before cloning. Never commit .env, credentials, .runtime, database files or signing keys.

Set a public DNS A record for monitor.example.com to your server IPv4 address. Replace monitor.example.com throughout this document. Remove an incorrect AAAA record or configure IPv6 before requesting TLS. Keep SSH access and permit public TCP 80 and 443. Keep MySQL, Redis, RabbitMQ and the application port private. This guide assumes direct public Nginx rather than a separate load balancer.

Have ready: repository URL, deployed branch, DNS domain, server SSH access, sudo access for aoderecho and an off-server backup destination. Public repository cloning can use HTTPS; for a private repository, use a read-only SSH deploy key and your Git provider's documented host-key verification. Do not embed access tokens into clone URLs.

## 2. Prepare the server account and packages

Run this first block in the current root server shell, such as root@cronus. It does not assume /opt/cronos already exists.

```bash
cat /etc/os-release
id aoderecho
apt update
apt install -y sudo git nginx certbot ca-certificates curl openssl
install -d -o aoderecho -g aoderecho -m 755 /opt/cronos
systemctl enable --now nginx
su - aoderecho
```

All remaining server commands run as aoderecho unless explicitly stated otherwise. Confirm sudo works. If sudo access is missing, configure it using the server's administrative policy from the root session before continuing.

```bash
whoami
sudo -v
sudo nginx -T
sudo ss -lntp
df -h
```

Expected account: aoderecho. Inspect existing Nginx sites and occupied ports before changing them. Preserve the actual SSH port when adjusting UFW or cloud firewall rules. Do not enable a new firewall blindly over an SSH session.

## 3. Install Docker Engine and Compose

If Docker is already installed, inspect its source and version before replacing packages. Do not remove packages or existing container data on a shared host. For a fresh Ubuntu server, install from Docker's official Apt repository:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' "${UBUNTU_CODENAME:-$VERSION_CODENAME}" "$(dpkg --print-architecture)" | sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker compose version
sudo docker run --rm hello-world
```

Expected: Compose version is printed and hello-world completes successfully. This guide uses sudo docker consistently, so Docker group membership is unnecessary. Docker-published ports can bypass UFW; retain Compose's loopback-only API mapping and no public data-service ports. Reference: https://docs.docker.com/engine/install/ubuntu/

## 4. Clone the repository into the application directory

Replace the example URL with your actual repository. Replace main if the deployment branch differs. The directory was created in step 2 and must be empty for this first clone.

```bash
CRONOS_REPO='https://github.com/YOUR-ORGANIZATION/YOUR-REPOSITORY.git'
CRONOS_BRANCH='main'
git clone --branch "$CRONOS_BRANCH" "$CRONOS_REPO" /opt/cronos
cd /opt/cronos
git status --short
git rev-parse HEAD
ls -l compose.yaml .env.example backend/Dockerfile backend/requirements.txt frontend/package-lock.json
```

Expected: all five files exist and git status shows no local changes. Record the revision printed by git rev-parse HEAD. If Git reports authentication failure, configure repository access first. If the directory already contains a checkout, inspect git -C /opt/cronos status and its remote; do not clone over or delete it. If /opt/cronos does not exist, return to step 2 rather than starting with cd.

## 5. Install the application and secrets

The clone is now present. Create production configuration once; do not overwrite an existing production .env during later updates:

```bash
cd /opt/cronos
umask 077
cp .env.example .env
mkdir -p secrets
chmod 700 secrets
chmod 600 .env
```

Run nano .env or your preferred editor to edit .env securely. Install nano with sudo apt install nano if needed. Run openssl rand -hex 32 four times, and paste each distinct generated value into `DJANGO_SECRET_KEY`, `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD` and `RABBITMQ_DEFAULT_PASS`. Hexadecimal passwords avoid URL interpolation problems in the Compose AMQP URL. Generate a Fernet encryption key without putting a real secret into shell history:

```bash
sudo docker run --rm python:3.12-slim sh -c 'pip install --quiet cryptography && python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
```

Put that value in `DEVICE_ENCRYPTION_KEY`. Preserve this key with backups: changing it prevents decryption of stored device credentials. Do not regenerate any existing production key during routine updates.

Required production values:

```dotenv
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=monitor.example.com
TRUST_PROXY=true
CORS_ALLOWED_ORIGINS=https://monitor.example.com,https://localhost
CRONOS_DEMO_MODE=false
MYSQL_DATABASE=cronos
MYSQL_USER=cronos
MYSQL_HOST=mysql
MYSQL_PORT=3306
REDIS_URL=redis://redis:6379/0
RABBITMQ_DEFAULT_USER=cronos
RABBITMQ_DEFAULT_VHOST=cronos
RABBITMQ_EXCHANGE=cronos.notifications
PROBE_DENIED_HOSTS=localhost,metadata.google.internal,metadata,monitor.example.com
PROBE_ALLOWED_CIDRS=
```

Also fill the generated secret fields from `.env.example`. Set `RABBITMQ_URL=amqp://cronos:YOUR_GENERATED_HEX_PASSWORD@rabbitmq:5672/cronos`, matching `RABBITMQ_DEFAULT_PASS`; Compose overrides this URL for API/worker from the initialization variables. Non-URL-safe credentials/vhost names require appropriate URL encoding and Compose changes. Restrict `PROBE_ALLOWED_CIDRS` to the private networks you explicitly intend to monitor; leave it empty if none. Never use `0.0.0.0/0` merely to bypass probe restrictions.

`TRUST_PROXY=true` is appropriate here because API access is limited to loopback and Nginx overwrites the forwarding headers. Keep `https://localhost` in CORS for the Capacitor Android app. Do not use wildcard hosts/origins. The scheduler must run only once.


## 6. Build, migrate and start services

```bash
cd /opt/cronos
sudo docker compose config --quiet
sudo docker compose build
sudo docker compose up -d mysql redis rabbitmq
sudo docker compose run --rm api python manage.py migrate --noinput
sudo docker compose run --rm api python manage.py check
sudo docker compose run --rm api python manage.py createsuperuser
sudo docker compose up -d api worker scheduler
sudo docker compose ps
sudo docker compose logs --tail=100 api worker scheduler
```

Do not run `seed_demo` or enable demo login in production. Initialization passwords apply to new MySQL/RabbitMQ volumes; changing `.env` does not rotate existing database/broker users. Rotate those using their respective administration tools and coordinate application restarts.

Collect Django admin static assets and copy them to a host directory readable by Nginx:

```bash
sudo docker compose exec api python manage.py collectstatic --noinput
sudo install -d -m 755 /var/www/cronos-static
sudo docker compose cp api:/app/staticfiles/. /var/www/cronos-static/
sudo chmod -R a+rX /var/www/cronos-static
```

Build the frontend with the Node version pinned by the project using a temporary container. Node does not need to be installed on the host. This command runs as aoderecho's UID and writes only build files in the checkout:

```bash
cd /opt/cronos
sudo docker run --rm --user "$(id -u):$(id -g)" \
  -e npm_config_cache=/tmp/npm-cache \
  -e VITE_API_URL=https://monitor.example.com/api/v1 \
  -e VITE_ALLOW_LOCAL_HTTP=false \
  -v "$PWD/frontend:/work" -w /work \
  node:24.11.1-bookworm sh -c 'npm ci && npm run build'
sudo install -d -m 755 /var/www/cronos-web
sudo cp -a frontend/dist/. /var/www/cronos-web/
sudo chmod -R a+rX /var/www/cronos-web
```

Expected: frontend/dist/index.html exists, the build succeeds and static assets are copied. Change the HTTPS domain before the build; runtime .env changes do not change compiled frontend URLs.

Do not run Vite's development server on production. Only copy `dist` to the public document root, never the application checkout or `.env`.


## 7. Bootstrap HTTPS

First create an HTTP-only site so Certbot can validate the domain. This avoids referencing certificate paths before a certificate exists:

```bash
sudo install -d -m 755 /var/www/letsencrypt
sudo tee /etc/nginx/sites-available/cronos >/dev/null <<'NGINX'
server {
    listen 80;
    server_name monitor.example.com;
    location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; }
    location / { return 404; }
}
NGINX
sudo ln -s /etc/nginx/sites-available/cronos /etc/nginx/sites-enabled/cronos
sudo nginx -t
sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/letsencrypt -d monitor.example.com
```

Use the real domain in the heredoc and Certbot command. If the symlink already exists, inspect it rather than recreating it. Remove a conflicting default site only after confirming it is unused. DNS and public port 80 must work for this validation method.

Copy the complete production template, edit its domain/certificate paths, and activate it:

```bash
sudo cp /etc/nginx/sites-available/cronos /etc/nginx/sites-available/cronos.http-backup
sudo cp /opt/cronos/docs/deployment/nginx.conf.example /etc/nginx/sites-available/cronos
sudoedit /etc/nginx/sites-available/cronos
sudo nginx -t
sudo systemctl reload nginx
sudo certbot renew --dry-run
```

Ensure Nginx reloads after certificate renewal:

```bash
sudo install -d /etc/letsencrypt/renewal-hooks/deploy
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx >/dev/null <<'SH'
#!/bin/sh
nginx -t && systemctl reload nginx
SH
sudo chmod 755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
```

The template forwards `Upgrade` and `Connection` for the exact WebSocket route and preserves the URI in `proxy_pass`, following [Nginx WebSocket guidance](https://nginx.org/en/docs/http/websocket.html). The 90-second timeout permits gateway pings. It serves Django static assets separately from the Vue frontend.


## 8. Acceptance checks

Run on the server:

```bash
cd /opt/cronos
curl -fsS -H 'Host: monitor.example.com' http://127.0.0.1:8100/api/v1/health/live
curl -fsS https://monitor.example.com/api/v1/health/live
curl -fsS https://monitor.example.com/api/v1/health/ready
curl -I https://monitor.example.com/
curl -I https://monitor.example.com/static/admin/css/base.css
sudo ss -lntp
sudo docker compose exec api python manage.py check --deploy
sudo docker compose logs --tail=100 api worker scheduler
```

Readiness includes database, Redis and recent monitor heartbeat; allow one scheduler cycle after startup. It does not prove RabbitMQ forwarding or audible delivery. Review `check --deploy` warnings in context: Nginx handles HTTPS redirect in this topology; HSTS should only be enabled after HTTPS and all required subdomains are confirmed. Do not suppress warnings blindly.

In a browser, sign in with the new account, create a monitored target, assign users/roles, register notifications in Settings and wait for **connected**. Send a test notification. Inspect browser Network for WebSocket status **101** on `/api/v1/realtime/ws` and a ready message after authentication. Do not put device credentials into URLs, shell history or screenshots.

For the Android phone/tablet:

1. Install a signed production APK built/configured for `https://monitor.example.com/api/v1`. The existing `output/cronos-debug.apk` defaults to workstation loopback and USB forwarding; do not distribute that build as production.
2. Sign in, register the device, allow notification permission, enable monitoring and select **Allow background alarms**. Approve the Android battery exemption and verify connected status.
3. Send a test while open, then with the screen locked. Confirm both notification and actual alarm sound at the tablet's alarm volume; use Stop alarm afterward.
4. With an enabled QA target that has previously reported a heartbeat, stop its agent. Agent offline opens after 90 seconds plus up to 30 seconds for evaluation and 15 seconds for dispatch under healthy scheduling. Confirm the native alarm. Retire the QA target after testing.
5. Repeat after a reconnect and prolonged idle on the actual deployment network. Local test successes do not guarantee every vendor's battery policy. Reopen Cronos after force-stop/reboot. Continuous monitoring needs a live network and uses additional battery.

For an Android build machine with SDK/JDK configured, an HTTPS debug validation build can be made with:

```bash
VITE_API_URL=https://monitor.example.com/api/v1 ./scripts/android-build.sh
```

That helper still produces a **debug** APK. Release keystore creation, signing, secure keystore backup and distribution are separate release steps; do not call its output signed production software. Production devices must not depend on `adb reverse`.

Register monitored servers through the Servers UI and use its generated agent installation command; see the agent guide linked from the project README. Keep per-server enrollment credentials private. Maintenance suppresses notifications, and disabled/retired targets are not monitored.


Go live only when the public homepage loads, sign-in succeeds, readiness is healthy, the authenticated WebSocket connects and the actual phone/tablet alarms with the screen locked. Check that no database, broker, Redis or API ports are public. Record the source revision, domain, validation time and backup location in your deployment record. A browser toast or broker acceptance alone is insufficient proof of an audible alarm.

## 9. Updates, backups and rollback

Before any update, record the currently deployed source revision and preserve the web/static release directories. Back up `.env`, any secrets, signing keys and the database to encrypted, access-controlled storage. Never publish these backups under `/var/www`.

Example database backup from `/opt/cronos` (the database password stays inside the container):

```bash
umask 077
mkdir -p backups
sudo docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump --no-tablespaces --single-transaction --quick -u "$MYSQL_USER" "$MYSQL_DATABASE"' > "backups/cronos-$(date -u +%Y%m%dT%H%M%SZ).sql"
```

Check the command exit status and nonempty output, encrypt/copy off-host, and test a restore into a separate environment. The MySQL volume is authoritative application state; Redis and RabbitMQ volumes also require an environment-appropriate backup/recovery policy. Broker live queues are temporary and do not replay missed alarms on reconnect. Back up RabbitMQ configuration/user definitions separately if they are changed after initialization. A VM snapshot alone is not a tested database restore.

For subsequent repository updates, first back up and record the current revision. Confirm the working tree is clean and pull only a fast-forward update:

```bash
cd /opt/cronos
git status --short
git rev-parse HEAD
git pull --ff-only
```

Stop if the working tree is dirty, the pull fails or migrations require an additional procedure. Do not reset local changes or automatically resolve production conflicts.

For a planned update, schedule a monitoring outage, back up first, build the new image before stopping services, then:

```bash
cd /opt/cronos
sudo docker compose build
sudo docker compose stop scheduler worker api
sudo docker compose run --rm api python manage.py migrate --noinput
sudo docker compose up -d api worker scheduler
```

Rebuild/copy frontend and collect/copy Django static assets using step 6. Repeat step 8. Keep exactly one scheduler. During the outage, telemetry/probes/live notifications may be unavailable.

Rollback requires the previous source/image and matching web/static assets. Database migrations may be incompatible with old code: review migration reversibility before rollback, or restore the pre-update database during a controlled outage. Do not blindly reverse migrations or restore over live writes. Restoring loses writes since the backup. Never run `sudo docker compose down -v` as an update or repair command; it deletes persistent volumes.


## 10. Troubleshooting

| Symptom | Checks |
| --- | --- |
| Nginx 502 | `sudo docker compose ps`; API logs; loopback health request with the configured Host; Nginx error log. |
| WebSocket missing 101 | Exact WS location, upgrade headers, HTTPS/WSS, Host/Origin configuration, API ASGI command. A normal unauthenticated HTTP GET is not a valid gateway test. |
| Accepted notification but no alarm | Device connected at publication time, enabled registration/preferences, server membership, Android notification permission/alarm volume/battery exemption. Acceptance is broker confirmation, not receipt. |
| Agent offline never opens | Previously received heartbeat, target enabled, maintenance/preferences, worker and scheduler running, readiness heartbeat. |
| Readiness fails | MySQL/Redis reachability and scheduler/worker logs; missing or old JobHeartbeat. |
| Admin CSS missing | Re-run collectstatic, copy to `/var/www/cronos-static`, inspect Nginx alias and permissions. |
| Wrong API/loopback in APK | Rebuild/configure with the public HTTPS API; existing app Settings may retain a prior API override. |
| DB/broker authentication after editing .env | Existing-volume passwords are not reset by initialization variables; rotate service users explicitly. |

Useful commands:

```bash
sudo nginx -t
sudo tail -n 100 /var/log/nginx/cronos-error.log
cd /opt/cronos
sudo docker compose ps
sudo docker compose logs --tail=100 api worker scheduler rabbitmq
sudo docker compose exec rabbitmq rabbitmq-diagnostics -q ping
```

Share redacted logs only. This document and template are prepared configuration; the target server must pass Nginx syntax validation, container startup, public HTTPS, WebSocket and real-device acceptance checks before deployment is considered complete.
