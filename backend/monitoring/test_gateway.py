"""Gateway security tests and opt-in integration tests against an actual RabbitMQ."""
import asyncio
import hashlib
import json
import os
import uuid
from unittest import skipUnless
from unittest.mock import patch
from asgiref.sync import sync_to_async
from asgiref.testing import ApplicationCommunicator
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from .gateway import NotificationGateway
from .models import DeviceRegistration, Notification, DeliveryAttempt, NotificationPreference
from .realtime import RabbitPublisher, channel_name
from .tasks import deliver_notifications


def socket(gateway, origin='https://localhost', host='localhost', query=b''):
    headers=[(b'host',host.encode())]
    if origin is not None:
        headers.append((b'origin',origin.encode()))
    return ApplicationCommunicator(gateway,{'type':'websocket','path':'/api/v1/realtime/ws','headers':headers,'query_string':query})


@override_settings(ALLOWED_HOSTS=['localhost'],CORS_ALLOWED_ORIGINS=['https://localhost'])
class GatewaySecurityTests(SimpleTestCase):
    async def test_untrusted_origin_host_and_query_credentials_rejected(self):
        for kwargs in [{'origin':'https://untrusted.example'},{'host':'untrusted.example'},{'query':b'token=do-not-log'}]:
            client=socket(NotificationGateway(),**kwargs)
            await client.send_input({'type':'websocket.connect'})
            self.assertEqual((await client.receive_output())['code'],4403)
            await client.wait()

    async def test_missing_or_cross_channel_authentication_rejected(self):
        for payload in [{}, {'type':'authenticate','token':'cronos:'+str(uuid.uuid4()),'channel':'another-user'}, {'type':'subscribe','channel':'another-user'}]:
            client=socket(NotificationGateway())
            await client.send_input({'type':'websocket.connect'})
            self.assertEqual((await client.receive_output())['type'],'websocket.accept')
            await client.send_input({'type':'websocket.receive','text':json.dumps(payload)})
            self.assertEqual((await client.receive_output())['code'],4400)
            await client.wait()

    async def test_unknown_credential_rejected_before_broker_connection(self):
        gateway=NotificationGateway()
        client=socket(gateway,origin=None)
        with patch('monitoring.realtime.authorize_device',return_value=None),patch.object(gateway,'broker') as broker:
            await client.send_input({'type':'websocket.connect'})
            await client.receive_output()
            await client.send_input({'type':'websocket.receive','text':json.dumps({'type':'authenticate','token':'cronos:'+str(uuid.uuid4())})})
            self.assertEqual((await client.receive_output())['code'],4403)
            broker.assert_not_called()
            await client.wait()

    async def test_broker_error_closes_retryably_without_logging_credentials(self):
        from unittest.mock import AsyncMock
        gateway=NotificationGateway()
        client=socket(gateway)
        with patch('monitoring.realtime.authorize_device',return_value=(1,1,'device-route')), \
             patch.object(gateway,'broker',new=AsyncMock(side_effect=RuntimeError('amqp://hidden-secret@broker'))), \
             override_settings(RABBITMQ_URL='amqp://internal@broker'), \
             self.assertLogs('monitoring.gateway',level='WARNING') as logs:
            await client.send_input({'type':'websocket.connect'})
            await client.receive_output()
            await client.send_input({'type':'websocket.receive','text':json.dumps({'type':'authenticate','token':'cronos:'+str(uuid.uuid4())})})
            self.assertEqual((await client.receive_output())['code'],1013)
            await client.wait()
        self.assertNotIn('hidden-secret',str(logs.output))


@skipUnless(os.getenv('CRONOS_BROKER_TESTS')=='1','Set CRONOS_BROKER_TESTS=1 with an isolated RabbitMQ available')
@override_settings(ALLOWED_HOSTS=['localhost'],CORS_ALLOWED_ORIGINS=['https://localhost'])
class RabbitGatewayIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.gateway=NotificationGateway()
        self.user=get_user_model().objects.create_user('gateway-test')
        self.other=get_user_model().objects.create_user('other-gateway-test')
        self.token='cronos:'+str(uuid.uuid4())
        self.other_token='cronos:'+str(uuid.uuid4())
        self.device=self.device_for(self.user,self.token)
        self.other_device=self.device_for(self.other,self.other_token)
        self.clients=[]

    def device_for(self,user,token):
        return DeviceRegistration.objects.create(user=user,token_hash=hashlib.sha256(token.encode()).hexdigest(),encrypted_token=Fernet(settings.DEVICE_ENCRYPTION_KEY.encode()).encrypt(token.encode()).decode())

    async def connect(self,token):
        client=socket(self.gateway)
        self.clients.append(client)
        await client.send_input({'type':'websocket.connect'})
        self.assertEqual((await client.receive_output(timeout=10))['type'],'websocket.accept')
        await client.send_input({'type':'websocket.receive','text':json.dumps({'type':'authenticate','token':token})})
        self.assertEqual(json.loads((await client.receive_output(timeout=10))['text']),{'type':'ready'})
        return client

    async def cleanup(self):
        for client in self.clients:
            if not client.future.done():
                await client.send_input({'type':'websocket.disconnect','code':1000})
            await client.wait(timeout=5)
        if self.gateway.connection is not None:
            await self.gateway.connection.close()

    async def test_outbox_rabbitmq_gateway_isolates_devices_and_fans_out_tabs(self):
        try:
            first=await self.connect(self.token)
            second=await self.connect(self.token)
            other=await self.connect(self.other_token)
            notification=await sync_to_async(Notification.objects.create)(user=self.user,kind='test',title='RabbitMQ delivery test')
            delivery=await sync_to_async(DeliveryAttempt.objects.create)(notification=notification,device=self.device)
            await sync_to_async(deliver_notifications)()
            for client in [first,second]:
                payload=json.loads((await client.receive_output(timeout=10))['text'])
                self.assertEqual(payload['type'],'notification')
                self.assertEqual(payload['id'],notification.pk)
                self.assertEqual(payload['title'],'RabbitMQ delivery test')
            self.assertTrue(await other.receive_nothing(timeout=.2))
            await sync_to_async(delivery.refresh_from_db)()
            self.assertEqual(delivery.state,'accepted')
            self.assertTrue(delivery.provider_id.startswith('rabbitmq:'))
        finally:
            await self.cleanup()

    async def test_disabled_preference_blocks_queued_notification(self):
        try:
            client=await self.connect(self.token)
            notification=await sync_to_async(Notification.objects.create)(user=self.user,kind='test',title='Must not arrive')
            await sync_to_async(NotificationPreference.objects.create)(user=self.user,push_enabled=False)
            def publish():
                with RabbitPublisher() as publisher:
                    publisher.publish(channel_name(self.device),{'id':notification.pk})
            await sync_to_async(publish)()
            self.assertTrue(await client.receive_nothing(timeout=.3))
        finally:
            await self.cleanup()

    async def test_client_cannot_change_its_subscription(self):
        try:
            client=await self.connect(self.token)
            await client.send_input({'type':'websocket.receive','text':json.dumps({'type':'subscribe','channel':channel_name(self.other_device)})})
            self.assertEqual((await client.receive_output(timeout=5))['code'],4400)
        finally:
            await self.cleanup()

    async def test_revocation_closes_an_existing_connection(self):
        self.gateway.AUTH_INTERVAL=.05
        try:
            client=await self.connect(self.token)
            await sync_to_async(DeviceRegistration.objects.filter(pk=self.device.pk).update)(enabled=False)
            for _ in range(5):
                event=await client.receive_output(timeout=2)
                if event['type']=='websocket.close':
                    self.assertEqual(event['code'],4403)
                    break
                await client.send_input({'type':'websocket.receive','text':'{"type":"pong"}'})
            else:
                self.fail('Revoked connection was not closed')
        finally:
            await self.cleanup()

    async def test_offline_server_alarm_reaches_assigned_device_only(self):
        from datetime import timedelta
        from django.utils import timezone
        from .models import Server,AlertRule,Membership,Incident
        from .tasks import evaluate_server
        try:
            tablet=await self.connect(self.token)
            unrelated=await self.connect(self.other_token)
            server=await sync_to_async(Server.objects.create)(name='Offline alarm test',hostname='offline.example.invalid',last_seen=timezone.now()-timedelta(seconds=100))
            await sync_to_async(AlertRule.objects.create)(server=server)
            await sync_to_async(Membership.objects.create)(server=server,user=self.user,role='viewer')
            await sync_to_async(evaluate_server)(server)
            await sync_to_async(deliver_notifications)()
            payload=json.loads((await tablet.receive_output(timeout=10))['text'])
            self.assertEqual(payload['type'],'notification')
            self.assertEqual(payload['kind'],'initial')
            self.assertEqual(payload['title'],'Offline alarm test: agent offline')
            incident=await sync_to_async(Incident.objects.get)(pk=payload['incident_id'])
            self.assertEqual(incident.rule,'agent_offline')
            self.assertTrue(await unrelated.receive_nothing(timeout=.2))
        finally:
            await self.cleanup()
