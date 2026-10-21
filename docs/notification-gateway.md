# RabbitMQ notification gateway

The backend publishes committed notification outbox entries to a durable direct exchange. Each authenticated WebSocket gets a temporary exclusive queue bound only to its device route. Queue TTL is 30 seconds and maximum backlog is 100 messages. The client never chooses a RabbitMQ route or receives an AMQP username/password. Browser origins and hostnames must match backend configuration. The gateway authenticates the device credential in the first message within five seconds, revalidates it every 20 seconds, and checks current server membership before forwarding every alert.

## Run locally

Configure `.env` with a dedicated broker connection on loopback, for example `amqp://cronos:YOUR-PASSWORD@127.0.0.1:5679/cronos`. Use URL-safe credentials or URL-encode them. Keep `.env` mode 600 and ignored by Git. Install RabbitMQ (`brew install rabbitmq` on macOS), then run:

```bash
.venv/bin/python scripts/rabbitmq-dev.py
# Separate terminal, with the project's MySQL and Redis already running:
.venv/bin/python scripts/dev.py
```

The local broker has its own `.runtime/rabbitmq` data and no management plugin. It is not a system service. Stop its foreground command with Ctrl+C. Do not start another instance on its ports. Existing local MySQL stays on 3309, Redis on 6389, API/gateway on 8100, and Vite on 9100. The Android development APK continues to use `adb reverse tcp:8100 tcp:8100` for both HTTP and WebSocket traffic.

## Production preparation

Use `compose.yaml` with a new production `.env`, distinct RabbitMQ credentials, and `DEBUG=false`. The `RABBITMQ_DEFAULT_*` credentials initialize a new broker volume; changing these environment variables does not rotate users in an existing volume. Follow RabbitMQ's user-management procedure for later password changes. Match the URL username/password/vhost to broker configuration. Keep AMQP/management ports private; use verified AMQPS when crossing untrusted networks. Redis remains the Celery task broker/cache.

The API Docker image serves `config.asgi:application` with Uvicorn, handling HTTP and WebSocket upgrades on port 8100. A separate public gateway port is unnecessary. The following fragment belongs inside your existing TLS Nginx server; it is an example, not a deployed configuration:

```nginx
location = /api/v1/realtime/ws {
    proxy_pass http://127.0.0.1:8100;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 90s;
    proxy_send_timeout 90s;
    proxy_buffering off;
}
```

Set `DJANGO_ALLOWED_HOSTS` to the API hostname and `CORS_ALLOWED_ORIGINS` to your exact web UI origins plus `https://localhost` for the Capacitor app. Use HTTPS for the API and WSS for sockets. Configure trusted proxy headers only for your controlled proxy. The native client requires the WebSocket endpoint to share the API's origin. The only plaintext native exception is a debug-only loopback development build.

## Verify

1. Start RabbitMQ, API/gateway, worker, scheduler, and frontend. Open Settings and register the device; wait for the connected message.
2. Send a test notification. Confirm the in-app message or native tablet alarm. Broker acceptance alone does not prove display or audio.
3. Run `CRONOS_BROKER_TESTS=1 .venv/bin/python backend/manage.py test monitoring --noinput` against isolated development services; this creates a separate MySQL test database.
4. Run `npm run test:e2e --prefix frontend` for the actual browser/API/worker/RabbitMQ path. Tests create and retire QA targets and deactivate QA accounts; do not run them against production.
5. For a tablet, install `output/cronos-debug.apk`, register, put Cronos in the background/lock the screen, and queue a test notification. Check the alarm and Stop alarm behavior.

Worker publication uses RabbitMQ publisher confirms and retains existing retry/backoff state. Gateway acknowledgements follow WebSocket forwarding, not a human acknowledgement. Offline sockets have no durable live queue: persisted incident history remains available, but reconnecting does not replay stale alarms. Device/account deactivation and notification preferences revoke access; server membership removal prevents future forwarding for that server.

Android force-stop, reboot, deep idle, network loss, and vendor battery restrictions remain relevant. Reopen after force-stop/reboot and allow unrestricted battery use on a dedicated monitoring tablet. Production hosting/TLS, broker HA/backup operations, capacity tuning, and store foreground-service review require environment-specific verification.

In Android Settings within Cronos, use **Allow background alarms** and approve the system battery exemption. The monitoring foreground service holds a bounded partial wake lock, renewed while monitoring is active and released when the service stops. Continuous monitoring uses more battery. This supports live connections during screen-off operation, but physical idle delivery still requires device-specific verification; a successful broker publication is insufficient.

Connection, reconnect and alarm callbacks run on a dedicated native handler thread rather than the WebView UI thread. On the development Infinix X1103, automatic offline detection was verified with both normal screen locking and forced deep idle: the native notification appeared and Android recorded alarm audio starting. This is device-specific development evidence, not a guarantee for every vendor or network.

For a power-off test, use an enabled target that has already sent a heartbeat, then stop its agent or power it off. With the defaults, its heartbeat becomes stale after 90 seconds, the next 30-second evaluation opens one Agent offline incident, and the next 15-second dispatch queues the alert for eligible devices. Maintenance and notification preferences still apply. Retiring the target in Cronos intentionally stops monitoring.
