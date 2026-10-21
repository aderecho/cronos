from datetime import timedelta
from django.utils import timezone

def component(value, good, critical):
    return max(0.0, min(100.0, 100 * (critical - value) / (critical - good)))

def score_health(server, data):
    components = {}
    missing = []
    for key, weight, good in [('cpu',25,60), ('ram',25,70)]:
        value = data.get(key)
        if value is None:
            missing.append(key)
        else:
            components[key] = {'health': component(value, good, 95), 'weight': weight}
    mounts = server.filesystems or ['/']
    filesystems = {fs['mount']: fs for fs in data.get('filesystems', [])}
    for key, weight in [('used_percent',25), ('inode_percent',10)]:
        values = [filesystems.get(mount, {}).get(key) for mount in mounts]
        if any(value is None for value in values):
            missing.append(key)
        else:
            components[key] = {'health': component(max(values), 75, 95), 'weight': weight}
    if server.required_services:
        services = data.get('services', {})
        if any(services.get(name) not in ['active','inactive','failed'] for name in server.required_services):
            missing.append('services')
        else:
            components['services'] = {'health': 100 * sum(services[name] == 'active' for name in server.required_services) / len(server.required_services), 'weight': 15}
    score = None if missing else sum(c['health'] * c['weight'] for c in components.values()) / sum(c['weight'] for c in components.values())
    return score, components, missing

def fresh(server, now=None):
    seconds = getattr(getattr(server, 'rule', None), 'stale_seconds', 90)
    return bool(server.last_seen and server.last_seen >= (now or timezone.now()) - timedelta(seconds=seconds))

def maintenance(server, now=None):
    now = now or timezone.now()
    return server.maintenance_windows.filter(starts_at__lte=now, ends_at__gt=now).exists()

def health_state(server):
    if not server.last_seen:
        return 'Pending'
    if not fresh(server) or server.last_score is None:
        return 'Unknown'
    if server.last_score < 50:
        return 'Critical'
    return 'Healthy' if server.last_score >= 80 else 'Warning'

def availability(server):
    if maintenance(server):
        return 'Maintenance'
    if not server.last_seen and not server.probe_url:
        return 'Pending'
    if server.probe_url:
        results = list(server.proberesult_set.filter(application__isnull=True).order_by('-checked_at')[:3])
        if results and results[0].checked_at >= timezone.now() - timedelta(seconds=90):
            if results[0].success:
                return 'Reachable'
            if len(results) == 3 and all(not r.success for r in results):
                return 'Endpoint unreachable' if fresh(server) else 'Unreachable'
    return 'Agent reporting' if fresh(server) else 'Unknown'
