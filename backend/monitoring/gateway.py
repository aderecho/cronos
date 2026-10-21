"""ASGI WebSocket gateway. RabbitMQ credentials never leave the server."""
import asyncio
import contextlib
import json
import logging
import time
from asgiref.sync import sync_to_async
import aio_pika
from django.conf import settings
from django.http.request import split_domain_port, validate_host
from . import realtime

logger = logging.getLogger(__name__)


class NotificationGateway:
    AUTH_INTERVAL = 20
    def __init__(self):
        self.connection = None
        self.lock = asyncio.Lock()

    async def broker(self):
        async with self.lock:
            if self.connection is None or self.connection.is_closed:
                # Suppress client URL logging: connection failures must not reveal credentials.
                self.connection = await aio_pika.connect_robust(
                    settings.RABBITMQ_URL, timeout=5, reconnect_interval=3,
                    client_properties={'connection_name': 'cronos-notification-gateway'})
            return self.connection

    async def lifespan(self, receive, send):
        while True:
            event = await receive()
            if event['type'] == 'lifespan.startup':
                await send({'type': 'lifespan.startup.complete'})
            elif event['type'] == 'lifespan.shutdown':
                if self.connection is not None:
                    await self.connection.close()
                await send({'type': 'lifespan.shutdown.complete'})
                return

    async def __call__(self, scope, receive, send):
        headers = {k.lower(): v.decode('latin-1') for k, v in scope.get('headers', [])}
        host = split_domain_port(headers.get(b'host', ''))[0]
        origin = headers.get(b'origin')
        # Browsers must originate from the configured UI. Native sockets omit Origin.
        if (scope['path'] != '/api/v1/realtime/ws' or scope.get('query_string')
                or not validate_host(host, settings.ALLOWED_HOSTS)
                or (origin is not None and origin not in settings.CORS_ALLOWED_ORIGINS)):
            await send({'type': 'websocket.close', 'code': 4403})
            return
        event = await receive()
        if event['type'] != 'websocket.connect':
            return
        await send({'type': 'websocket.accept'})
        send_lock = asyncio.Lock()
        closed = False

        async def close(code):
            nonlocal closed
            async with send_lock:
                if not closed:
                    closed = True
                    await send({'type': 'websocket.close', 'code': code})

        async def emit(payload):
            async with send_lock:
                if not closed:
                    await send({'type': 'websocket.send', 'text': json.dumps(payload)})

        channel = None
        tasks = []
        try:
            first = await asyncio.wait_for(receive(), timeout=5)
            text = first.get('text', '')
            if first['type'] != 'websocket.receive' or len(text) > 1024:
                await close(4400)
                return
            auth = json.loads(text)
            if not isinstance(auth, dict) or set(auth) != {'type', 'token'} or auth['type'] != 'authenticate':
                await close(4400)
                return
            token = auth['token']
            identity = await sync_to_async(realtime.authorize_device, thread_sensitive=True)(token)
            if identity is None:
                await close(4403)
                return
            if not realtime.configured():
                await close(1013)
                return
            connection = await self.broker()
            channel = await asyncio.wait_for(connection.channel(), timeout=5)
            await channel.set_qos(prefetch_count=10)
            exchange = await channel.declare_exchange(settings.RABBITMQ_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True, timeout=5)
            queue = await channel.declare_queue(exclusive=True, auto_delete=True,
                                               arguments={'x-message-ttl': 30000, 'x-max-length': 100}, timeout=5)
            await queue.bind(exchange, routing_key=identity[2], timeout=5)
            # Install the consumer before announcing readiness to avoid losing the first alert.
            iterator = queue.iterator()
            await asyncio.wait_for(iterator.__aenter__(), timeout=5)
            await emit({'type': 'ready'})
            last_seen = time.monotonic()

            async def client_messages():
                nonlocal last_seen, closed
                while True:
                    event = await receive()
                    if event['type'] == 'websocket.disconnect':
                        closed = True
                        return
                    text = event.get('text', '')
                    if len(text) > 1024:
                        await close(4400)
                        return
                    try:
                        message = json.loads(text)
                    except (ValueError, TypeError):
                        await close(4400)
                        return
                    if not isinstance(message, dict) or message.get('type') not in ('ping', 'pong'):
                        await close(4400)
                        return
                    last_seen = time.monotonic()
                    if message['type'] == 'ping':
                        await emit({'type': 'pong'})

            async def heartbeat():
                while True:
                    await asyncio.sleep(self.AUTH_INTERVAL)
                    current = await sync_to_async(realtime.authorize_device, thread_sensitive=True)(token)
                    if current != identity:
                        await close(4403)
                        return
                    if time.monotonic() - last_seen > 65:
                        await close(4408)
                        return
                    if channel.is_closed or connection.is_closed:
                        await close(1013)
                        return
                    await emit({'type': 'ping'})

            async def relay():
                async with contextlib.AsyncExitStack() as stack:
                    stack.push_async_callback(iterator.__aexit__, None, None, None)
                    async for message in iterator:
                        async with message.process(requeue=False):
                            data = json.loads(message.body)
                            payload = await sync_to_async(realtime.authorized_notification, thread_sensitive=True)(identity, data['id'])
                            if payload is not None:
                                await emit({'type': 'notification', **payload})

            tasks = [asyncio.create_task(client_messages()), asyncio.create_task(heartbeat()), asyncio.create_task(relay())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (ValueError, TypeError, KeyError):
            await close(4400)
        except asyncio.TimeoutError:
            await close(4408)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never log exceptions/URLs/tokens supplied by AMQP or WebSocket clients.
            logger.warning('Notification connection unavailable (%s)', type(exc).__name__)
            with contextlib.suppress(Exception):
                await close(1013)
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if channel is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(channel.close(), timeout=2)


# aio-pika/aiormq include the broker URL in reconnect error logs.
logging.getLogger('aio_pika').setLevel(logging.CRITICAL)
logging.getLogger('aiormq').setLevel(logging.CRITICAL)
