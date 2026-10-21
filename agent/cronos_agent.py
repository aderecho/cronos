#!/usr/bin/env python3
"""Outbound-only Linux telemetry agent. Credentials come from environment, never CLI args."""
import argparse
import json
import logging
import os
import platform
import re
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
import psutil
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('cronos-agent')
stopping = False

def service_state(name):
    if not re.fullmatch(r'[a-zA-Z0-9_.@-]{1,100}', name):
        return 'unknown'
    try:
        result = subprocess.run(['systemctl','is-active','--',name],capture_output=True,text=True,timeout=3,check=False)
        state=result.stdout.strip()
        return state if state in ['active','inactive','failed'] else 'unknown'
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'

def collect(mounts, services, previous_network=None, previous_time=None):
    filesystems=[]
    for mount in mounts:
        try:
            usage=psutil.disk_usage(mount)
            vfs=os.statvfs(mount)
            inodes=100*(vfs.f_files-vfs.f_ffree)/vfs.f_files if vfs.f_files else None
            filesystems.append({'mount':mount,'used_percent':usage.percent,'inode_percent':inodes})
        except OSError:
            filesystems.append({'mount':mount,'used_percent':None,'inode_percent':None})
    counters=psutil.net_io_counters(pernic=True)
    now=time.monotonic()
    network={}
    for name,c in counters.items():
        if name=='lo': continue
        prev=(previous_network or {}).get(name)
        elapsed=now-previous_time if previous_time else None
        network[name]={'bytes_sent':c.bytes_sent,'bytes_recv':c.bytes_recv,'errors_in':c.errin,'errors_out':c.errout,'sent_per_second':max(0,(c.bytes_sent-prev.bytes_sent)/elapsed) if prev and elapsed else None,'received_per_second':max(0,(c.bytes_recv-prev.bytes_recv)/elapsed) if prev and elapsed else None}
    data={'schema_version':1,'disk_io':{name:dict(c._asdict()) for name,c in (psutil.disk_io_counters(perdisk=True) or {}).items()},'uptime_seconds':max(0,time.time()-psutil.boot_time()),'sample_id':str(uuid.uuid4()),'sampled_at':datetime.now(timezone.utc).isoformat(),'cpu':psutil.cpu_percent(interval=1),'ram':psutil.virtual_memory().percent,'swap':psutil.swap_memory().percent,'load':list(os.getloadavg()),'filesystems':filesystems,'services':{name:service_state(name) for name in services},'network':network,'os_name':f'{platform.system()} {platform.release()}'}
    return data,counters,now

def stop(*_):
    global stopping
    stopping=True

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true',help='Send one sample and exit')
    parser.add_argument('--dry-run',action='store_true',help='Print one sample without sending')
    args=parser.parse_args()
    endpoint=os.getenv('CRONOS_API_URL','').rstrip('/')
    token=os.getenv('CRONOS_AGENT_TOKEN','')
    parsed=urlsplit(endpoint)
    if not args.dry_run and (not endpoint or not token):parser.error('Set CRONOS_API_URL and CRONOS_AGENT_TOKEN in the environment.')
    if not args.dry_run and parsed.scheme!='https' and not (os.getenv('CRONOS_ALLOW_LOCAL_HTTP')=='true' and parsed.hostname in ['localhost','127.0.0.1']):parser.error('Use HTTPS. Loopback HTTP is allowed only with CRONOS_ALLOW_LOCAL_HTTP=true.')
    mounts=[s.strip() for s in os.getenv('CRONOS_FILESYSTEMS','/').split(',') if s.strip()]
    services=[s.strip() for s in os.getenv('CRONOS_SERVICES','').split(',') if s.strip()]
    interval=max(10,int(os.getenv('CRONOS_INTERVAL','30')))
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    previous=None;previous_time=None
    session=requests.Session()
    while not stopping:
        started=time.monotonic()
        payload,previous,previous_time=collect(mounts,services,previous,previous_time)
        if args.dry_run:
            print(json.dumps(payload,indent=2));return
        success=False
        for attempt in range(3):
            try:
                response=session.post(endpoint+'/agent/telemetry',json=payload,headers={'Authorization':'Bearer '+token},timeout=(5,10),allow_redirects=False)
                if response.status_code in [200,201]:
                    log.info('Telemetry accepted');success=True;break
                if response.status_code in [401,403]:
                    log.error('Agent credential rejected. Re-enroll this server.');return 1
                log.warning('Telemetry rejected (HTTP %s)',response.status_code)
                if response.status_code<500:break
            except requests.RequestException:
                log.warning('Monitoring API unavailable; attempt %s',attempt+1)
            if stopping:break
            time.sleep(2**attempt)
        if args.once:return 0 if success else 1
        # Do not replay old buffered metrics as current health after a long outage.
        while not stopping and time.monotonic()-started<interval:time.sleep(min(1,interval-(time.monotonic()-started)))
    session.close()
    return 0

if __name__=='__main__':raise SystemExit(main())
