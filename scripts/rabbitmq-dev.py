#!/usr/bin/env python3
"""Run an isolated, loopback-only Cronos development RabbitMQ (not a system service)."""
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, unquote
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


def main():
    config = dotenv_values(ROOT / '.env')
    url = urlsplit(config.get('RABBITMQ_URL', ''))
    if url.scheme != 'amqp' or url.hostname not in ('127.0.0.1', 'localhost') or not url.username or not url.password:
        raise SystemExit('Configure a dedicated loopback amqp:// user/password/vhost in .env first.')
    binary = shutil.which('rabbitmq-server')
    if binary is None:
        for candidate in ['/opt/homebrew/opt/rabbitmq/sbin/rabbitmq-server', '/usr/local/opt/rabbitmq/sbin/rabbitmq-server']:
            if Path(candidate).is_file():
                binary = candidate
                break
    if binary is None:
        raise SystemExit('Install RabbitMQ first (macOS: brew install rabbitmq).')
    runtime = ROOT / '.runtime/rabbitmq'
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    cookie = runtime / 'cookie'
    if not cookie.exists():
        import secrets
        cookie.write_text(secrets.token_hex(32))
        cookie.chmod(0o600)
    # Readable configuration contains no password: RabbitMQ bootstrap credentials use env.
    conf = runtime / 'rabbitmq.conf'
    conf.write_text(f'listeners.tcp.1 = 127.0.0.1:{url.port or 5679}\nmanagement.tcp.ip = 127.0.0.1\nmanagement.tcp.port = 15679\n')
    plugins = runtime / 'enabled_plugins'
    plugins.write_text('[].\n')
    env_file=runtime / 'rabbitmq-env.conf'
    env_file.write_text('')
    env = {**os.environ, 'RABBITMQ_CONF_ENV_FILE':str(env_file), 'RABBITMQ_NODENAME': 'cronos@localhost',
           'RABBITMQ_MNESIA_BASE': str(runtime / 'mnesia'), 'RABBITMQ_LOG_BASE': str(runtime / 'logs'),
           'RABBITMQ_PID_FILE': str(runtime / 'rabbitmq.pid'), 'RABBITMQ_CONFIG_FILE': str(conf),
           'RABBITMQ_ENABLED_PLUGINS_FILE': str(plugins), 'RABBITMQ_DIST_PORT': '25679',
           'RABBITMQ_ERLANG_COOKIE': cookie.read_text().strip(), 'ERL_EPMD_ADDRESS': '127.0.0.1',
           'RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS': '-kernel inet_dist_use_interface {127,0,0,1}',
           'RABBITMQ_DEFAULT_USER': unquote(url.username), 'RABBITMQ_DEFAULT_PASS': unquote(url.password),
           'RABBITMQ_DEFAULT_VHOST': unquote(url.path.lstrip('/')) or '/'}
    print(f'Cronos RabbitMQ: loopback port {url.port or 5679}; Ctrl+C stops this instance.', flush=True)
    return subprocess.call([binary], env=env)


if __name__ == '__main__':
    raise SystemExit(main())
