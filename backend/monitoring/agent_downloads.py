"""Public, fixed-name agent artifacts. No credentials or user files are served."""
import hashlib
import os
from pathlib import Path
from django.conf import settings
from django.http import FileResponse, JsonResponse, Http404
from django.views.decorators.http import require_GET

ARTIFACTS = {
    'update-host.sh': 'text/x-shellscript',
    'install.sh': 'text/x-shellscript',
    'cronos_agent.py': 'text/x-python',
    'requirements.txt': 'text/plain',
    'cronos-agent.service': 'text/plain',
}

def source_dir():
    return Path(os.getenv('CRONOS_AGENT_SOURCE_DIR', str(settings.BASE_DIR.parent / 'agent')))

@require_GET
def download(request, filename='install.sh'):
    root=source_dir()
    if filename=='manifest.json':
        names=['cronos_agent.py','requirements.txt','cronos-agent.service']
        if any(not (root/name).is_file() for name in names): raise Http404('Agent package unavailable.')
        response=JsonResponse({'schema_version':1,'files':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}})
    else:
        if filename not in ARTIFACTS or not (root/filename).is_file(): raise Http404('Agent artifact not found.')
        response=FileResponse((root/filename).open('rb'),content_type=ARTIFACTS[filename],as_attachment=True,filename='install-cronos-agent.sh' if filename=='install.sh' else filename)
    response['Cache-Control']='no-store'
    response['X-Content-Type-Options']='nosniff'
    return response
