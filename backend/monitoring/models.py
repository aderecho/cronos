from django.conf import settings
from django.db import models
from django.utils import timezone

class Server(models.Model):
    name = models.CharField(max_length=120)
    hostname = models.CharField(max_length=253)
    environment = models.CharField(max_length=32, default='Production')
    os_name = models.CharField(max_length=120, blank=True)
    enabled = models.BooleanField(default=True)
    demo = models.BooleanField(default=False)
    filesystems = models.JSONField(default=list)
    required_services = models.JSONField(default=list)
    probe_url = models.URLField(max_length=500, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    last_score = models.FloatField(null=True, blank=True)
    latest_metrics = models.JSONField(default=dict)
    low_count = models.PositiveIntegerField(default=0)
    recovery_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['name']

class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=12, choices=[('admin','Admin'),('operator','Operator'),('viewer','Viewer')], default='viewer')
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user','server'], name='unique_membership')]

class AgentCredential(models.Model):
    server = models.ForeignKey(Server, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked = models.BooleanField(default=False)

class MetricSample(models.Model):
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='samples')
    sample_id = models.UUIDField()
    sampled_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    score = models.FloatField(null=True)
    data = models.JSONField()
    class Meta:
        constraints = [models.UniqueConstraint(fields=['server','sample_id'], name='unique_server_sample')]
        indexes = [models.Index(fields=['server','sampled_at'])]

class Application(models.Model):
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='applications')
    name = models.CharField(max_length=120)
    url = models.URLField(max_length=500)
    environment = models.CharField(max_length=32, default='Production')
    enabled = models.BooleanField(default=True)
    expected_status = models.PositiveIntegerField(default=200)
    assertion_key = models.CharField(max_length=120, blank=True)
    assertion_value = models.JSONField(null=True, blank=True)
    latency_threshold = models.PositiveIntegerField(default=2000)
    interval = models.PositiveIntegerField(default=30)
    timeout = models.PositiveIntegerField(default=5)
    state = models.CharField(max_length=16, default='Pending')
    fail_count = models.PositiveIntegerField(default=0)
    slow_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    last_checked = models.DateTimeField(null=True, blank=True)
    latency_ms = models.FloatField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)
    tls_expires = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['name']

class ProbeResult(models.Model):
    server = models.ForeignKey(Server, on_delete=models.CASCADE)
    application = models.ForeignKey(Application, on_delete=models.CASCADE, null=True, blank=True, related_name='checks')
    checked_at = models.DateTimeField(default=timezone.now)
    success = models.BooleanField()
    latency_ms = models.FloatField(null=True)
    status_code = models.IntegerField(null=True)
    error = models.CharField(max_length=200, blank=True)
    class Meta:
        indexes = [models.Index(fields=['server','checked_at']), models.Index(fields=['application','checked_at'])]
        ordering = ['-checked_at']

class AlertRule(models.Model):
    server = models.OneToOneField(Server, on_delete=models.CASCADE, related_name='rule')
    health_threshold = models.FloatField(default=50)
    recovery_threshold = models.FloatField(default=60)
    persistence = models.PositiveIntegerField(default=3)
    stale_seconds = models.PositiveIntegerField(default=90)
    reminder_minutes = models.PositiveIntegerField(default=30)

class Incident(models.Model):
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='incidents')
    application = models.ForeignKey(Application, on_delete=models.SET_NULL, null=True, blank=True)
    rule = models.CharField(max_length=64)
    # NULL allows many closed incidents under MySQL; a non-null key identifies one active incident.
    open_key = models.CharField(max_length=160, unique=True, null=True)
    title = models.CharField(max_length=200)
    severity = models.CharField(max_length=12, default='critical')
    state = models.CharField(max_length=16, default='open')
    evidence = models.JSONField(default=dict)
    opened_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    last_notified = models.DateTimeField(null=True)
    class Meta:
        ordering = ['-opened_at']

class IncidentEvent(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name='events')
    kind = models.CharField(max_length=32)
    message = models.TextField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['created_at']

class MaintenanceWindow(models.Model):
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='maintenance_windows')
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=200)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

class DeviceRegistration(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    encrypted_token = models.TextField()
    label = models.CharField(max_length=100, default='Android device')
    enabled = models.BooleanField(default=True)
    last_seen = models.DateTimeField(auto_now=True)

class NotificationPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    push_enabled = models.BooleanField(default=True)

class Notification(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, null=True, related_name='notifications')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    kind = models.CharField(max_length=20)
    title = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True)

class DeliveryAttempt(models.Model):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name='deliveries')
    device = models.ForeignKey(DeviceRegistration, on_delete=models.CASCADE)
    state = models.CharField(max_length=16, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    next_attempt = models.DateTimeField(default=timezone.now)
    error = models.CharField(max_length=200, blank=True)
    provider_id = models.CharField(max_length=300, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['notification','device'], name='unique_delivery')]

class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=160)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

class JobHeartbeat(models.Model):
    name = models.CharField(max_length=80, unique=True)
    last_seen = models.DateTimeField(default=timezone.now)
    detail = models.JSONField(default=dict)
