import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from django.core.asgi import get_asgi_application
http_application = get_asgi_application()
from django.conf import settings
if settings.DEBUG:
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
    http_application = ASGIStaticFilesHandler(http_application)
from monitoring.gateway import NotificationGateway
notifications = NotificationGateway()


async def application(scope, receive, send):
    if scope['type'] == 'websocket':
        await notifications(scope, receive, send)
    elif scope['type'] == 'lifespan':
        await notifications.lifespan(receive, send)
    else:
        await http_application(scope, receive, send)
