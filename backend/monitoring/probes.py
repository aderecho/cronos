"""Bounded HTTP checks pinned to a validated IP; redirects are never followed."""
import ipaddress
import socket
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
import urllib3
from django.conf import settings
from rest_framework.exceptions import ValidationError

METADATA = [ipaddress.ip_network('169.254.0.0/16'), ipaddress.ip_network('100.100.100.200/32'), ipaddress.ip_network('fd00:ec2::254/128')]

def validated_destination(url, allow_tcp=False):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in (('https','http','tcp') if allow_tcp else ('https','http')) or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError()
        host = parsed.hostname.lower().rstrip('.')
        if host in settings.PROBE_DENIED_HOSTS:
            raise ValueError()
        # Monitoring APIs must never be a target for authenticated arbitrary probes.
        if parsed.path.startswith(('/api/', '/admin')):
            raise ValueError()
        if parsed.scheme=='tcp' and (not parsed.port or parsed.path not in ('','/') or parsed.query): raise ValueError()
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if not 1 <= port <= 65535:
            raise ValueError()
        addresses = sorted({result[4][0] for result in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
        allowed = [ipaddress.ip_network(c.strip()) for c in settings.PROBE_ALLOWED_CIDRS if c.strip()]
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if getattr(ip, 'ipv4_mapped', None):
                ip = ip.ipv4_mapped
            if any(ip in network for network in METADATA) or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
                raise ValueError()
            if not ip.is_global and not any(ip in network for network in allowed):
                raise ValueError()
        if not addresses:
            raise ValueError()
        return parsed, addresses[0], port
    except (ValueError, OSError):
        raise ValidationError('Probe URL is invalid, unresolved, or outside the permitted monitoring networks.')

def check(url, timeout=5, expected_status=200, assertion_key='', assertion_value=None, allow_tcp=False):
    import json
    start = time.monotonic()
    pool = None
    result = {'success':False, 'latency_ms':None, 'status_code':None, 'error':'', 'tls_expires':None}
    try:
        parsed, ip, port = validated_destination(url, allow_tcp=allow_tcp)
        if parsed.scheme=='tcp':
            with socket.create_connection((ip,port),timeout=timeout): pass
            result['success']=True
            result['latency_ms']=(time.monotonic()-start)*1000
            return result
        common = dict(host=ip, port=port, timeout=urllib3.Timeout(total=timeout, connect=timeout, read=timeout), retries=False, maxsize=1)
        if parsed.scheme == 'https':
            pool = urllib3.HTTPSConnectionPool(**common, server_hostname=parsed.hostname, assert_hostname=parsed.hostname, cert_reqs='CERT_REQUIRED')
        else:
            pool = urllib3.HTTPConnectionPool(**common)
        path = (parsed.path or '/') + (f'?{parsed.query}' if parsed.query else '')
        response = pool.request('GET', path, headers={'Host':parsed.netloc,'User-Agent':'Cronos-Monitor/1.0'}, redirect=False, preload_content=False)
        result['status_code'] = response.status
        if parsed.scheme == 'https' and response.connection and response.connection.sock:
            cert = response.connection.sock.getpeercert()
            if cert.get('notAfter'):
                result['tls_expires'] = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert['notAfter']), timezone.utc)
        body = response.read(65537) if assertion_key else b''
        response.close()
        result['latency_ms'] = (time.monotonic() - start) * 1000
        if response.status != expected_status:
            result['error'] = f'Unexpected HTTP status {response.status}'
        elif assertion_key:
            if len(body) > 65536:
                result['error'] = 'Health response exceeds 64 KiB'
            else:
                value = json.loads(body)
                for key in assertion_key.split('.'):
                    value = value[key]
                result['success'] = value == assertion_value
                if not result['success']:
                    result['error'] = 'Health assertion failed'
        else:
            result['success'] = True
    except ValidationError:
        result['error'] = 'Destination blocked or DNS resolution failed'
    except (KeyError, TypeError, ValueError):
        result['error'] = 'Invalid health response or JSON assertion'
    except urllib3.exceptions.SSLError:
        result['error'] = 'TLS validation failed'
    except (urllib3.exceptions.TimeoutError, TimeoutError):
        result['error'] = 'Probe timed out'
    except (urllib3.exceptions.HTTPError, OSError):
        result['error'] = 'Connection failed'
    finally:
        if pool:
            pool.close()
    return result
