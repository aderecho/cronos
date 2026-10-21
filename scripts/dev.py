#!/usr/bin/env python3
"""Start ASGI API/WebSocket gateway, Celery worker/beat, and frontend using existing .env/database/Redis.
Stop with Ctrl+C. Never starts or mutates your MySQL/Redis server.
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
PYTHON=ROOT/'.venv/bin/python'
processes=[]

def main():
    if not (ROOT/'.env').exists() or not PYTHON.exists():
        print('Complete the README installation steps and configure .env first.',file=sys.stderr)
        return 1
    commands=[([str(PYTHON),'-m','uvicorn','config.asgi:application','--host','127.0.0.1','--port','8100','--ws-max-size','4096','--reload'],ROOT/'backend'),([str(ROOT/'.venv/bin/celery'),'-A','config','worker','--pool=solo','--loglevel=INFO'],ROOT/'backend'),([str(ROOT/'.venv/bin/celery'),'-A','config','beat','--loglevel=INFO','--schedule='+str(ROOT/'.runtime/celerybeat')],ROOT/'backend'),(['npm','run','dev'],ROOT/'frontend')]
    (ROOT/'.runtime').mkdir(exist_ok=True)
    try:
        for command,cwd in commands:processes.append(subprocess.Popen(command,cwd=cwd,start_new_session=True))
        print('Cronos: http://127.0.0.1:9100 — press Ctrl+C to stop.')
        while all(p.poll() is None for p in processes):time.sleep(.5)
    except KeyboardInterrupt:pass
    finally:
        for p in processes:
            if p.poll() is None:os.killpg(p.pid,signal.SIGTERM)
        for p in processes:
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL)
    return 0
if __name__=='__main__':raise SystemExit(main())
