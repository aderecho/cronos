from . import realtime
import re
import hashlib
import secrets
from datetime import timedelta
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction, connection
from django.db.models import Avg, Max, Min, Count, FloatField, Value
from django.db.models.functions import TruncMinute, TruncHour, Cast, NullIf
from django.db.models.fields.json import KeyTextTransform
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, serializers, status
from rest_framework.decorators import action, api_view, permission_classes, authentication_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import *
from .serializers import *
from .health import score_health, fresh
from .incidents import open_incident, resolve

def scoped_servers(user):
    qs = Server.objects.filter(enabled=True)
    return qs if user.is_superuser else qs.filter(memberships__user=user)

def authorize(user, server, roles=('admin',)):
    if not user.is_superuser and not server.memberships.filter(user=user, role__in=roles).exists():
        raise PermissionDenied('You do not have permission to change this target.')

def audit(user, action, target, metadata=None):
    AuditEvent.objects.create(actor=user, action=action, target=str(target), metadata=metadata or {})

class LoginView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

class ServerViewSet(viewsets.ModelViewSet):
    serializer_class = ServerSerializer
    def get_queryset(self): return scoped_servers(self.request.user).select_related('rule').prefetch_related('memberships')
    def perform_create(self, serializer):
        if not self.request.user.is_superuser: raise PermissionDenied('Only administrators can register servers.')
        with transaction.atomic():
            server = serializer.save()
            AlertRule.objects.create(server=server)
            Membership.objects.create(user=self.request.user,server=server,role='admin')
            audit(self.request.user,'server.created',server.pk)
    def perform_update(self, serializer):
        authorize(self.request.user,serializer.instance)
        server=serializer.save()
        if any(k in serializer.validated_data for k in ['filesystems','required_services']):
            server.last_score=None;server.low_count=server.recovery_count=0;server.save(update_fields=['last_score','low_count','recovery_count'])
        audit(self.request.user,'server.updated',serializer.instance.pk)
    def perform_destroy(self, instance):
        authorize(self.request.user,instance)
        instance.enabled = False
        instance.save(update_fields=['enabled'])
        instance.applications.update(enabled=False)
        audit(self.request.user,'server.retired',instance.pk)
    @action(detail=True,methods=['post'],url_path='agent-credentials')
    def credentials(self,request,pk=None):
        server = self.get_object()
        authorize(request.user,server)
        if server.demo: raise ValidationError('Create a real server to enroll an agent.')
        token = secrets.token_urlsafe(48)
        with transaction.atomic():
            Server.objects.select_for_update().get(pk=server.pk)
            server.agentcredential_set.filter(revoked=False).update(revoked=True)
            AgentCredential.objects.create(server=server,token_hash=hashlib.sha256(token.encode()).hexdigest())
            audit(request.user,'agent.rotated',server.pk)
        return Response({'token':token,'server_id':server.pk,'message':'Copy now. This secret will not be shown again.'})
    @action(detail=True,methods=['get'])
    def metrics(self,request,pk=None):
        server = self.get_object()
        window = request.query_params.get('range','24h')
        if window not in ['1h','24h','7d']: raise ValidationError('Range must be 1h, 24h, or 7d.')
        hours = {'1h':1,'24h':24,'7d':168}[window]
        trunc = TruncMinute if window == '1h' else TruncHour
        qs = server.samples.filter(sampled_at__gte=timezone.now()-timedelta(hours=hours)).annotate(time=trunc('sampled_at')).values('time').annotate(cpu=Avg(Cast(NullIf(KeyTextTransform('cpu','data'),Value('null')),FloatField())), cpu_max=Max(Cast(NullIf(KeyTextTransform('cpu','data'),Value('null')),FloatField())),ram=Avg(Cast(NullIf(KeyTextTransform('ram','data'),Value('null')),FloatField())), score_min=Min('score'),score=Avg('score'),count=Count('pk')).order_by('time')
        rows=list(qs)
        if not rows: return Response([])
        step=timedelta(minutes=1) if window=='1h' else timedelta(hours=1)
        first=(timezone.now()-timedelta(hours=hours)).replace(second=0,microsecond=0)
        if window!='1h': first=first.replace(minute=0)
        end=timezone.now()
        by_time={r['time']:r for r in rows}
        filled=[]
        while first<=end:
            filled.append(by_time.get(first,{'time':first,'cpu':None,'cpu_max':None,'ram':None,'score':None,'score_min':None,'count':0}))
            first+=step
        return Response(filled)
    @action(detail=True,methods=['get','post'],url_path='memberships')
    def memberships(self,request,pk=None):
        server = self.get_object()
        authorize(request.user,server)
        if request.method == 'POST':
            user = get_object_or_404(get_user_model(),username=request.data.get('username'),is_active=True)
            role = request.data.get('role')
            if role not in ['admin','operator','viewer']: raise ValidationError('Choose admin, operator, or viewer.')
            Membership.objects.update_or_create(server=server,user=user,defaults={'role':role})
            audit(request.user,'membership.updated',server.pk,{'user_id':user.pk,'role':role})
        return Response(list(server.memberships.values('id','user__username','role')))

    @action(detail=True,methods=['delete'],url_path=r'memberships/(?P<member_id>[^/.]+)')
    def revoke_membership(self,request,pk=None,member_id=None):
        server=self.get_object()
        authorize(request.user,server)
        membership=get_object_or_404(Membership,pk=member_id,server=server)
        if membership.user_id==request.user.pk: raise ValidationError('Ask another administrator to revoke your own access.')
        audit(request.user,'membership.revoked',server.pk,{'user_id':membership.user_id})
        membership.delete()
        return Response(status=204)

class ApplicationViewSet(viewsets.ModelViewSet):
    serializer_class = ApplicationSerializer
    def get_queryset(self): return Application.objects.filter(enabled=True,server__in=scoped_servers(self.request.user)).select_related('server')
    def perform_create(self,serializer):
        server = serializer.validated_data['server']
        if not scoped_servers(self.request.user).filter(pk=server.pk).exists(): raise PermissionDenied()
        authorize(self.request.user,server)
        serializer.save()
        audit(self.request.user,'application.created',serializer.instance.pk)
    def perform_update(self,serializer):
        authorize(self.request.user,serializer.instance.server)
        server = serializer.validated_data.get('server',serializer.instance.server)
        if not scoped_servers(self.request.user).filter(pk=server.pk).exists(): raise PermissionDenied()
        authorize(self.request.user,server)
        serializer.save()
        audit(self.request.user,'application.updated',serializer.instance.pk)
    def perform_destroy(self,instance):
        authorize(self.request.user,instance.server)
        instance.enabled=False
        instance.save(update_fields=['enabled'])
        audit(self.request.user,'application.retired',instance.pk)
    @action(detail=True,methods=['get'])
    def checks(self,request,pk=None):
        app = self.get_object()
        qs = app.checks.all()[:200]
        results = [{'id':r.pk,'checked_at':r.checked_at,'success':r.success,'latency_ms':r.latency_ms,'status_code':r.status_code,'error':r.error} for r in qs]
        recent = app.checks.filter(checked_at__gte=timezone.now()-timedelta(hours=24)).aggregate(total=Count('id'),ok=Count('id',filter=models.Q(success=True)))
        return Response({'results':results,'uptime_24h':100*recent['ok']/recent['total'] if recent['total'] else None,'check_count_24h':recent['total']})

class IncidentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = IncidentSerializer
    def get_queryset(self):
        qs = Incident.objects.filter(server__in=scoped_servers(self.request.user)).select_related('server','application').prefetch_related('events__actor')
        state = self.request.query_params.get('state')
        if state == 'active': qs=qs.exclude(state='resolved')
        elif state in ['open','acknowledged','resolved']: qs=qs.filter(state=state)
        return qs
    @action(detail=True,methods=['post'])
    def acknowledge(self,request,pk=None):
        with transaction.atomic():
            incident = self.get_object()
            authorize(request.user,incident.server,('admin','operator'))
            Server.objects.select_for_update().get(pk=incident.server_id)
            incident.refresh_from_db()
            if incident.state != 'open': raise ValidationError('Only open incidents can be acknowledged.')
            incident.state='acknowledged'
            incident.acknowledged_by=request.user
            incident.save()
            IncidentEvent.objects.create(incident=incident,kind='acknowledged',message='Acknowledged; reminders stopped.',actor=request.user)
            audit(request.user,'incident.acknowledged',incident.pk)
        return Response(self.get_serializer(incident).data)
    @action(detail=True,methods=['post'])
    def comments(self,request,pk=None):
        incident=self.get_object()
        authorize(request.user,incident.server,('admin','operator'))
        message = request.data.get('message','')
        if not isinstance(message,str) or not 1<=len(message.strip())<=2000: raise ValidationError('Comment must contain 1–2000 characters.')
        IncidentEvent.objects.create(incident=incident,kind='comment',message=message.strip(),actor=request.user)
        return Response({'ok':True},status=201)

class RuleViewSet(viewsets.ModelViewSet):
    serializer_class=RuleSerializer
    http_method_names=['get','patch','head','options']
    def get_queryset(self): return AlertRule.objects.filter(server__in=scoped_servers(self.request.user))
    def perform_update(self,serializer):
        authorize(self.request.user,serializer.instance.server)
        serializer.save()
        Server.objects.filter(pk=serializer.instance.server_id).update(low_count=0,recovery_count=0)
        audit(self.request.user,'rule.updated',serializer.instance.pk)

class MaintenanceViewSet(viewsets.ModelViewSet):
    serializer_class=MaintenanceSerializer
    def get_queryset(self): return MaintenanceWindow.objects.filter(server__in=scoped_servers(self.request.user)).order_by('-starts_at')
    def perform_create(self,serializer):
        server=serializer.validated_data['server']
        if not scoped_servers(self.request.user).filter(pk=server.pk).exists(): raise PermissionDenied()
        authorize(self.request.user,server)
        serializer.save(creator=self.request.user)
        audit(self.request.user,'maintenance.created',serializer.instance.pk)
    def perform_update(self,serializer):
        authorize(self.request.user,serializer.instance.server)
        if 'server' in serializer.validated_data and serializer.validated_data['server'] != serializer.instance.server: raise ValidationError('Maintenance cannot be moved between servers.')
        serializer.save()
    def perform_destroy(self,instance):
        authorize(self.request.user,instance.server)
        audit(self.request.user,'maintenance.deleted',instance.pk)
        instance.delete()

class TelemetryView(APIView):
    permission_classes=[AllowAny]
    authentication_classes=[]
    throttle_classes=[ScopedRateThrottle]
    throttle_scope='agent'
    def post(self,request):
        token=request.headers.get('Authorization','').removeprefix('Bearer ')
        if not token or len(token)>256: raise PermissionDenied('Invalid agent credential.')
        credential=AgentCredential.objects.select_related('server').filter(token_hash=hashlib.sha256(token.encode()).hexdigest(),revoked=False,server__enabled=True,server__demo=False).first()
        if not credential: raise PermissionDenied('Invalid agent credential.')
        serializer=TelemetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d=serializer.validated_data
        with transaction.atomic():
            server=Server.objects.select_for_update().select_related('rule').get(pk=credential.server_id)
            # Recheck revocation after acquiring the same lock used for rotation.
            if not AgentCredential.objects.filter(pk=credential.pk,revoked=False).exists(): raise PermissionDenied('Agent credential revoked.')
            if server.samples.filter(sample_id=d['sample_id']).exists(): return Response({'duplicate':True})
            age=(timezone.now()-d['sampled_at']).total_seconds()
            if age < -30 or age>120: raise ValidationError('Sample timestamp must be within the last 120 seconds, with at most 30 seconds clock skew.')
            if server.last_seen and d['sampled_at']<=server.last_seen: raise ValidationError('Out-of-order sample.')
            data={k:v for k,v in d.items() if k not in ['sample_id','sampled_at']}
            score,components,missing=score_health(server,data)
            server.samples.create(sample_id=d['sample_id'],sampled_at=d['sampled_at'],score=score,data=data)
            was_fresh=fresh(server)
            server.last_seen=d['sampled_at']
            server.last_score=score
            server.latest_metrics=data
            server.os_name=data.get('os_name',server.os_name)
            rule=server.rule
            server.low_count=(server.low_count+1 if was_fresh else 1) if score is not None and score<rule.health_threshold else 0
            server.recovery_count=(server.recovery_count+1 if was_fresh else 1) if score is not None and score>=rule.recovery_threshold else 0
            server.save()
            # Agent recovery uses two distinct accepted samples.
            samples=list(server.samples.order_by('-sampled_at')[:2])
            if len(samples)==2 and (timezone.now()-samples[-1].sampled_at).total_seconds()<=rule.stale_seconds: resolve(server,'agent_offline')
            if missing: open_incident(server,'data_quality',f'{server.name}: incomplete telemetry',{'missing':missing},severity='warning')
            else: resolve(server,'data_quality')
            if server.low_count>=rule.persistence: open_incident(server,'low_health',f'{server.name}: low server health',{'score':score,'threshold':rule.health_threshold})
            elif server.recovery_count>=rule.persistence: resolve(server,'low_health')
            for name in server.required_services:
                states=[s.data.get('services',{}).get(name) for s in samples]
                if len(states)==2 and all(x in ['inactive','failed'] for x in states): open_incident(server,'service:'+name,f'{server.name}: {name} stopped')
                elif len(states)==2 and all(x=='active' for x in states): resolve(server,'service:'+name)
            full=any(fs['used_percent'] is not None and fs['used_percent']>=95 for fs in data['filesystems'] if fs['mount'] in (server.filesystems or ['/']))
            if full: open_incident(server,'disk_full',f'{server.name}: filesystem capacity critical')
            elif not any(fs.get('used_percent') is None for fs in data['filesystems']) and all(m in [fs['mount'] for fs in data['filesystems']] for m in (server.filesystems or ['/'])): resolve(server,'disk_full')
        return Response({'accepted':True,'score':score,'components':components,'missing':missing},status=201)

@api_view(['GET'])
def me(request):
    return Response({'id':request.user.pk,'username':request.user.username,'is_admin':request.user.is_superuser,'demo':settings.DEMO_MODE})

@api_view(['GET'])
def dashboard(request):
    servers=list(scoped_servers(request.user).select_related('rule'))
    ids=[s.pk for s in servers]
    incidents=Incident.objects.filter(server_id__in=ids).exclude(state='resolved').select_related('server','application').prefetch_related('events__actor')[:6]
    heartbeats={h.name:h.last_seen for h in JobHeartbeat.objects.all()}
    now=timezone.now()
    return Response({'servers':ServerSerializer(servers,many=True,context={'request':request}).data,'applications':ApplicationSerializer(Application.objects.filter(server_id__in=ids,enabled=True).select_related('server'),many=True).data,'incidents':IncidentSerializer(incidents,many=True).data,'updated_at':now,'monitoring':{'scheduler_at':heartbeats.get('scheduler'),'worker_at':heartbeats.get('monitor'),'scheduler_healthy':bool(heartbeats.get('monitor') and (now-heartbeats['monitor']).total_seconds()<90),'push_configured':realtime.configured(),'pending_deliveries':DeliveryAttempt.objects.filter(notification__user=request.user,state='pending').count()},'demo':settings.DEMO_MODE})

@api_view(['GET','PATCH'])
def preferences(request):
    pref,_=NotificationPreference.objects.get_or_create(user=request.user)
    if request.method=='PATCH':
        value=request.data.get('push_enabled')
        if not isinstance(value,bool): raise ValidationError('push_enabled must be boolean.')
        pref.push_enabled=value
        pref.save()
    return Response({'push_enabled':pref.push_enabled})

@api_view(['GET','POST'])
def devices(request):
    if request.method=='GET':
        rows=list(request.user.deviceregistration_set.values('id','label','enabled','last_seen'))
        labels={'Cronos browser (Pusher)':'Cronos browser','Cronos Android (Pusher)':'Cronos Android'}
        for row in rows:
            row['label']=labels.get(row['label'],row['label'])
        return Response(rows)
    token=request.data.get('token','')
    if not isinstance(token,str) or not realtime.valid_token(token): raise ValidationError('Invalid device token.')
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    # Device may be reused by a different authenticated account after logout.
    device,_=DeviceRegistration.objects.update_or_create(token_hash=token_hash,defaults={'user':request.user,'encrypted_token':Fernet(settings.DEVICE_ENCRYPTION_KEY.encode()).encrypt(token.encode()).decode(),'label':str(request.data.get('label','Android device'))[:100],'enabled':True})
    return Response({'id':device.pk,'channel':realtime.channel_name(device)},status=201)

@api_view(['DELETE'])
def device_remove(request,pk):
    device=get_object_or_404(DeviceRegistration,pk=pk,user=request.user)
    device.enabled=False
    device.save(update_fields=['enabled'])
    return Response(status=204)

@api_view(['POST'])
def test_notification(request):
    if not realtime.configured(): return Response({'detail':'Live notifications are not configured on the backend.'},status=503)
    active=request.user.deviceregistration_set.filter(enabled=True)
    if not active.exists(): raise ValidationError('Register this device first.')
    with transaction.atomic():
        n=Notification.objects.create(user=request.user,kind='test',title='Cronos test notification')
        DeliveryAttempt.objects.bulk_create([DeliveryAttempt(notification=n,device=d) for d in active])
    return Response({'message':'Test notification queued. Keep the app connected to receive it.'},status=202)

@api_view(['GET'])
def notifications(request):
    return Response(list(request.user.notification_set.filter(models.Q(incident__isnull=True)|models.Q(incident__server__in=scoped_servers(request.user))).order_by('-created_at').values('id','incident_id','kind','title','created_at','read_at')[:100]))

@api_view(['GET'])
@permission_classes([AllowAny])
def live(request): return Response({'status':'ok'})

@api_view(['GET'])
@permission_classes([AllowAny])
def ready(request):
    try:
        with connection.cursor() as cursor: cursor.execute('SELECT 1')
        import redis
        redis.Redis.from_url(settings.CELERY_BROKER_URL,socket_connect_timeout=1,socket_timeout=1).ping()
        heartbeat=JobHeartbeat.objects.filter(name='monitor').first()
        if not heartbeat or (timezone.now()-heartbeat.last_seen).total_seconds()>90: raise RuntimeError()
        return Response({'status':'ready'})
    except Exception:
        return Response({'status':'not_ready'},status=503)

@api_view(['POST'])
@permission_classes([AllowAny])
def demo_login(request):
    if not settings.DEBUG or not settings.DEMO_MODE: raise PermissionDenied('Demo sign-in is disabled.')
    from rest_framework_simplejwt.tokens import RefreshToken
    from .management.commands.seed_demo import refresh_demo
    user=get_object_or_404(get_user_model(),username='demo',is_active=True)
    refresh_demo()
    refresh=RefreshToken.for_user(user)
    return Response({'refresh':str(refresh),'access':str(refresh.access_token)})


class PlatformAdministrator(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [PlatformAdministrator]
    serializer_class = ManagedUserSerializer
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']
    queryset = get_user_model().objects.order_by('username')

    def perform_create(self, serializer):
        with transaction.atomic():
            user = serializer.save()
            audit(self.request.user, 'user.created', user.pk)

    def perform_update(self, serializer):
        with transaction.atomic():
            # Serialize administrator changes, including simultaneous demotions.
            list(get_user_model().objects.select_for_update().filter(is_superuser=True).order_by('pk'))
            user = serializer.save()
            audit(self.request.user, 'user.updated', user.pk, {'fields': list(serializer.validated_data)})

    @action(detail=True, methods=['get', 'put'])
    def access(self, request, pk=None):
        user = self.get_object()
        if request.method == 'PUT':
            class Assignment(serializers.Serializer):
                server = serializers.PrimaryKeyRelatedField(queryset=Server.objects.filter(enabled=True))
                role = serializers.ChoiceField(choices=['admin', 'operator', 'viewer'])
            assignments = Assignment(data=request.data, many=True)
            assignments.is_valid(raise_exception=True)
            rows = assignments.validated_data
            ids = [row['server'].pk for row in rows]
            if len(ids) != len(set(ids)):
                raise ValidationError('Assign each server only once.')
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=user.pk)
                user.membership_set.filter(server__enabled=True).exclude(server_id__in=ids).delete()
                for row in rows:
                    Membership.objects.update_or_create(user=user, server=row['server'], defaults={'role': row['role']})
                audit(request.user, 'user.access_updated', user.pk, {'server_ids': ids})
        return Response(list(user.membership_set.filter(server__enabled=True).values('server', 'role')))


@api_view(['GET'])
def realtime_config(request):
    return Response({'configured':realtime.configured(), 'websocket_path':'/api/v1/realtime/ws', 'user_id':request.user.pk})


# Device credentials authorize notification sockets only, never user APIs.
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def realtime_device_status(request):
    device = realtime.device_identity(request.headers.get('X-Cronos-Device', ''))
    if device is None:
        raise PermissionDenied('Notification device revoked or disabled.')
    return Response({'enabled':True})
