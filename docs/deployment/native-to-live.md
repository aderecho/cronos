# Cronos Native Nginx Deployment Guide

Deploy Cronos directly on Ubuntu 24.04 LTS amd64 with Nginx, Python 3.12, MySQL, Redis, RabbitMQ and systemd. Run each block separately and stop on failure. Replace the repository URL, branch and monitor.example.com before execution. Start from your root@cronus shell, then switch to aoderecho as directed. This procedure creates /opt/cronos before cloning.

## 1. Confirm repository DNS and server access

The remote repository must contain backend/requirements.txt, backend/manage.py, frontend/package-lock.json, .env.example, agent and docs/deployment/nginx.conf.example. Clone downloads only committed and pushed source. Obtain the actual repository URL; none is configured in the local checkout. Use a read-only deploy key for a private repository; do not embed credentials into the URL.

Point the public DNS A record for monitor.example.com to the server. Configure IPv6 correctly before publishing AAAA. Allow public TCP 80/443 and preserve the actual SSH port. Data services and port 8100 must remain private. This guide assumes Nginx directly terminates TLS; additional load balancers need their own trusted-proxy configuration. Keep an off-server backup destination ready.

## 2. Prepare the server and application directory

Run this block as root. Confirm the OS and architecture before installing packages. This runbook's RabbitMQ repository and Node archive commands are for Ubuntu noble amd64.

```bash
cat /etc/os-release
dpkg --print-architecture
id aoderecho
apt update
apt install -y sudo git nginx certbot curl ca-certificates gnupg openssl xz-utils nano python3 python3-venv python3-dev build-essential pkg-config default-libmysqlclient-dev mysql-server redis-server
install -d -o aoderecho -g aoderecho -m 755 /opt/cronos
systemctl enable --now nginx mysql redis-server
su - aoderecho
```

All remaining shell commands run as aoderecho, with sudo where shown. Confirm sudo works; if access is missing, configure it through your server's administrative policy from the root shell before continuing.

```bash
whoami
sudo -v
sudo nginx -T
sudo ss -lntp
df -h
```

Do not overwrite unrelated sites or services. Review existing firewall rules and retain SSH access before making changes. Keep TCP 3306, 6379, 5672, 4369, 25672 and 8100 inaccessible from public networks.

## 3. Clone the application repository

Replace the URL and branch. The newly prepared directory must be empty. If a checkout already exists, inspect its remote and working tree instead of cloning over it.

```bash
CRONOS_REPO='https://github.com/YOUR-ORGANIZATION/YOUR-REPOSITORY.git'
CRONOS_BRANCH='main'
git clone --branch "$CRONOS_BRANCH" "$CRONOS_REPO" /opt/cronos
cd /opt/cronos
git status --short
git rev-parse HEAD
ls -l backend/manage.py backend/requirements.txt frontend/package-lock.json .env.example
```

Expected: all four files exist, the working tree is clean and the deployed revision is recorded. If /opt/cronos is missing, return to step 2. Do not delete an existing checkout to resolve a clone error.

## 4. Install Python dependencies

```bash
cd /opt/cronos
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/pip check
```

Expected: Python 3.12 and dependency installation completes. mysqlclient requires the development libraries installed in step 2. If a pinned package cannot be resolved, stop and reconcile requirements rather than silently installing different versions.

## 5. Install current RabbitMQ and Erlang

Use Team RabbitMQ's Ubuntu noble amd64 repositories. If RabbitMQ already exists, review its version and upgrade procedure before changing packages. The standard Ubuntu RabbitMQ package may be out of community support. Reference: https://www.rabbitmq.com/docs/install-debian

```bash
curl -fsSL https://keys.openpgp.org/vks/v1/by-fingerprint/0A9AF2115F4687BD29803A206B73A36E6026DFCA -o /tmp/cronos-rabbitmq-signing.asc
sudo gpg --dearmor --output /usr/share/keyrings/cronos-rabbitmq.gpg /tmp/cronos-rabbitmq-signing.asc
sudo tee /etc/apt/sources.list.d/cronos-rabbitmq.list >/dev/null <<'APT'
deb [arch=amd64 signed-by=/usr/share/keyrings/cronos-rabbitmq.gpg] https://deb1.rabbitmq.com/rabbitmq-erlang/ubuntu/noble noble main
deb [arch=amd64 signed-by=/usr/share/keyrings/cronos-rabbitmq.gpg] https://deb2.rabbitmq.com/rabbitmq-erlang/ubuntu/noble noble main
deb [arch=amd64 signed-by=/usr/share/keyrings/cronos-rabbitmq.gpg] https://deb1.rabbitmq.com/rabbitmq-server/ubuntu/noble noble main
deb [arch=amd64 signed-by=/usr/share/keyrings/cronos-rabbitmq.gpg] https://deb2.rabbitmq.com/rabbitmq-server/ubuntu/noble noble main
APT
sudo apt update
sudo apt install -y erlang-base erlang-asn1 erlang-crypto erlang-eldap erlang-ftp erlang-inets erlang-mnesia erlang-os-mon erlang-parsetools erlang-public-key erlang-runtime-tools erlang-snmp erlang-ssl erlang-syntax-tools erlang-tftp erlang-tools erlang-xmerl rabbitmq-server
```

For a fresh dedicated RabbitMQ installation, bind AMQP to loopback. On an existing host, merge this setting into its current configuration instead of overwriting it.

```bash
sudo nano /etc/rabbitmq/rabbitmq.conf
```

Add or set this configuration line, then restart and verify:

```ini
listeners.tcp.default = 127.0.0.1:5672
```

```bash
sudo systemctl enable --now rabbitmq-server
sudo systemctl restart rabbitmq-server
sudo rabbitmq-diagnostics -q ping
```

The management plugin is unnecessary. Keep RabbitMQ's Erlang distribution and epmd ports private using the host/cloud firewall as well. A cluster would require a different network design.

## 6. Create production secrets and database access

Create configuration only on first installation. Do not overwrite an existing production .env or regenerate its encryption key during updates.

```bash
cd /opt/cronos
umask 077
cp .env.example .env
chmod 600 .env
mkdir -p secrets
chmod 700 secrets
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
nano .env
```

Use the three distinct hex values as DJANGO_SECRET_KEY, MYSQL_PASSWORD and the RabbitMQ application password. Use the Fernet output as DEVICE_ENCRYPTION_KEY. Store them in your approved secret manager and encrypted backups. The database and RabbitMQ users below must receive those same passwords.

Set the following in .env, replacing the three marked secret values and the Fernet key. These native host endpoints replace service names such as mysql, redis and rabbitmq from other deployment examples:

```dotenv
DJANGO_SECRET_KEY=PASTE_DJANGO_SECRET
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=monitor.example.com
TRUST_PROXY=true
MYSQL_DATABASE=cronos
MYSQL_USER=cronos
MYSQL_PASSWORD=PASTE_DATABASE_HEX_PASSWORD
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
DEVICE_ENCRYPTION_KEY=PASTE_FERNET_KEY
REDIS_URL=redis://127.0.0.1:6379/0
RABBITMQ_URL=amqp://cronos:PASTE_RABBITMQ_HEX_PASSWORD@127.0.0.1:5672/cronos
RABBITMQ_EXCHANGE=cronos.notifications
CORS_ALLOWED_ORIGINS=https://monitor.example.com,https://localhost
CRONOS_DEMO_MODE=false
PROBE_ALLOWED_CIDRS=
PROBE_DENIED_HOSTS=localhost,metadata.google.internal,metadata,monitor.example.com
```

The MYSQL_ROOT_PASSWORD and RABBITMQ_DEFAULT variables in .env.example are not used to provision native services. Remove them to avoid confusion. Restrict PROBE_ALLOWED_CIDRS to explicitly approved private monitoring networks. Never use a blanket allowlist just to bypass validation. Keep https://localhost in CORS for Capacitor Android.

Open MySQL's interactive client with history disabled:

```bash
sudo env MYSQL_HISTFILE=/dev/null mysql
```

Run these SQL statements inside MySQL, replacing the password with MYSQL_PASSWORD from .env. These create a new database and user; inspect existing installations first if either already exists.

```sql
CREATE DATABASE cronos CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'cronos'@'127.0.0.1' IDENTIFIED BY 'PASTE_DATABASE_HEX_PASSWORD';
GRANT ALL PRIVILEGES ON cronos.* TO 'cronos'@'127.0.0.1';
EXIT;
```

Set MySQL bind-address to 127.0.0.1 in /etc/mysql/mysql.conf.d/mysqld.cnf and verify Redis binds only loopback with protected-mode yes in /etc/redis/redis.conf. Preserve other existing settings. Restart only after checking the impact on other applications:

```bash
sudo systemctl restart mysql redis-server
redis-cli -h 127.0.0.1 ping
sudo rabbitmqctl add_vhost cronos
sudo rabbitmqctl add_user cronos
sudo rabbitmqctl set_permissions -p cronos cronos '.*' '.*' '.*'
```

The add_user command prompts for the RabbitMQ password; enter the same hex password embedded in RABBITMQ_URL. Do not add administrator tags. Inspect existing users/vhosts before retrying creation. Redis should return PONG. RabbitMQ and MySQL bind to loopback for this single-host setup.

## 7. Migrate the database and create the administrator

```bash
cd /opt/cronos
.venv/bin/python backend/manage.py check
.venv/bin/python backend/manage.py migrate --noinput
.venv/bin/python backend/manage.py createsuperuser
.venv/bin/python backend/manage.py collectstatic --noinput
sudo install -d -m 755 /var/www/cronos-static
sudo cp -a backend/staticfiles/. /var/www/cronos-static/
sudo chmod -R a+rX /var/www/cronos-static
```

Expected: migrations succeed and the administrator is created. Do not enable demo login or load development sample data in production. Never replace migrations with a database reset.

## 8. Build and publish the frontend

Install the Node version pinned by .nvmrc. The following downloads the official Linux amd64 release and checks its SHA256 before extraction. It does not replace a system-wide Node installation. Run it only for the documented amd64 host.

```bash
cd /tmp
curl -fSLO https://nodejs.org/dist/v24.11.1/node-v24.11.1-linux-x64.tar.xz
curl -fSLO https://nodejs.org/dist/v24.11.1/SHASUMS256.txt
awk '$2 == "node-v24.11.1-linux-x64.tar.xz"' SHASUMS256.txt | sha256sum -c -
sudo tar -xJf node-v24.11.1-linux-x64.tar.xz -C /opt
export PATH=/opt/node-v24.11.1-linux-x64/bin:$PATH
node --version
cd /opt/cronos/frontend
npm ci
VITE_API_URL=https://monitor.example.com/api/v1 VITE_ALLOW_LOCAL_HTTP=false npm run build
sudo install -d -m 755 /var/www/cronos-web
sudo cp -a dist/. /var/www/cronos-web/
sudo chmod -R a+rX /var/www/cronos-web
```

Expected: Node v24.11.1, successful build and /var/www/cronos-web/index.html. Replace the domain before building. Frontend API settings are compiled into the build. Nginx serves these files; do not run Vite's development server in production. Only dist and Django static assets belong in the public directories.

## 9. Configure systemd services

The examples use aoderecho as the runtime account to match your current server setup. Never run Uvicorn or Celery as root. A deployment with a separate runtime account needs its own source, secret and state-directory permissions. Application settings load /opt/cronos/.env directly; do not source that file into a shell.

Create the API unit:

```bash
sudo tee /etc/systemd/system/cronos-api.service >/dev/null <<'UNIT'
[Unit]
Description=Cronos API and WebSocket gateway
After=network-online.target mysql.service redis-server.service rabbitmq-server.service
Wants=network-online.target
[Service]
User=aoderecho
Group=aoderecho
WorkingDirectory=/opt/cronos/backend
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/cronos/.venv/bin/uvicorn config.asgi:application --host 127.0.0.1 --port 8100 --workers 3 --ws-max-size 4096 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
```

Create the worker and the single scheduler:

```bash
sudo tee /etc/systemd/system/cronos-worker.service >/dev/null <<'UNIT'
[Unit]
Description=Cronos Celery worker
After=network-online.target mysql.service redis-server.service rabbitmq-server.service
Wants=network-online.target
[Service]
User=aoderecho
Group=aoderecho
WorkingDirectory=/opt/cronos/backend
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/cronos/.venv/bin/celery -A config worker --loglevel=INFO --concurrency=4
Restart=always
RestartSec=5
TimeoutStopSec=150
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
```

Create the scheduler unit:

```bash
sudo tee /etc/systemd/system/cronos-scheduler.service >/dev/null <<'UNIT'
[Unit]
Description=Cronos Celery scheduler
After=network-online.target redis-server.service cronos-worker.service
Wants=network-online.target
[Service]
User=aoderecho
Group=aoderecho
WorkingDirectory=/opt/cronos/backend
Environment=PYTHONUNBUFFERED=1
StateDirectory=cronos
ExecStart=/opt/cronos/.venv/bin/celery -A config beat --loglevel=INFO --schedule=/var/lib/cronos/celerybeat
Restart=always
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
```

Validate and start the services:

```bash
sudo systemd-analyze verify /etc/systemd/system/cronos-api.service /etc/systemd/system/cronos-worker.service /etc/systemd/system/cronos-scheduler.service
sudo systemctl daemon-reload
sudo systemctl enable --now cronos-api cronos-worker cronos-scheduler
sudo systemctl status cronos-api cronos-worker cronos-scheduler --no-pager
```

Expected: all three services are active. Run exactly one scheduler. The API must serve config.asgi:application so WebSockets work. Check logs before proceeding if any service restarts repeatedly.

```bash
sudo journalctl -u cronos-api -u cronos-worker -u cronos-scheduler -n 100 --no-pager
curl -fsS -H 'Host: monitor.example.com' http://127.0.0.1:8100/api/v1/health/live
```

## 10. Bootstrap HTTPS

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


## 11. Acceptance checks

Run on the server:

```bash
cd /opt/cronos
curl -fsS -H 'Host: monitor.example.com' http://127.0.0.1:8100/api/v1/health/live
curl -fsS https://monitor.example.com/api/v1/health/live
curl -fsS https://monitor.example.com/api/v1/health/ready
curl -I https://monitor.example.com/
curl -I https://monitor.example.com/static/admin/css/base.css
sudo ss -lntp
.venv/bin/python backend/manage.py check --deploy
sudo journalctl -u cronos-api -u cronos-worker -u cronos-scheduler -n 100 --no-pager
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


## 12. Go live and record acceptance

Go live when sign-in works, readiness is healthy, the WebSocket authenticates and the actual tablet produces an alarm with the screen locked. Confirm the services are enabled for startup, data ports are private and the certificate renew dry-run passes. Record the deployed git revision, hostname, test time, observed alarm result and backup destination. A broker acceptance or browser toast does not establish audible delivery.

## 13. Back up the database and secrets

Back up before updates and on a regular schedule. Keep encrypted copies off-server. Preserve .env and DEVICE_ENCRYPTION_KEY; regenerating the encryption key prevents stored device credentials from decrypting. Never store backups in a public web directory.

From aoderecho's shell, create a consistent logical MySQL backup using the local root socket. The command prompts for sudo authorization if needed; no database password is put on the command line:

```bash
cd /opt/cronos
umask 077
mkdir -p backups
sudo mysqldump --no-tablespaces --single-transaction --quick cronos > "backups/cronos-$(date -u +%Y%m%dT%H%M%SZ).sql"
```

Verify the command succeeds and output is nonempty, encrypt it and copy it off-host. Test restoration into a separate database environment. Archive configuration from /etc/nginx, /etc/systemd/system/cronos-*.service and /etc/rabbitmq. Protect RabbitMQ user definitions as sensitive data if exported. Redis and RabbitMQ have their own persistence and recovery requirements; the MySQL database is authoritative notification/incident history. Temporary live alarm queues do not replay missed alarms on reconnect.

## 14. Pull updates and restart safely

Schedule a monitoring outage. Back up the database/secrets and preserve the previous source revision, Python environment and published web/static files before changing the release. Review migration compatibility first. Commands run as aoderecho:

```bash
cd /opt/cronos
git status --short
git rev-parse HEAD
git pull --ff-only
```

Stop on local changes, conflicts or a failed pull; do not reset production changes. After source review, stop application services while leaving MySQL, Redis and RabbitMQ running:

```bash
sudo systemctl stop cronos-scheduler cronos-worker cronos-api
cd /opt/cronos
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python backend/manage.py migrate --noinput
.venv/bin/python backend/manage.py collectstatic --noinput
sudo cp -a backend/staticfiles/. /var/www/cronos-static/
sudo chmod -R a+rX /var/www/cronos-static
```

Rebuild and publish the frontend using step 8; re-export the Node PATH in a new shell. If units changed, run systemd-analyze verify and systemctl daemon-reload. Start services and repeat the acceptance checks in steps 10 through 12:

```bash
sudo systemctl start cronos-api cronos-worker cronos-scheduler
sudo systemctl status cronos-api cronos-worker cronos-scheduler --no-pager
```

During the outage, collection/probes/notifications may be unavailable. Rollback requires the previous source, matching Python dependencies and web/static assets. If migrations are incompatible, restore the pre-update database during a controlled outage; restoring loses writes since that backup. Do not reverse migrations blindly or restore over ongoing writes. Do not delete MySQL, Redis or RabbitMQ data directories as a repair step.

## 15. Troubleshooting and operating commands

```bash
sudo nginx -t
sudo systemctl status cronos-api cronos-worker cronos-scheduler --no-pager
sudo journalctl -u cronos-api -u cronos-worker -u cronos-scheduler -n 100 --no-pager
sudo tail -n 100 /var/log/nginx/cronos-error.log
sudo ss -lntp
sudo rabbitmq-diagnostics -q ping
redis-cli -h 127.0.0.1 ping
```

For a 502, check API service status, the loopback health endpoint and the Nginx error log. For missing WebSocket 101, check the exact gateway location, upgrade headers, Host/Origin allowlists and ASGI service command. A plain unauthenticated HTTP GET is not a valid gateway authentication test.

For accepted notifications without sound, verify live connectivity, notification permissions, alarm volume, battery exemption, registration/preferences and server membership. For missing offline detection, confirm a previous heartbeat, enabled target and active worker/scheduler. Maintenance suppresses notifications. Admin CSS errors usually indicate missing collectstatic copy or incorrect alias permissions.

If the application cannot read .env, check its ownership and mode; aoderecho runs these services. Preserve 600 permissions rather than making secrets world-readable. For an API containing localhost or 127.0.0.1 on a remote tablet, configure the public HTTPS endpoint and rebuild or remove the old Settings override.

The document's commands and systemd syntax require target-host validation. No installation or production go-live is claimed by providing this runbook. Share only redacted logs.
