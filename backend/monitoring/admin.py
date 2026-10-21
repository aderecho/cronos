from django.contrib import admin
from .models import Server, Membership, Application, AlertRule, MaintenanceWindow, Incident, AuditEvent
for model in [Server, Membership, Application, AlertRule, MaintenanceWindow, Incident, AuditEvent]:
    admin.site.register(model)
