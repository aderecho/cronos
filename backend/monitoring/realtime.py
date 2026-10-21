"""Private RabbitMQ publishing and device-scoped gateway authorization."""
import hashlib
import re
from django.conf import settings
from django.db import close_old_connections, connection
from kombu import Connection, Exchange, Producer
from .models import DeviceRegistration, Notification

TOKEN_PATTERN = re.compile(r'(?:cronos|pusher):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def configured():
    return bool(settings.RABBITMQ_URL)


def valid_token(token):
    # Existing installations keep working while migrating from the old provider.
    return isinstance(token, str) and TOKEN_PATTERN.fullmatch(token) is not None


def channel_name(device):
    return f'cronos.user.{device.user_id}.device.{device.token_hash}'


def device_identity(token):
    if not valid_token(token):
        return None
    device = DeviceRegistration.objects.select_related('user', 'user__notificationpreference').filter(
        token_hash=hashlib.sha256(token.encode()).hexdigest(), enabled=True, user__is_active=True).first()
    if device is None:
        return None
    pref = getattr(device.user, 'notificationpreference', None)
    if pref and not pref.push_enabled:
        return None
    return device


def cleanup_database_connection():
    # Keep explicit caller transactions intact, while refreshing long-lived socket DB access.
    if not connection.in_atomic_block:
        close_old_connections()


def authorize_device(token):
    """Return only identity data, safe to move across the ASGI thread boundary."""
    cleanup_database_connection()
    try:
        device = device_identity(token)
        return (device.pk, device.user_id, channel_name(device)) if device else None
    finally:
        cleanup_database_connection()


def authorized_notification(identity, notification_id):
    """Recheck access after queueing so revoked server membership cannot leak alerts."""
    cleanup_database_connection()
    try:
        device = DeviceRegistration.objects.select_related('user', 'user__notificationpreference').filter(
            pk=identity[0], user_id=identity[1], enabled=True, user__is_active=True).first()
        if device is None or channel_name(device) != identity[2]:
            return None
        pref = getattr(device.user, 'notificationpreference', None)
        if pref and not pref.push_enabled:
            return None
        notification = Notification.objects.select_related('incident__server').filter(pk=notification_id, user_id=device.user_id).first()
        if notification is None:
            return None
        if notification.incident_id:
            server = notification.incident.server
            if not server.enabled or (not device.user.is_superuser and not server.memberships.filter(user=device.user).exists()):
                return None
        return {'id': notification.pk, 'title': notification.title, 'kind': notification.kind,
                'incident_id': str(notification.incident_id or '')}
    finally:
        cleanup_database_connection()


class RabbitPublisher:
    def __init__(self):
        self.connection = Connection(settings.RABBITMQ_URL, connect_timeout=5, heartbeat=30,
                                     transport_options={'confirm_publish': True})
        self.producer = None

    def __enter__(self):
        try:
            self.connection.connect()
        except Exception:
            self.connection.release()
            raise
        exchange = Exchange(settings.RABBITMQ_EXCHANGE, type='direct', durable=True)
        self.producer = Producer(self.connection, exchange=exchange, serializer='json')
        return self

    def publish(self, routing_key, payload):
        # Outbox persists history/retries. Ephemeral gateway queues carry live events only.
        self.producer.publish(payload, routing_key=routing_key,
                              declare=[self.producer.exchange], delivery_mode=2,
                              expiration=30, retry=False, timeout=5, confirm_timeout=5)

    def __exit__(self, *args):
        self.connection.release()
