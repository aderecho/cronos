from datetime import timedelta
import uuid
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from monitoring.models import Server, AlertRule, Membership, MetricSample, Application, ProbeResult, JobHeartbeat
from monitoring.health import score_health
from monitoring.incidents import open_incident

FIXTURES=[('atlas-production','10.0.1.10',28,62,71),('edge-gateway','10.0.1.11',46,58,78),('worker-01','10.0.1.21',95,93,87),('backup-node','10.0.1.30',32,43,62),('staging-api','10.0.2.10',32,54,49),('db-primary','10.0.1.12',38,68,80)]

def refresh_demo():
    if not settings.DEBUG or not settings.DEMO_MODE: return
    now=timezone.now()
    for server in Server.objects.filter(demo=True,enabled=True):
        if server.name != 'backup-node':
            server.last_seen=now
            server.save(update_fields=['last_seen'])
            MetricSample.objects.create(server=server,sample_id=uuid.uuid4(),sampled_at=now,score=server.last_score,data=server.latest_metrics)
        if server.probe_url:
            ProbeResult.objects.create(server=server,success=server.name!='backup-node',latency_ms=14 if server.name!='backup-node' else None,error='Probe timed out' if server.name=='backup-node' else '')
        for app in server.applications.all():
            app.last_checked=now
            app.save(update_fields=['last_checked'])
            ProbeResult.objects.create(server=server,application=app,success=app.state!='Down',latency_ms=app.latency_ms,status_code=200 if app.state!='Down' else None,error=app.last_error)

class Command(BaseCommand):
    help='Create clearly labelled synthetic demo data (DEBUG and CRONOS_DEMO_MODE only).'
    def handle(self,*args,**options):
        if not settings.DEBUG or not settings.DEMO_MODE: raise CommandError('Demo seeding requires DEBUG=true and CRONOS_DEMO_MODE=true.')
        with transaction.atomic():
            user,_=get_user_model().objects.get_or_create(username='demo',defaults={'is_superuser':True,'is_staff':True})
            user.set_unusable_password();user.save()
            now=timezone.now()
            for name,host,cpu,ram,disk in FIXTURES:
                server,_=Server.objects.get_or_create(name=name,demo=True,defaults={'hostname':host,'environment':'Staging' if name=='staging-api' else 'Production','os_name':'Ubuntu 24.04 LTS','filesystems':['/'],'required_services':['nginx'],'probe_url':f'https://{name}.example.com/health'})
                AlertRule.objects.get_or_create(server=server)
                Membership.objects.get_or_create(server=server,user=user,defaults={'role':'admin'})
                data={'cpu':cpu,'ram':ram,'swap':2,'load':[1.1,1.2,1.0],'filesystems':[{'mount':'/','used_percent':disk,'inode_percent':42}],'services':{'nginx':'active'}}
                score,_,_=score_health(server,data)
                server.last_score=score;server.latest_metrics=data;server.last_seen=now-timedelta(minutes=37) if name=='backup-node' else now;server.save()
                if not server.samples.exists():
                    for minute in range(120,-1,-2):
                        MetricSample.objects.create(server=server,sample_id=uuid.uuid4(),sampled_at=now-timedelta(minutes=minute),score=score,data={**data,'cpu':max(5,cpu-8+(minute%12))})
                if name=='worker-01':open_incident(server,'low_health',f'{name}: low server health',{'score':score,'threshold':50})
                if name=='backup-node':
                    for _ in range(3):ProbeResult.objects.create(server=server,success=False,error='Probe timed out')
                    open_incident(server,'unreachable',f'{name}: server unreachable',{'reason':'Probe timed out','location':'Demo worker'})
            for name,server_name,url,state,latency,error in [('API Gateway','atlas-production','https://api.example.com/health','Healthy',124,''),('Student Portal','staging-api','https://portal.example.com/health','Healthy',232,''),('Queue Service','worker-01','https://queue.example.com/health','Degraded',2400,''),('Backup Console','backup-node','https://backup.example.com/health','Down',None,'Probe timed out')]:
                server=Server.objects.get(name=server_name,demo=True)
                app,_=Application.objects.get_or_create(server=server,name=name,defaults={'url':url,'state':state,'latency_ms':latency,'last_error':error,'last_checked':now,'tls_expires':now+timedelta(days=62)})
                if not app.checks.exists():
                    for minute in range(60,-1,-2):ProbeResult.objects.create(server=server,application=app,checked_at=now-timedelta(minutes=minute),success=state!='Down',latency_ms=latency,error=error,status_code=200 if latency else None)
        self.stdout.write(self.style.SUCCESS('Demo inventory created. Explore the demo from the sign-in screen.'))
