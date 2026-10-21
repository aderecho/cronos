import hashlib
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from .models import *
from .health import score_health, availability
from .tasks import record_application, evaluate_server, deliver_notifications
from .incidents import open_incident, reminders, resolve
from .probes import validated_destination

@override_settings(CACHES={'default': {'BACKEND':'django.core.cache.backends.locmem.LocMemCache'}})
class MonitoringTests(TestCase):
    def setUp(self):
        self.admin=get_user_model().objects.create_user('admin',password='testing-long-password',is_superuser=True)
        self.viewer=get_user_model().objects.create_user('viewer',password='testing-long-password')
        self.outsider=get_user_model().objects.create_user('outsider',password='testing-long-password')
        self.server=Server.objects.create(name='test-server',hostname='example.com',filesystems=['/'],required_services=['nginx'])
        AlertRule.objects.create(server=self.server)
        Membership.objects.create(user=self.viewer,server=self.server,role='viewer')
        self.token='test-agent-secret'
        AgentCredential.objects.create(server=self.server,token_hash=hashlib.sha256(self.token.encode()).hexdigest())
        self.client=APIClient()
        self.data={'cpu':10,'ram':20,'filesystems':[{'mount':'/','used_percent':25,'inode_percent':20}],'services':{'nginx':'active'}}
    def sample(self,**changes):
        data={**self.data,**changes,'sample_id':str(uuid.uuid4()),'sampled_at':timezone.now().isoformat()}
        return self.client.post('/api/v1/agent/telemetry',data,format='json',HTTP_AUTHORIZATION='Bearer '+self.token)
    def test_healthy_score(self): self.assertEqual(score_health(self.server,self.data)[0],100)
    def test_exactly_fifty(self): self.assertEqual(score_health(self.server,{**self.data,'cpu':95,'ram':95})[0],50)
    def test_missing_data_unknown(self): self.assertIsNone(score_health(self.server,{**self.data,'ram':None})[0])
    def test_unknown_service_not_healthy(self): self.assertIsNone(score_health(self.server,{**self.data,'services':{'nginx':'unknown'}})[0])
    def test_no_services_normalizes(self):
        self.server.required_services=[]
        self.assertEqual(score_health(self.server,self.data)[0],100)
    def test_accept_and_deduplicate(self):
        data={**self.data,'sample_id':str(uuid.uuid4()),'sampled_at':timezone.now().isoformat()}
        for expected in [201,200]:
            r=self.client.post('/api/v1/agent/telemetry',data,format='json',HTTP_AUTHORIZATION='Bearer '+self.token)
            self.assertEqual(r.status_code,expected,r.data)
        self.assertEqual(MetricSample.objects.count(),1)
    def test_invalid_agent(self): self.assertEqual(self.client.post('/api/v1/agent/telemetry',{},format='json').status_code,403)
    def test_reject_old_sample(self):
        d={**self.data,'sample_id':str(uuid.uuid4()),'sampled_at':(timezone.now()-timedelta(minutes=4)).isoformat()}
        self.assertEqual(self.client.post('/api/v1/agent/telemetry',d,format='json',HTTP_AUTHORIZATION='Bearer '+self.token).status_code,400)
    def test_exact_fifty_does_not_alert(self):
        for _ in range(3):self.assertEqual(self.sample(cpu=95,ram=95).status_code,201)
        self.assertFalse(Incident.objects.filter(rule='low_health').exists())
    def test_low_health_persistence_and_recovery(self):
        for _ in range(2):self.sample(cpu=100,ram=100,services={'nginx':'failed'})
        self.assertFalse(Incident.objects.filter(rule='low_health').exists())
        self.sample(cpu=100,ram=100,services={'nginx':'failed'})
        self.assertEqual(Incident.objects.filter(rule='low_health',state='open').count(),1)
        for _ in range(3):self.sample()
        self.assertEqual(Incident.objects.get(rule='low_health').state,'resolved')
    def test_service_fails_independently(self):
        for _ in range(2):self.sample(services={'nginx':'inactive'})
        self.server.refresh_from_db()
        self.assertGreater(self.server.last_score,50)
        self.assertTrue(Incident.objects.filter(rule='service:nginx').exists())
    def test_incomplete_samples_open_data_incident(self):
        self.assertEqual(self.sample(ram=None).status_code,201)
        self.assertTrue(Incident.objects.filter(rule='data_quality').exists())
    def test_viewer_cannot_change_server(self):
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.patch(f'/api/v1/servers/{self.server.pk}',{'name':'changed'},format='json').status_code,403)
    def test_outsider_cannot_see_server_metrics(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(f'/api/v1/servers/{self.server.pk}/metrics').status_code,404)
        self.assertEqual(self.client.get('/api/v1/dashboard').data['servers'],[])
    def test_agent_cannot_access_user_api(self):
        self.assertEqual(self.client.get('/api/v1/servers',HTTP_AUTHORIZATION='Bearer '+self.token).status_code,401)
    def test_acknowledgement_stops_reminders(self):
        i=open_incident(self.server,'low_health','Low health')
        Membership.objects.filter(user=self.viewer).update(role='operator')
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.post(f'/api/v1/incidents/{i.pk}/acknowledge').status_code,200)
        i.refresh_from_db();self.assertEqual(i.state,'acknowledged')
        count=Notification.objects.count();reminders(self.server);self.assertEqual(Notification.objects.count(),count)
    def test_incident_deduplication(self):
        for _ in range(3):open_incident(self.server,'low_health','Low health')
        self.assertEqual(Incident.objects.count(),1)
        self.assertEqual(Notification.objects.filter(user=self.admin).count(),1)
    def test_maintenance_suppresses_and_catches_up(self):
        m=MaintenanceWindow.objects.create(server=self.server,starts_at=timezone.now()-timedelta(minutes=1),ends_at=timezone.now()+timedelta(minutes=1),reason='test')
        i=open_incident(self.server,'low_health','Low health');self.assertEqual(Notification.objects.count(),0)
        m.ends_at=timezone.now()-timedelta(seconds=1);m.save();reminders(self.server)
        self.assertGreater(Notification.objects.count(),0)
    def test_suppressed_incident_has_no_recovery_notice(self):
        MaintenanceWindow.objects.create(server=self.server,starts_at=timezone.now()-timedelta(minutes=1),ends_at=timezone.now()+timedelta(minutes=1),reason='test')
        open_incident(self.server,'low_health','Low health');resolve(self.server,'low_health')
        self.assertEqual(Notification.objects.count(),0)
    def test_offline_server_queues_one_alarm_for_assigned_active_devices(self):
        def device_for(user, enabled=True):
            token='cronos:'+str(uuid.uuid4())
            return DeviceRegistration.objects.create(user=user,enabled=enabled,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                encrypted_token=Fernet(settings.DEVICE_ENCRYPTION_KEY.encode()).encrypt(token.encode()).decode())
        from cryptography.fernet import Fernet
        tablet=device_for(self.viewer)
        disabled=device_for(self.viewer,False)
        outsider=device_for(self.outsider)
        self.server.last_seen=timezone.now()-timedelta(seconds=self.server.rule.stale_seconds-1)
        self.server.save()
        evaluate_server(self.server)
        self.assertFalse(Incident.objects.filter(server=self.server,rule='agent_offline').exists())
        self.server.last_seen=timezone.now()-timedelta(seconds=self.server.rule.stale_seconds+1)
        self.server.save()
        evaluate_server(self.server)
        evaluate_server(self.server)
        incident=Incident.objects.get(server=self.server,rule='agent_offline')
        self.assertEqual(DeliveryAttempt.objects.filter(notification__incident=incident,device=tablet).count(),1)
        self.assertFalse(DeliveryAttempt.objects.filter(notification__incident=incident,device__in=[disabled,outsider]).exists())
        self.assertTrue(Notification.objects.filter(incident=incident,user=self.admin).exists())

    @patch('monitoring.tasks.check')
    def test_stale_agent_but_reachable_host(self,mock):
        self.server.last_seen=timezone.now()-timedelta(minutes=3);self.server.probe_url='https://example.com';self.server.save()
        mock.return_value={'success':True,'latency_ms':10,'status_code':200,'error':'','tls_expires':None}
        evaluate_server(self.server)
        self.assertTrue(Incident.objects.filter(rule='agent_offline').exists())
        self.assertFalse(Incident.objects.filter(rule='unreachable').exists())
        self.assertEqual(availability(self.server),'Reachable')
    @patch('monitoring.tasks.check')
    def test_unreachable_after_three_failures(self,mock):
        self.server.last_seen=timezone.now()-timedelta(minutes=3);self.server.probe_url='https://example.com';self.server.save()
        mock.return_value={'success':False,'latency_ms':None,'status_code':None,'error':'Probe timed out','tls_expires':None}
        for _ in range(3):evaluate_server(self.server)
        self.assertEqual(Incident.objects.filter(rule='unreachable').count(),1)
        self.assertEqual(availability(self.server),'Unreachable')
    def test_application_failure_and_recovery(self):
        app=Application.objects.create(server=self.server,name='App',url='https://example.com')
        failure={'success':False,'latency_ms':None,'status_code':None,'error':'Probe timed out','tls_expires':None}
        for _ in range(3):record_application(app,failure)
        self.assertEqual(app.state,'Down')
        success={'success':True,'latency_ms':100,'status_code':200,'error':'','tls_expires':None}
        for _ in range(2):record_application(app,success)
        self.assertEqual(app.state,'Healthy');self.assertEqual(Incident.objects.get(rule='application_down').state,'resolved')
    def test_correlated_outage_suppresses_child_notification(self):
        open_incident(self.server,'unreachable','Server unreachable')
        count=Notification.objects.count()
        app=Application.objects.create(server=self.server,name='App',url='https://example.com')
        open_incident(self.server,'application_down','App down',application=app)
        self.assertEqual(Notification.objects.count(),count)
    @patch('monitoring.probes.socket.getaddrinfo',return_value=[(2,1,6,'',('169.254.169.254',80))])
    def test_metadata_probe_blocked(self,_):
        with self.assertRaises(ValidationError):validated_destination('http://example.com/latest')
    @patch('monitoring.probes.socket.getaddrinfo',return_value=[(2,1,6,'',('10.0.0.1',80))])
    def test_private_probe_blocked_by_default(self,_):
        with self.assertRaises(ValidationError):validated_destination('http://example.com/health')
    @override_settings(PROBE_ALLOWED_CIDRS=['10.0.0.0/24'])
    @patch('monitoring.probes.socket.getaddrinfo',return_value=[(2,1,6,'',('10.0.0.1',80))])
    def test_authorized_private_probe_allowed(self,_): self.assertEqual(validated_destination('http://example.com/health')[1],'10.0.0.1')
    def test_url_credentials_rejected(self):
        with self.assertRaises(ValidationError):validated_destination('https://user:password@example.com/health')
    @override_settings(DEBUG=False,DEMO_MODE=True)
    def test_demo_login_disabled_in_production(self):self.assertEqual(self.client.post('/api/v1/auth/demo').status_code,403)
    def test_metrics_use_mysql_aggregation(self):
        self.sample();self.client.force_authenticate(self.viewer)
        r=self.client.get(f'/api/v1/servers/{self.server.pk}/metrics?range=24h')
        self.assertEqual(r.status_code,200,r.data);self.assertEqual(next(p for p in r.data if p['count'])['cpu'],10)
    def test_invalid_maintenance_rejected(self):
        self.client.force_authenticate(self.admin)
        r=self.client.post('/api/v1/maintenance-windows',{'server':self.server.pk,'starts_at':timezone.now().isoformat(),'ends_at':(timezone.now()-timedelta(hours=1)).isoformat(),'reason':'bad'},format='json')
        self.assertEqual(r.status_code,400)
    def test_retired_server_rejects_telemetry(self):
        self.server.enabled=False;self.server.save();self.assertEqual(self.sample().status_code,403)
    @patch('monitoring.probes.socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))])
    def test_tcp_probe_configuration(self,_):
        parsed,ip,port=validated_destination('tcp://example.com:443',allow_tcp=True)
        self.assertEqual(parsed.scheme,'tcp');self.assertEqual(port,443)
        with self.assertRaises(ValidationError):validated_destination('tcp://example.com:443')
    def test_application_cannot_move_between_scopes(self):
        other=Server.objects.create(name='other',hostname='other.example.com')
        app=Application.objects.create(server=self.server,name='app',url='https://example.com')
        self.client.force_authenticate(self.admin)
        r=self.client.patch(f'/api/v1/applications/{app.pk}',{'server':other.pk},format='json')
        self.assertEqual(r.status_code,400)
    def test_counter_resets_after_stale_telemetry(self):
        self.server.low_count=2;self.server.last_seen=timezone.now()-timedelta(minutes=10);self.server.save()
        self.sample(cpu=99,ram=99,services={'nginx':'failed'})
        self.server.refresh_from_db()
        self.assertEqual(self.server.low_count,1)
        self.assertFalse(Incident.objects.filter(rule='low_health').exists())
    def test_history_includes_explicit_gap_buckets(self):
        self.sample();self.client.force_authenticate(self.viewer)
        points=self.client.get(f'/api/v1/servers/{self.server.pk}/metrics?range=1h').data
        self.assertTrue(any(p['count']==0 and p['cpu'] is None for p in points))
    def test_member_revocation_removes_access(self):
        self.client.force_authenticate(self.admin)
        membership=Membership.objects.get(user=self.viewer,server=self.server)
        self.assertEqual(self.client.delete(f'/api/v1/servers/{self.server.pk}/memberships/{membership.pk}').status_code,204)
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(f'/api/v1/servers/{self.server.pk}').status_code,404)
    def test_device_tokens_encrypted_and_scoped(self):
        self.client.force_authenticate(self.viewer)
        token='pusher:'+str(uuid.uuid4())
        r=self.client.post('/api/v1/devices',{'token':token},format='json')
        self.assertEqual(r.status_code,201)
        device=DeviceRegistration.objects.get(pk=r.data['id'])
        self.assertNotIn(token,device.encrypted_token)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.delete(f'/api/v1/devices/{device.pk}').status_code,404)
    @override_settings(RABBITMQ_URL='amqp://internal-user:internal-secret@broker/cronos')
    def test_gateway_configuration_exposes_no_broker_credentials(self):
        self.assertEqual(self.client.get('/api/v1/realtime/config').status_code,401)
        self.client.force_authenticate(self.viewer)
        config=self.client.get('/api/v1/realtime/config')
        self.assertTrue(config.data['configured'])
        self.assertEqual(config.data['websocket_path'],'/api/v1/realtime/ws')
        self.assertNotIn('internal-secret',str(config.data))
        self.assertNotIn('broker',str(config.data))
        self.assertNotIn('key',config.data)

    @override_settings(RABBITMQ_URL='amqp://internal-user:secret@broker/cronos')
    @patch('monitoring.realtime.RabbitPublisher')
    def test_rabbitmq_delivery_retries_and_preferences(self, publisher):
        provider=publisher.return_value.__enter__.return_value
        self.client.force_authenticate(self.viewer)
        registered=self.client.post('/api/v1/devices',{'token':'cronos:'+str(uuid.uuid4())},format='json')
        device=DeviceRegistration.objects.get(pk=registered.data['id'])
        notification=Notification.objects.create(user=self.viewer,kind='test',title='Test')
        delivery=DeliveryAttempt.objects.create(notification=notification,device=device)
        provider.publish.side_effect=RuntimeError('temporary failure')
        deliver_notifications()
        delivery.refresh_from_db()
        self.assertEqual(delivery.state,'pending')
        self.assertEqual(delivery.attempts,1)
        provider.publish.side_effect=None
        delivery.next_attempt=timezone.now();delivery.save()
        deliver_notifications()
        delivery.refresh_from_db()
        self.assertEqual(delivery.state,'accepted')
        self.assertTrue(delivery.provider_id.startswith('rabbitmq:'))
        args=provider.publish.call_args.args
        self.assertEqual(args[0],registered.data['channel'])
        self.assertEqual(args[1]['id'],notification.pk)
        NotificationPreference.objects.create(user=self.viewer,push_enabled=False)
        blocked=DeliveryAttempt.objects.create(notification=Notification.objects.create(user=self.viewer,kind='test',title='Disabled'),device=device)
        provider.reset_mock()
        deliver_notifications()
        blocked.refresh_from_db()
        self.assertEqual(blocked.state,'cancelled')
        provider.publish.assert_not_called()

    @override_settings(RABBITMQ_URL='')
    def test_missing_notification_configuration(self):
        self.client.force_authenticate(self.viewer)
        self.assertFalse(self.client.get('/api/v1/realtime/config').data['configured'])
        self.assertEqual(self.client.post('/api/v1/notifications/test',{},format='json').status_code,503)

    def test_invalid_rule_recovery_rejected(self):
        self.client.force_authenticate(self.admin)
        r=self.client.patch(f'/api/v1/alert-rules/{self.server.rule.pk}',{'health_threshold':70,'recovery_threshold':60},format='json')
        self.assertEqual(r.status_code,400)

from django.test import SimpleTestCase
from pathlib import Path
import json
import os
import subprocess
import tempfile
from .agent_downloads import source_dir

class AgentDistributionTests(SimpleTestCase):
    def test_installer_download_has_no_auth_requirement(self):
        response=self.client.get('/api/v1/agent/install.sh')
        self.assertEqual(response.status_code,200)
        body=b''.join(response.streaming_content)
        self.assertTrue(body.startswith(b'#!/usr/bin/env bash'))
        self.assertIn('install-cronos-agent.sh',response['Content-Disposition'])
    def test_manifest_matches_agent_artifacts(self):
        response=self.client.get('/api/v1/agent/files/manifest.json')
        self.assertEqual(response.status_code,200)
        for name,digest in response.json()['files'].items():
            self.assertEqual(hashlib.sha256((source_dir()/name).read_bytes()).hexdigest(),digest)
    def test_only_fixed_public_artifacts_can_be_downloaded(self):
        self.assertEqual(self.client.get('/api/v1/agent/files/.env').status_code,404)
        self.assertEqual(self.client.get('/api/v1/agent/files/settings.py').status_code,404)
    def test_downloaded_agent_matches_local_source(self):
        response=self.client.get('/api/v1/agent/files/cronos_agent.py')
        self.assertEqual(b''.join(response.streaming_content),(source_dir()/'cronos_agent.py').read_bytes())
    def test_installer_rejects_remote_plaintext_http(self):
        result=subprocess.run(['bash',str(source_dir()/'install.sh'),'--check','--api-url','http://example.com/api/v1'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('https://YOUR-CRONOS-HOST',result.stderr)
    def test_installer_check_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage=Path(tmp)
            names=['cronos_agent.py','requirements.txt','cronos-agent.service']
            manifest={'files':{name:hashlib.sha256((source_dir()/name).read_bytes()).hexdigest() for name in names}}
            for name in names:(stage/name).write_bytes((source_dir()/name).read_bytes())
            (stage/'manifest.json').write_text(json.dumps(manifest))
            wget=stage/'wget'
            wget.write_text('#!/usr/bin/env python3\nimport os,shutil,sys\nfrom pathlib import Path\na=sys.argv\nshutil.copyfile(Path(os.environ["CRONOS_FIXTURE"])/a[-1].rsplit("/",1)[-1],a[a.index("-O")+1])\n')
            wget.chmod(0o755)
            env={**os.environ,'PATH':str(stage)+os.pathsep+os.environ['PATH'],'CRONOS_FIXTURE':str(stage)}
            args=['bash',str(source_dir()/'install.sh'),'--check','--api-url','https://monitor.example.com/api/v1','--services','nginx,mysql','--filesystems','/,/data']
            good=subprocess.run(args,env=env,capture_output=True,text=True)
            self.assertEqual(good.returncode,0,good.stderr)
            self.assertIn('No packages, users, files, or services were installed',good.stdout)
            (stage/'cronos_agent.py').write_text('tampered')
            bad=subprocess.run(args,env=env,capture_output=True,text=True)
            self.assertNotEqual(bad.returncode,0)
            self.assertIn('checksum mismatch',bad.stderr)


@override_settings(CACHES={'default': {'BACKEND':'django.core.cache.backends.locmem.LocMemCache'}})
class UserManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user('manager', password='Strong-secret-829!', is_superuser=True)
        self.member = get_user_model().objects.create_user('member', password='Strong-secret-829!')
        self.server = Server.objects.create(name='Assigned', hostname='example.com')
        AlertRule.objects.create(server=self.server)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_create_edit_password_and_deactivate(self):
        result = self.client.post('/api/v1/users', {'username':'new-member', 'password':'Reliable-password-482!', 'email':'user@example.com'}, format='json')
        self.assertEqual(result.status_code, 201, result.data)
        self.assertNotIn('password', result.data)
        user = get_user_model().objects.get(pk=result.data['id'])
        self.assertTrue(user.check_password('Reliable-password-482!'))
        result = self.client.patch(f'/api/v1/users/{user.pk}', {'password':'Changed-password-493!', 'is_active':False}, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        user.refresh_from_db()
        self.assertTrue(user.check_password('Changed-password-493!'))
        self.assertFalse(user.is_active)
        self.assertEqual(self.client.post('/api/v1/auth/login', {'username':user.username,'password':'Changed-password-493!'}, format='json').status_code, 401)
        self.assertTrue(AuditEvent.objects.filter(action='user.updated',target=str(user.pk)).exists())

    def test_non_admin_denied_even_server_admin(self):
        Membership.objects.create(user=self.member, server=self.server, role='admin')
        self.client.force_authenticate(self.member)
        for path in ['/api/v1/users', f'/api/v1/users/{self.admin.pk}', f'/api/v1/users/{self.member.pk}/access']:
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.patch(f'/api/v1/users/{self.member.pk}', {'is_admin':True}, format='json').status_code, 403)
        self.assertEqual(self.client.post('/api/v1/users', {'username':'forbidden'}, format='json').status_code,403)

    def test_self_lockout_rejected(self):
        for data in [{'is_admin':False}, {'is_active':False}]:
            self.assertEqual(self.client.patch(f'/api/v1/users/{self.admin.pk}', data, format='json').status_code,400)

    def test_password_and_duplicate_validation(self):
        for data in [{'username':'missing'}, {'username':'weak','password':'123'}, {'username':'member','password':'Reliable-password-482!'}]:
            self.assertEqual(self.client.post('/api/v1/users',data,format='json').status_code,400)

    def test_assign_change_revoke_and_validate_access(self):
        path = f'/api/v1/users/{self.member.pk}/access'
        for role in ['viewer', 'operator', 'admin']:
            result = self.client.put(path,[{'server':self.server.pk,'role':role}],format='json')
            self.assertEqual(result.status_code,200,result.data)
            self.assertEqual(Membership.objects.get(user=self.member).role,role)
        for rows in [[{'server':self.server.pk,'role':'owner'}],[{'server':self.server.pk,'role':'viewer'}]*2,[{'server':999999,'role':'viewer'}]]:
            self.assertEqual(self.client.put(path,rows,format='json').status_code,400)
            self.assertEqual(Membership.objects.get(user=self.member).role,'admin')
        self.client.force_authenticate(self.member)
        self.assertEqual(len(self.client.get('/api/v1/servers').data['results']),1)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.put(path,[],format='json').status_code,200)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.get('/api/v1/servers').data['results'],[])

@override_settings(CACHES={'default': {'BACKEND':'django.core.cache.backends.locmem.LocMemCache'}},RABBITMQ_URL='amqp://internal-user:secret@broker/cronos')
class TabletNotificationTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('tablet-user',password='Testing-device-843!')
        self.token='pusher:'+str(uuid.uuid4())
        self.client=APIClient()
        self.client.force_authenticate(self.user)
        result=self.client.post('/api/v1/devices',{'token':self.token},format='json')
        self.channel=result.data['channel']
        self.device=DeviceRegistration.objects.get(pk=result.data['id'])
        self.client.force_authenticate(None)
        self.headers={'HTTP_X_CRONOS_DEVICE':self.token}

    def test_device_identity_cannot_use_user_apis(self):
        from .realtime import authorize_device
        identity=authorize_device(self.token)
        self.assertEqual(identity[:2],(self.device.pk,self.user.pk))
        self.assertEqual(identity[2],self.channel)
        self.assertIsNone(authorize_device('cronos:'+str(uuid.uuid4())))
        self.assertEqual(self.client.get('/api/v1/users',**self.headers).status_code,401)
        self.assertEqual(self.client.get('/api/v1/dashboard',**self.headers).status_code,401)

    def test_gateway_rechecks_membership_before_forwarding(self):
        from .realtime import authorize_device,authorized_notification
        server=Server.objects.create(name='Private',hostname='example.com')
        membership=Membership.objects.create(user=self.user,server=server,role='viewer')
        incident=Incident.objects.create(server=server,rule='test',title='Private incident')
        notification=Notification.objects.create(user=self.user,incident=incident,kind='initial',title=incident.title)
        identity=authorize_device(self.token)
        self.assertEqual(authorized_notification(identity,notification.pk)['id'],notification.pk)
        membership.delete()
        self.assertIsNone(authorized_notification(identity,notification.pk))

    def test_status_rejects_disabled_preference_revoked_device_and_inactive_user(self):
        path='/api/v1/realtime/device-status'
        self.assertEqual(self.client.post(path,{},format='json',**self.headers).status_code,200)
        pref=NotificationPreference.objects.create(user=self.user,push_enabled=False)
        self.assertEqual(self.client.post(path,{},format='json',**self.headers).status_code,403)
        pref.push_enabled=True;pref.save()
        self.user.is_active=False;self.user.save()
        self.assertEqual(self.client.post(path,{},format='json',**self.headers).status_code,403)
        self.user.is_active=True;self.user.save()
        self.device.enabled=False;self.device.save()
        self.assertEqual(self.client.post(path,{},format='json',**self.headers).status_code,403)

    def test_unknown_device_credential_is_denied(self):
        for token in ['', 'pusher:'+str(uuid.uuid4()), 'not-a-device']:
            self.assertEqual(self.client.post('/api/v1/realtime/device-status',{},format='json',HTTP_X_CRONOS_DEVICE=token).status_code,403)
