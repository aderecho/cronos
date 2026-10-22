import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / '.env')
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
DEBUG = os.getenv('DJANGO_DEBUG', 'false').lower() == 'true'
ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'rest_framework', 'rest_framework_simplejwt.token_blacklist', 'corsheaders', 'monitoring']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'corsheaders.middleware.CorsMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request', 'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.mysql', 'NAME': os.getenv('MYSQL_DATABASE', 'cronos'), 'USER': os.getenv('MYSQL_USER', 'cronos'), 'PASSWORD': os.environ['MYSQL_PASSWORD'], 'HOST': os.getenv('MYSQL_HOST', '127.0.0.1'), 'PORT': os.getenv('MYSQL_PORT', '3306'), 'OPTIONS': {'charset': 'utf8mb4', 'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"}, 'CONN_MAX_AGE': 60}}
AUTH_PASSWORD_VALIDATORS = [{'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'}, {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'}, {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'}, {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CORS_ALLOWED_ORIGINS = os.getenv('CORS_ALLOWED_ORIGINS', 'http://localhost:9100,http://127.0.0.1:9100,https://localhost').split(',')
REST_FRAMEWORK = {'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework_simplejwt.authentication.JWTAuthentication'], 'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'], 'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination', 'PAGE_SIZE': 100, 'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.UserRateThrottle', 'rest_framework.throttling.AnonRateThrottle'], 'DEFAULT_THROTTLE_RATES': {'user': '600/min', 'anon': '20/min', 'login': '10/min', 'agent': '120/min'}}
from datetime import timedelta
SIMPLE_JWT = {'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15), 'REFRESH_TOKEN_LIFETIME': timedelta(days=7), 'ROTATE_REFRESH_TOKENS': True, 'BLACKLIST_AFTER_ROTATION': True}
CELERY_BROKER_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
CELERY_BEAT_SCHEDULE = {'monitor': {'task': 'monitoring.tasks.monitor', 'schedule': 30.0}, 'notifications': {'task': 'monitoring.tasks.deliver_notifications', 'schedule': 15.0}, 'retention': {'task': 'monitoring.tasks.cleanup', 'schedule': 3600.0}}
CELERY_TASK_SOFT_TIME_LIMIT = 110
CELERY_TASK_TIME_LIMIT = 120
CELERY_WORKER_CONCURRENCY = 4
PROBE_ALLOWED_CIDRS = os.getenv('PROBE_ALLOWED_CIDRS', '').split(',')
PROBE_DENIED_HOSTS = os.getenv('PROBE_DENIED_HOSTS', 'metadata.google.internal,metadata,localhost').split(',')
DEVICE_ENCRYPTION_KEY = os.environ['DEVICE_ENCRYPTION_KEY']
RABBITMQ_URL = os.getenv('RABBITMQ_URL', '')
RABBITMQ_EXCHANGE = os.getenv('RABBITMQ_EXCHANGE', 'cronos.notifications')
ASGI_APPLICATION = 'config.asgi.application'
DEMO_MODE = os.getenv('CRONOS_DEMO_MODE', 'false').lower() == 'true'
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if os.getenv('TRUST_PROXY', 'false') == 'true' else None
DATA_UPLOAD_MAX_MEMORY_SIZE = 128 * 1024

CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': CELERY_BROKER_URL, 'KEY_PREFIX': 'cronos-cache'}}

# Keep production exception tracebacks visible in the systemd journal.
# Django's default console handler is filtered out when DEBUG is false.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'ERROR',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}
