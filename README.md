# Cronos

Server and application monitoring for Android phones and tablets, built with **Quasar Vue + TypeScript**, **Django REST Framework**, **RabbitMQ**, and **MySQL**.

## What works

- Responsive Overview, Servers, Applications, Alerts, and Settings screens.
- Authentication with short-lived access tokens, rotating refresh tokens, and Android secure refresh-token storage.
- Scoped Admin / Operator / Viewer access; account creation, editing, deactivation, password resets, and server role assignment through Users & roles. Platform administrators manage accounts; scoped Admin / Operator / Viewer permissions remain enforced by the API.
- Server registration, configuration, retirement, and one-time agent enrollment/rotation.
- Outbound Python telemetry agent: CPU, RAM, swap, load, selected filesystems/inodes, network counters/rates, and configured systemd services.
- Documented weighted health scoring, missing-data detection, consecutive-sample alerts below 50%, and recovery hysteresis.
- Independent HTTP(S)/TCP probes with DNS resolution and TLS validation, response-time/status/JSON assertions, TLS-expiry incidents, and application histories.
- Distinct agent-offline, endpoint-unreachable, and server-unreachable states.
- Transactional incident deduplication, acknowledgement, investigation comments, recovery notifications, maintenance suppression, reminders, and parent/child outage correlation.
- Persistent in-app incident history, encrypted device registrations, notification outbox/retries, and live browser/Android alerts through private channels.
- MySQL-backed history charts with averages, CPU maxima, minimum health, and explicit gaps; 14-day raw retention.
- Celery worker/scheduler heartbeat, readiness endpoint, and development-only synthetic demo.
- Android project and build script that produces `output/cronos-debug.apk`.

**Scope boundary:** Network packet-loss testing, disk SMART/latency, service restart counts, database internals, queue/cron/backup adapters, logs/security/NTP checks, domain-registration expiry, long-term rollups, capacity forecasting, and external watchdog deployment are follow-up work. They are not represented as passing checks. Production deployment, physical-device push delivery, restore drills, and scale validation are not completed by a local build.

## Repository

```text
Cronos/
├── frontend/                  Quasar Vue app with Vite, Pinia, Vue Router
│   ├── src/components/        Shared tables, badges, bars, charts, editor
│   ├── src/pages/             Overview, Servers, Applications, Alerts, Settings, Users & roles
│   ├── src/services/          API/session, connection settings, push
│   ├── e2e/                   Connected browser workflow tests
│   └── android/               Capacitor native Android project
├── backend/
│   ├── config/                Django, MySQL, Celery, routes
│   └── monitoring/            Models, API, scoring, incidents, probes, tasks, tests
├── agent/                     Python agent, systemd unit, environment example
├── scripts/                   Local process launcher and Android build helper
├── docs/                      Specification and interface reference
├── compose.yaml               API, worker, scheduler, MySQL, Redis
└── .env.example               Backend configuration template
```

## Local development

Prerequisites: Python 3.12+ (current local verification uses 3.14), Node 22+ (local build uses 24), MySQL 8.4+ and Redis. Use `nvm use` if available. MySQL is required; there is no SQLite substitution.

```bash
cd /Users/anthonyyyy/Documents/ChatGPT/Cronos
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

For mysqlclient, Linux needs `default-libmysqlclient-dev build-essential pkg-config`. On macOS with Homebrew, if discovery/linking fails:

```bash
MYSQLCLIENT_CFLAGS="$(mysql_config --cflags)" \
MYSQLCLIENT_LDFLAGS="$(mysql_config --libs) -L$(brew --prefix zstd)/lib -L$(brew --prefix openssl@3)/lib" \
pip install -r backend/requirements.txt
```

Generate separate values for `DJANGO_SECRET_KEY` and `DEVICE_ENCRYPTION_KEY` and place them in `.env`; do not commit that file:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(64))'
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Set your actual MySQL connection/user/password, Redis URL, allowed hosts/origins, and `DJANGO_DEBUG=true` for local development. Create the database and grant the application user access. Tests require access to a separate `test_cronos` database, never a production database.

```bash
python backend/manage.py migrate
python backend/manage.py createsuperuser
npm ci --prefix frontend
python scripts/dev.py
```

Open **http://127.0.0.1:9100**. The frontend proxies `/api` to Django on port 8100. The launcher expects MySQL and Redis to be running already and shuts down its own processes on Ctrl+C. It does not start database services.

For this task's local preview, the ignored `.env` is already configured with a dedicated MySQL instance on **127.0.0.1:3309**, Redis on **127.0.0.1:6389**, and Django on **127.0.0.1:8100**. Those are development settings, not deployment defaults. The MySQL data directory is `.runtime/mysql` with socket `/tmp/cronos-mysql.sock`. Do not reuse the development database root account outside this isolated instance.

To restart that isolated database/Redis if stopped (check the ports before starting another instance):

```bash
mysqld --datadir="$PWD/.runtime/mysql" --port=3309 --bind-address=127.0.0.1 \
  --socket=/tmp/cronos-mysql.sock --pid-file="$PWD/.runtime/mysql.pid" \
  --log-error="$PWD/.runtime/mysql.log" --mysqlx=OFF
# In another terminal:
redis-server --port 6389 --bind 127.0.0.1 --dir "$PWD/.runtime" --save '' --appendonly no
```

### Demo

The local preview is seeded with six synthetic servers and four applications. Choose **Explore the demo** on the browser sign-in screen. Demo metrics are simulated; no requests are made to their example domains. Real servers can be registered separately and collect actual metrics.

To create this dataset in a new development installation, set `DJANGO_DEBUG=true` and `CRONOS_DEMO_MODE=true`, then:

```bash
python backend/manage.py seed_demo
```

Demo sign-in grants access to the local demo administrator and is blocked when `DEBUG=false`. Keep demo mode disabled in production and do not expose development servers publicly. Disable demo mode and remove/deactivate demo data/users before deployment. The Android app uses ordinary username/password sign-in.

## Connect a Linux server

1. Register the server in Cronos. Configure the actual filesystem paths and required systemd services.
2. Open Server details → Generate token. Store the displayed secret directly on the target machine; rotation revokes the old token.
3. Install the `agent/` files into `/opt/cronos-agent`, create an unprivileged `cronos-agent` user, and install its requirements into a virtual environment there.
4. Copy `agent/agent.env.example` to `/etc/cronos-agent.env` and replace the backend URL and token. Match filesystems/services to the server configuration. Protect the environment file with root ownership and mode 600.
5. Copy `agent/cronos-agent.service` into `/etc/systemd/system/`, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cronos-agent
sudo journalctl -u cronos-agent -f
```

The agent sends outbound HTTPS every 30 seconds; it opens no listening port. No SSH private key or root password is stored in Cronos. Unknown/unavailable service or filesystem measurements produce Unknown health rather than fabricated healthy values. An agent can report only for its enrolled server.

Dry-run collector verification:

```bash
python agent/cronos_agent.py --dry-run
```

For local ingestion testing only, the agent permits loopback HTTP when `CRONOS_ALLOW_LOCAL_HTTP=true`; native Android and deployed agents require HTTPS.

## Health and alerts

Full scoring rules are in [docs/specification.md](docs/specification.md). Default weights: CPU 25, RAM 25, disk 25, inodes 10, required services 15. If no required services are configured, that component is excluded and other weights normalize. Missing required measurements make health Unknown.

- Below 50% for three fresh samples opens a critical health incident; exactly 50% does not.
- At least 60% for three samples resolves a low-health incident.
- Heartbeat older than 90 seconds opens Agent offline.
- A powered-off monitored server therefore alerts after its heartbeat expires. Keep the server enabled in Cronos; a disabled/retired target is excluded from monitoring. The target must have reported at least one heartbeat. Evaluation runs every 30 seconds and notification dispatch every 15 seconds.
- Three consecutive independent probe failures open an endpoint/server outage incident according to agent freshness; two successes recover it.
- Three failed application checks mark Down; three slow successful checks mark Degraded; two healthy checks recover.
- Required-service and filesystem-capacity failures alert independently of the aggregate score.
- Acknowledgement stops reminders without pretending the issue is fixed.
- Maintenance suppresses notifications, not collection. Ongoing failures notify after maintenance ends.

Application availability is measured from completed probes; the displayed 24-hour successful-check percentage is not a guarantee of continuous uptime. Response history retains failed probes as gaps.

Private-network probes require an explicit `PROBE_ALLOWED_CIDRS` allowlist and appropriate worker routing. Cloud metadata, disallowed hosts, embedded URL credentials, API/admin paths, and redirects are blocked. Set `PROBE_DENIED_HOSTS` to include the monitoring platform's own hostnames. Firewall the workers from sensitive infrastructure beyond their monitoring targets. All resolved addresses are validated and the connection is pinned to a validated address.

## Android build

Prerequisites: Android Studio, SDK platform 36, JDK 21, Node 22+. Run from the repository root:

```bash
nvm use
./scripts/android-build.sh
```

The result is **`output/cronos-debug.apk`**, signed with the local Android debug key. It is suitable for development installation, not Play Store distribution. The project uses `ph.cronos.monitor` as its initial application ID.

At Android sign-in, enter the HTTPS backend API URL (for example `https://monitor.example.com/api/v1`) and your account credentials. The non-secret URL is remembered. Alternatively, set `VITE_API_URL` in `frontend/.env` before building. The Android app never connects directly to MySQL. Configure CORS for `https://localhost` on the backend.

To open the native project:

```bash
cd frontend
npx cap open android
```

### RabbitMQ notifications and tablet alarms

The notification path is **Django outbox → worker → private RabbitMQ exchange → authenticated WebSocket gateway → browser/tablet**. The gateway shares the ASGI API on port 8100 at `/api/v1/realtime/ws`. Celery scheduling and cache continue to use Redis; RabbitMQ handles notification delivery. No Pusher account, Pusher key, or Firebase project is required.

Configure the backend `.env` with a private broker connection:

```dotenv
RABBITMQ_URL=amqp://cronos:YOUR-URL-ENCODED-PASSWORD@rabbitmq:5672/cronos
RABBITMQ_EXCHANGE=cronos.notifications
RABBITMQ_DEFAULT_USER=cronos
RABBITMQ_DEFAULT_PASS=YOUR-PASSWORD
RABBITMQ_DEFAULT_VHOST=cronos
```

The `RABBITMQ_DEFAULT_*` values initialize the Compose broker; match them to the URL. Use `amqps://` with trusted TLS for a remote broker. Broker credentials stay on the backend. RabbitMQ AMQP/management ports are not published by Compose; clients connect only to Cronos over HTTPS/WSS. The gateway authenticates a device credential in its first WebSocket message, not a URL query or broker login. It chooses the route from the device identity, rejects client subscriptions, validates browser origins, rechecks device/account/preference access every 20 seconds, and rechecks server membership before forwarding each event.

For the existing local development database, `.env` now uses an isolated broker on **127.0.0.1:5679**. To run it in a terminal:

```bash
brew install rabbitmq
.venv/bin/python scripts/rabbitmq-dev.py
# In another terminal, with MySQL and Redis already running:
.venv/bin/python scripts/dev.py
```

The broker helper reads the local URL from `.env`, binds to loopback, and keeps broker data under ignored `.runtime/rabbitmq/`. It does not register a system service. The launcher now runs Uvicorn ASGI rather than Django's WSGI development server so WebSockets work. Use the project's launcher or the ASGI Docker image; `manage.py runserver` alone cannot provide this gateway.

Sign-in registers this installation and opens the notification socket. **Settings → Register this device** reconnects it; **Send test notification** queues a test through the worker (normally within 15 seconds). Browsers require the page to stay open. Android uses a native foreground monitoring service independent of WebView timers, with an ongoing **Cronos monitoring active** notification. Incidents, reminders, and tests sound a native alarm; recovery uses a separate channel.

**Test tablet alarm** tests local sound directly. **Stop alarm** silences the notification without acknowledging the incident or stopping monitoring. Alarms repeat for up to 30 seconds. **Alarm sound settings** opens Android channel settings. Keep alarm volume audible; Android channel controls and Do Not Disturb still apply. **Stop monitoring** on the ongoing notification stops the service; register again to restart it. Native service credentials remain encrypted with Android Keystore and native bridge payload logging stays disabled.

Each live socket has an exclusive, automatically deleted queue with a 30-second message TTL and a bounded backlog; two tabs receive their own copy. Broker publisher confirms feed outbox acceptance/retries. Acceptance means RabbitMQ accepted the publication, not that a tablet played it. Persistent MySQL incident/notification history remains authoritative; offline events are not replayed as alarms. Clients deduplicate notification IDs. Legacy device-token prefixes/storage are accepted during migration; there is no remaining Pusher client/publisher dependency. Install the updated APK on existing tablets; older Pusher-only builds cannot use the new gateway.

Network loss, Android Doze, and vendor battery restrictions can interrupt sockets. Allow unrestricted battery use for a dedicated monitoring tablet. Force-stop/reboot requires reopening Cronos; no boot auto-start is configured. Prolonged deep-idle reliability, release signing, production hosting/TLS, and store foreground-service review remain separate validation work. See [the gateway deployment guide](docs/notification-gateway.md).

## Container deployment preparation

For host Nginx, follow the [complete production deployment runbook](docs/deployment/README.md) and use its [Nginx site template](docs/deployment/nginx.conf.example). The runbook covers HTTPS, WebSocket forwarding, static files, migrations, worker/scheduler startup, backups, updates and real-device alarm verification.

`compose.yaml` provides MySQL, Redis, RabbitMQ, ASGI API/gateway, worker, and scheduler. Use a fresh production `.env` based on the example, including distinct MySQL root/application passwords, production hosts/origins, encryption key, and `DEBUG=false` / `CRONOS_DEMO_MODE=false`. Do not copy the local development `.env` into production unchanged.

```bash
docker compose up -d mysql redis rabbitmq
docker compose run --rm api python manage.py migrate
docker compose run --rm api python manage.py createsuperuser
docker compose up -d api worker scheduler
```

Serve the API through a TLS reverse proxy on the monitoring host, with port 8100 kept on loopback; serve `frontend/dist/` separately if browser access is wanted. Only trust proxy headers from your controlled reverse proxy. Run exactly one scheduler. Monitor `/api/v1/health/ready` from an external watchdog and back up MySQL plus the encryption key securely. Docker images are supplied; container deployment has not been verified in this workspace. Proxy WebSocket upgrades for `/api/v1/realtime/ws` as shown in the gateway guide.

## Verification

```bash
.venv/bin/python backend/manage.py check
.venv/bin/python backend/manage.py test monitoring --noinput
# Include real RabbitMQ gateway integration tests against the isolated local broker:
CRONOS_BROKER_TESTS=1 .venv/bin/python backend/manage.py test monitoring --noinput
npm run build --prefix frontend
# With local API, scheduler, worker, frontend, and demo mode running:
npm run test:e2e --prefix frontend
./scripts/android-build.sh
```

Browser tests use installed Google Chrome via Playwright. The integrated browser connection was unavailable in this task, so Playwright was used. Tests exercise actual Django/MySQL APIs, not static UI mocks. Do not run the end-to-end tests against a production deployment: they create and retire explicit `qa-server-*` development targets.

See [docs/implementation-status.md](docs/implementation-status.md) for verified scope and remaining work.

## Install the agent with wget

The backend now serves a shell installer at `/api/v1/agent/install.sh`. Open a real server's detail screen for its copyable install command, or follow [the complete server setup guide](docs/server-agent-setup.md). The installer prompts for the enrollment token, verifies the downloaded agent files, installs the agent and systemd service, and enables automatic reporting. Use your deployed HTTPS backend hostname; the Mac's loopback preview is not reachable from a remote server.

### Tablet development API over USB

`scripts/android-build.sh` builds a debug APK with `http://127.0.0.1:8100/api/v1` prefilled. It permits HTTP only for localhost/127.0.0.1; the Android network exception is in the debug source set. Standard builds still require HTTPS. Override `VITE_API_URL` to use another HTTPS backend.

With the tablet authorized and the local API running, connect it over USB:

```bash
adb reverse tcp:8100 tcp:8100
adb install -r output/cronos-debug.apk
```

Keep USB connected and the development API running. Reapply `adb reverse` after reconnecting if needed. Sign in with a regular Cronos account.
