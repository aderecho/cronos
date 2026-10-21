# Cronos implementation status

20 October 2026 · local development build

## Delivered

Quasar Vue/TypeScript frontend, Django REST API, MySQL migrations, Celery/Redis worker/scheduler, outbound telemetry agent, incident/notification persistence, Android native project and debug APK. Full installation, enrollment, RabbitMQ/gateway, deployment preparation, and verification commands are in `README.md`.

The primary requested behavior is implemented: server resource monitoring, independent availability checks, alerts below 50% after the configured persistence window, outage incidents, and independent application health/status. The mobile application reads the backend; monitoring continues while the application is closed.

## Verification evidence

| Check | Result | Limit |
|---|---|---|
| Django system checks | Passed | Local settings |
| Migration drift | No changes detected | Initial migration applied to isolated MySQL |
| Backend tests | 64 passed including live RabbitMQ integration | MySQL 9.4 local test database; no SQLite substitute |
| Browser end-to-end tests | 5 passed against the RabbitMQ/ASGI stack | Actual API/MySQL, synthetic telemetry, installed Chrome via Playwright |
| Phone/tablet layouts | Passed at 390×844, 768×1024, 1504×1045 | Browser layout checks, not physical devices |
| TypeScript/production web build | Passed | Quasar + Vite |
| Android emulator startup | Installed and opened on API 36.1; native WebView showed backend URL, username, and password fields with no horizontal overflow | WebView sign-in UI only; Android system/Pixel Launcher ANR dialogs prevented reliable native interaction testing; no deployed HTTPS account or live push |
| Native Android build | `assembleDebug` passed | Debug signed APK; release signing not configured |
| Dependency audit | 0 reported vulnerabilities at completion | npm lockfile snapshot; not a security guarantee |
| Python agent collector | Dry-run schema verified on macOS | Target Linux/systemd runtime remains unverified |
| RabbitMQ notification delivery | Passed: device authentication → outbox → RabbitMQ → gateway → visible browser alert; broker tests verify fan-out, isolation, revocation, and rejected subscription changes | Broker confirms are not proof of human receipt |
| Docker deployment | Not performed | Docker daemon unavailable; Compose/Dockerfile supplied |
| Production/scale/restore | Not performed | Requires deployment and target access |

Native startup initially exposed a Capacitor safe-area injection issue. Configuring native system-bar insets removed it. Missing refresh-token lookup now checks key presence before reading, avoiding expected native-storage errors on first launch.

For the 20 October update, the Browser plugin/skill was not available. Playwright with installed Google Chrome verified the rendered app, console health, and real RabbitMQ/gateway notification. A stale Vite dependency cache caused the first login run to time out; after restarting local services, the affected test passed.

### Connected workflow exercised

Browser demo sign-in → add server → open server → issue one-time token → submit three critical metric samples through the authenticated agent API → refresh dashboard → observe Critical → open low-health incident → acknowledge → add investigation note → Settings notification registration → send test notification → visible live alert → application response history → retire test server. Separate responsive tests exercised navigation, filtering, details, chart rendering, and overflow checks at all three viewports. No application page errors occurred in the passing suite.

### Interface fidelity ledger

Reference: `docs/dashboard-concept.png`, generated with the built-in image tool. Final screenshots were captured with Playwright and inspected using `view_image` against the concept at its 1504×1045 native dimensions, plus phone/tablet views.

| Comparison | Reference and implemented result | Resolution |
|---|---|---|
| Composition | Dark left navigation; title/actions; four stats; server table beside incidents; application rows beside activity | Preserved; tightened rows/header spacing to fit the tablet reference |
| Palette | Cool pale canvas, white panels, navy navigation, emerald health, restrained red incidents | Preserved; no gradients or raster UI |
| Typography | Strong page heading, readable section labels, compact metric labels | Increased desktop table/body text after screenshot review |
| Components | Outline icons, resource bars, status dots, light panel borders | Code-native Quasar controls and Lucide icons; chart interaction on details |
| Copy | Required navigation/actions/labels | Preserved; resource values and ordering come from API rather than illustrative screenshot numbers |
| Data correctness | Synthetic reference scores were illustrative | Deliberate deviation: actual weighted scoring returns 100/96/94/37, not invented screenshot scores |
| Responsive continuation | Tablet navigation and table structure | Phone bottom navigation, stacked rows/panels, full-width detail drawers; no horizontal overflow |

Above-the-fold copy review: navigation, Overview, subtitle, Refresh, Add server, demo label, and four summary labels match the design inventory. Required additions are authentication, account control, live/stale/empty/error states, role permissions, setup feedback, and a worker status footer. These are intentional functional additions from the specification. No decorative marketing sections were added to the dashboard.

## Remaining specification milestones

- Long-term five-minute/hourly stored rollups, one-year trends, and forecasting. Raw history currently retains 14 days; chart ranges are 1h/24h/7d.
- Detailed database internals/replication; background queue and cron heartbeats; backup/restore observations; logs/security updates; clock drift; domain-registration expiry; SMART/disk-latency and packet-loss adapters; service restart counts.
- Worker load/concurrency tuning and benchmark at the actual server/application count. Current checks are bounded by per-probe timeouts and serialized scheduler execution; scale is not certified.
- Long-duration Android deep-idle/vendor battery testing and other tablet models. The native alarm service uses no Google Play Services or external push provider.
- Production HTTPS hosting, external monitoring watchdog, MySQL backup/restore drill, release signing, and Play Store distribution.

No unavailable adapter is displayed as healthy. The local demo is explicitly labelled and does not prove real server, production, or push behavior.

Native validation limitation: the API 36.1 emulator showed Android system / Pixel Launcher “not responding” dialogs. Cronos's WebView rendered the expected form and reported no horizontal overflow; the final app log had no AndroidRuntime/Capacitor console errors. This is not proof of a fully working native interaction flow. The emulator was stopped after inspection; that historical emulator limitation does not supersede the later physical Infinix tablet alarm checks documented below.

## Wget service installation follow-up

Added `agent/install.sh`, fixed-name Django artifact downloads and SHA-256 manifest, Docker download-source packaging, and copyable install commands in real server details. The installer prompts securely for a server token, installs the Python reporting agent and unprivileged systemd service, and enables 30-second reporting. Full instructions: `docs/server-agent-setup.md`.

Follow-up verification: 44 backend tests passed (including six installer/distribution tests), four connected browser tests passed with install-command/token-exclusion assertions, Django checks passed, production web build passed, and Android debug APK rebuilt successfully. Live local API artifact checksums matched. The installer has not been run on a target Linux/systemd host; remote HTTPS hosting and live service-to-backend reporting still require target access.


## RabbitMQ migration and native alarms (20 October 2026)

Replaced Pusher publishing and browser/Android clients with private RabbitMQ plus an authenticated ASGI WebSocket gateway. RabbitMQ credentials stay server-side. Existing encrypted device registrations and Android alarm channels remain usable, including legacy token prefixes; tablets require the new APK. API and gateway share port 8100, the Vite proxy supports WebSocket upgrades, and Docker/dev launchers now use Uvicorn. Celery/Redis scheduling is unchanged. Added isolated local broker launcher, private Compose broker, deployment guide, and gateway authorization/broker integration tests.

The native foreground monitoring service keeps its own socket and displays a persistent monitoring notification. The existing 30-second audible alarm, Stop alarm, local test, channel settings, encrypted device credential, and background/locked-screen behavior are preserved. Prolonged deep-idle delivery and production/store deployment remain unverified.

Final migration validation: 64 backend tests passed against MySQL and local RabbitMQ 4.4, five Chrome e2e tests passed, Vue/TypeScript build and Android debug build passed, migration drift check passed, and the updated APK was installed on the Infinix X1103. Native status reported connected to the gateway. With the screen initially Dozing, test notification 42 was accepted as `rabbitmq:42:8` and produced native alarm notification 7101. Android logged alarm playback starting; sustained-playback polling did not catch the short sound, and the user then confirmed hearing the test alarm. The alarm expired after 30 seconds; background monitoring remained active. A final browser test at 1504×1045 and 390×844 confirmed the visible notification, no framework overlay, no console/page errors, and no horizontal overflow. Broker password scans of frontend source/build/APK assets passed. No production deployment or long-duration idle reliability is claimed.
