from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import Incident, IncidentEvent, Notification, DeliveryAttempt, NotificationPreference
from .health import maintenance

def notify(incident, kind, title=None):
    if maintenance(incident.server):
        return False
    if incident.application_id and kind != 'recovery' and Incident.objects.filter(server=incident.server, rule='unreachable', open_key__isnull=False).exists():
        return False
    users = get_user_model().objects.filter(Q(is_superuser=True) | Q(membership__server=incident.server), is_active=True).distinct()
    created = False
    for user in users:
        n = Notification.objects.create(incident=incident, user=user, kind=kind, title=title or incident.title)
        pref, _ = NotificationPreference.objects.get_or_create(user=user)
        if pref.push_enabled:
            DeliveryAttempt.objects.bulk_create([DeliveryAttempt(notification=n, device=d) for d in user.deviceregistration_set.filter(enabled=True)])
        created = True
    if created:
        incident.last_notified = timezone.now()
        incident.save(update_fields=['last_notified'])
    return created

# Callers hold the parent Server lock; this serializes agent and worker evaluation.
def open_incident(server, rule, title, evidence=None, application=None, severity='critical'):
    key = f'{server.pk}:{application.pk if application else 0}:{rule}'
    incident, created = Incident.objects.get_or_create(open_key=key, defaults={'server':server, 'application':application, 'rule':rule, 'title':title, 'severity':severity, 'evidence':evidence or {}})
    if created:
        IncidentEvent.objects.create(incident=incident, kind='opened', message=title)
        notify(incident, 'initial')
    else:
        incident.title = title
        incident.evidence = evidence or {}
        incident.save(update_fields=['title','evidence','updated_at'])
    return incident

def resolve(server, rule, application=None):
    incident = Incident.objects.filter(open_key=f'{server.pk}:{application.pk if application else 0}:{rule}').first()
    if not incident:
        return
    was_notified = incident.last_notified is not None
    incident.state = 'resolved'
    incident.open_key = None
    incident.resolved_at = timezone.now()
    incident.save()
    IncidentEvent.objects.create(incident=incident, kind='resolved', message='Recovery confirmed by monitoring checks.')
    if was_notified:
        notify(incident, 'recovery', f'Recovered: {incident.title}')

def reminders(server):
    minutes = server.rule.reminder_minutes
    for incident in server.incidents.filter(open_key__isnull=False):
        if incident.last_notified is None:
            notify(incident, 'initial')
        elif incident.state == 'open' and incident.last_notified <= timezone.now() - timedelta(minutes=minutes):
            notify(incident, 'reminder')
