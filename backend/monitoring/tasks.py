from datetime import timedelta
import hashlib
import logging
from celery import shared_task
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import transaction, connection
from django.utils import timezone
from .models import Server, Application, ProbeResult, Incident, MetricSample, JobHeartbeat, DeliveryAttempt
from .health import fresh
from .incidents import open_incident, resolve, reminders
from .probes import check

logger = logging.getLogger(__name__)

def record_application(app, result):
    now = timezone.now()
    ProbeResult.objects.create(server=app.server, application=app, **{k:result[k] for k in ['success','latency_ms','status_code','error']})
    app.last_checked, app.latency_ms, app.last_error = now, result['latency_ms'], result['error']
    app.tls_expires = result.get('tls_expires')
    if not result['success']:
        app.fail_count += 1
        app.success_count = app.slow_count = 0
        if app.fail_count >= 3:
            app.state = 'Down'
            open_incident(app.server, 'application_down', f'{app.name} is down', {'reason':app.last_error}, app)
    elif result['latency_ms'] > app.latency_threshold:
        app.slow_count += 1
        app.success_count = app.fail_count = 0
        if app.slow_count >= 3:
            app.state = 'Degraded'
            open_incident(app.server, 'application_slow', f'{app.name} is responding slowly', {'latency_ms':app.latency_ms}, app, 'warning')
            resolve(app.server, 'application_down', app)
    else:
        app.success_count += 1
        app.fail_count = app.slow_count = 0
        if app.success_count >= 2:
            app.state = 'Healthy'
            resolve(app.server, 'application_down', app)
            resolve(app.server, 'application_slow', app)
    if app.tls_expires:
        days = (app.tls_expires - now).total_seconds() / 86400
        if days <= 30:
            level = next((d for d in [1,7,14,30] if days <= d), 30)
            prior = Incident.objects.filter(open_key=f'{app.server_id}:{app.pk}:tls_expiry').first()
            old_level = prior.evidence.get('level', 31) if prior else 31
            incident = open_incident(app.server, 'tls_expiry', f'{app.name}: TLS certificate expires in {max(0,int(days))} days', {'days':days,'level':level}, app, 'warning')
            if prior and level < old_level:
                from .incidents import notify
                notify(incident, 'escalation')
        else:
            resolve(app.server, 'tls_expiry', app)
    app.save()

def evaluate_server(server):
    now = timezone.now()
    if server.last_seen and not fresh(server):
        open_incident(server, 'agent_offline', f'{server.name}: agent offline', {'last_seen':server.last_seen.isoformat()})
    if server.probe_url:
        r = check(server.probe_url,allow_tcp=True)
        ProbeResult.objects.create(server=server, **{k:r[k] for k in ['success','latency_ms','status_code','error']})
        results = list(server.proberesult_set.filter(application__isnull=True)[:3])
        if len(results) >= 3 and all(not x.success for x in results):
            rule = 'endpoint_unreachable' if fresh(server) else 'unreachable'
            other = 'unreachable' if fresh(server) else 'endpoint_unreachable'
            resolve(server, other)
            open_incident(server, rule, f'{server.name}: {"external endpoint unreachable" if fresh(server) else "server unreachable"}', {'reason':r['error'], 'location':'Cronos worker'})
        elif len(results) >= 2 and all(x.success for x in results[:2]):
            resolve(server, 'unreachable')
            resolve(server, 'endpoint_unreachable')
    for app in server.applications.filter(enabled=True):
        if not app.last_checked or (now - app.last_checked).total_seconds() >= app.interval:
            record_application(app, check(app.url, app.timeout, app.expected_status, app.assertion_key, app.assertion_value))
    reminders(server)

@shared_task
def monitor():
    # Advisory lock prevents overlapping scheduler invocations across all workers.
    with connection.cursor() as cursor:
        cursor.execute("SELECT GET_LOCK('cronos_monitor', 0)")
        if cursor.fetchone()[0] != 1:
            return
    try:
        JobHeartbeat.objects.update_or_create(name='scheduler', defaults={'last_seen':timezone.now()})
        if settings.DEBUG and settings.DEMO_MODE:
            from .management.commands.seed_demo import refresh_demo
            refresh_demo()
        for server_id in Server.objects.filter(enabled=True, demo=False).values_list('id', flat=True):
            try:
                with transaction.atomic():
                    server = Server.objects.select_for_update().select_related('rule').get(pk=server_id)
                    evaluate_server(server)
            except Exception:
                logger.exception('Monitoring target failed: %s', server_id)
        JobHeartbeat.objects.update_or_create(name='monitor', defaults={'last_seen':timezone.now()})
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT RELEASE_LOCK('cronos_monitor')")

@shared_task
def deliver_notifications():
    from .realtime import configured, RabbitPublisher, channel_name, valid_token
    if not configured():
        return
    for pk in list(DeliveryAttempt.objects.filter(state='pending', next_attempt__lte=timezone.now()).values_list('pk', flat=True)[:100]):
        with transaction.atomic():
            d = DeliveryAttempt.objects.select_for_update().select_related('device','notification__incident__server').get(pk=pk)
            if d.state != 'pending':
                continue
            n = d.notification
            if not n.user.is_active or d.device.user_id != n.user_id or not d.device.enabled or (n.incident_id and (not n.incident.server.enabled or (not n.user.is_superuser and not n.incident.server.memberships.filter(user=n.user).exists()))):
                d.state = 'cancelled'
                d.save()
                continue
            pref = getattr(n.user, 'notificationpreference', None)
            if pref and not pref.push_enabled:
                d.state = 'cancelled'
                d.save()
                continue
            d.attempts += 1
            try:
                token = Fernet(settings.DEVICE_ENCRYPTION_KEY.encode()).decrypt(d.device.encrypted_token.encode()).decode()
                if not valid_token(token):
                    d.device.enabled = False
                    d.device.save(update_fields=['enabled'])
                    d.state, d.error = 'failed', 'Register this device again'
                else:
                    with RabbitPublisher() as provider:
                        provider.publish(channel_name(d.device), {
                            'id': n.pk, 'title': n.title, 'incident_id': str(n.incident_id or ''), 'kind': n.kind,
                        })
                    d.provider_id = f'rabbitmq:{n.pk}:{d.device_id}'
                    d.state, d.error = 'accepted', ''
            except Exception as exc:
                d.error = type(exc).__name__
                d.state = 'failed' if d.attempts >= 5 else 'pending'
                d.next_attempt = timezone.now() + timedelta(seconds=min(3600, 30 * 2 ** d.attempts))
            d.save()
    JobHeartbeat.objects.update_or_create(name='notifications', defaults={'last_seen':timezone.now()})

@shared_task
def cleanup():
    # Raw telemetry and check history currently retained 14 days. Aggregates are a later milestone.
    cutoff = timezone.now() - timedelta(days=14)
    MetricSample.objects.filter(sampled_at__lt=cutoff).delete()
    ProbeResult.objects.filter(checked_at__lt=cutoff).delete()
