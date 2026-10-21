import math
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers
from .models import Server, Application, Incident, IncidentEvent, MaintenanceWindow, AlertRule, ProbeResult, Membership
from .health import health_state, availability, fresh, score_health, maintenance
from .probes import validated_destination

class ServerSerializer(serializers.ModelSerializer):
    probe_url = serializers.CharField(max_length=500,allow_blank=True,required=False)
    health_state = serializers.SerializerMethodField()
    availability = serializers.SerializerMethodField()
    fresh = serializers.SerializerMethodField()
    incident_count = serializers.SerializerMethodField()
    components = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    class Meta:
        model = Server
        fields = ['id','name','hostname','environment','os_name','enabled','demo','filesystems','required_services','probe_url','last_seen','last_score','latest_metrics','health_state','availability','fresh','incident_count','components','role']
        read_only_fields = ['demo','last_seen','last_score','latest_metrics']
    def get_role(self, obj):
        user = self.context['request'].user
        return 'admin' if user.is_superuser else obj.memberships.get(user=user).role
    def get_health_state(self, obj): return health_state(obj)
    def get_availability(self, obj): return availability(obj)
    def get_fresh(self, obj): return fresh(obj)
    def get_incident_count(self, obj): return obj.incidents.filter(open_key__isnull=False).count()
    def get_components(self, obj): return score_health(obj, obj.latest_metrics)[1] if obj.latest_metrics else {}
    def validate_probe_url(self, value):
        if value: validated_destination(value,allow_tcp=True)
        return value
    def validate_filesystems(self, value):
        if not isinstance(value,list) or len(value) > 32 or any(not isinstance(x,str) or not x.startswith('/') or len(x)>200 for x in value) or len(set(value)) != len(value):
            raise serializers.ValidationError('Use a unique list of up to 32 absolute mount paths.')
        return value
    def validate_required_services(self, value):
        import re
        if not isinstance(value,list) or len(value)>32 or any(not isinstance(x,str) or not re.fullmatch(r'[a-zA-Z0-9_.@-]{1,100}',x) for x in value) or len(set(value)) != len(value):
            raise serializers.ValidationError('Use a unique list of up to 32 systemd service names.')
        return value

class ApplicationSerializer(serializers.ModelSerializer):
    server_name = serializers.CharField(source='server.name', read_only=True)
    effective_state = serializers.SerializerMethodField()
    class Meta:
        model = Application
        fields = ['id','server','server_name','name','url','environment','enabled','expected_status','assertion_key','assertion_value','latency_threshold','interval','timeout','state','effective_state','last_checked','latency_ms','last_error','tls_expires']
        read_only_fields = ['state','last_checked','latency_ms','last_error','tls_expires']
    def get_effective_state(self, obj):
        if maintenance(obj.server): return 'Maintenance'
        if obj.last_checked and (timezone.now()-obj.last_checked).total_seconds() > max(90, obj.interval*3): return 'Unknown'
        return obj.state
    def validate_url(self, value):
        validated_destination(value)
        return value
    def validate(self, attrs):
        if self.instance and 'server' in attrs and attrs['server'].pk != self.instance.server_id:
            raise serializers.ValidationError('An application cannot be moved between servers. Register a new check to preserve scoped history.')
        for key, low, high in [('timeout',1,10),('interval',30,3600),('expected_status',100,599),('latency_threshold',1,60000)]:
            if key in attrs and not low<=attrs[key]<=high:
                raise serializers.ValidationError({key:f'Must be between {low} and {high}.'})
        return attrs

class EventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source='actor.username', read_only=True, default='Monitoring')
    class Meta:
        model = IncidentEvent
        fields = ['id','kind','message','actor_name','created_at']

class IncidentSerializer(serializers.ModelSerializer):
    server_name = serializers.CharField(source='server.name',read_only=True)
    application_name = serializers.CharField(source='application.name', read_only=True, default=None)
    events = EventSerializer(many=True, read_only=True)
    class Meta:
        model = Incident
        fields = ['id','server','server_name','application','application_name','rule','title','severity','state','evidence','opened_at','updated_at','resolved_at','events']

class MaintenanceSerializer(serializers.ModelSerializer):
    server_name = serializers.CharField(source='server.name',read_only=True)
    class Meta:
        model = MaintenanceWindow
        fields = ['id','server','server_name','starts_at','ends_at','reason']
    def validate(self, attrs):
        start = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        end = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        if not start or not end or end <= start: raise serializers.ValidationError('End must follow start.')
        return attrs

class RuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertRule
        fields = ['id','server','health_threshold','recovery_threshold','persistence','stale_seconds','reminder_minutes']
        read_only_fields = ['server']
    def validate(self, attrs):
        low = attrs.get('health_threshold', self.instance.health_threshold)
        high = attrs.get('recovery_threshold', self.instance.recovery_threshold)
        if not 0 <= low < high <= 100: raise serializers.ValidationError('Recovery must be above the health threshold, between 0 and 100.')
        for name, low_bound, high_bound in [('persistence',1,10),('stale_seconds',60,3600),('reminder_minutes',1,1440)]:
            if name in attrs and not low_bound<=attrs[name]<=high_bound: raise serializers.ValidationError({name:'Outside permitted range.'})
        return attrs

class FilesystemSerializer(serializers.Serializer):
    mount = serializers.CharField(max_length=200)
    used_percent = serializers.FloatField(min_value=0,max_value=100,allow_null=True)
    inode_percent = serializers.FloatField(min_value=0,max_value=100,allow_null=True)

class TelemetrySerializer(serializers.Serializer):
    schema_version = serializers.IntegerField(min_value=1,max_value=1,required=False,default=1)
    disk_io = serializers.DictField(required=False)
    uptime_seconds = serializers.FloatField(min_value=0,required=False)
    sample_id = serializers.UUIDField()
    sampled_at = serializers.DateTimeField()
    cpu = serializers.FloatField(min_value=0,max_value=100,allow_null=True)
    ram = serializers.FloatField(min_value=0,max_value=100,allow_null=True)
    swap = serializers.FloatField(min_value=0,max_value=100,allow_null=True,required=False)
    load = serializers.ListField(child=serializers.FloatField(min_value=0), min_length=3, max_length=3, required=False)
    filesystems = FilesystemSerializer(many=True, max_length=32)
    services = serializers.DictField(child=serializers.ChoiceField(choices=['active','inactive','failed','unknown']), required=False)
    network = serializers.DictField(required=False)
    os_name = serializers.CharField(max_length=120,required=False)
    def validate(self, attrs):
        for key in ['cpu','ram','swap']:
            if attrs.get(key) is not None and not math.isfinite(attrs[key]): raise serializers.ValidationError('Metrics must be finite.')
        for fs in attrs['filesystems']:
            for key in ['used_percent','inode_percent']:
                if fs[key] is not None and not math.isfinite(fs[key]): raise serializers.ValidationError('Metrics must be finite.')
        if len({fs['mount'] for fs in attrs['filesystems']}) != len(attrs['filesystems']): raise serializers.ValidationError('Duplicate mounts.')
        if len(attrs.get('services',{})) > 32: raise serializers.ValidationError('Too many services.')
        return attrs


class ManagedUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)
    is_admin = serializers.BooleanField(source='is_superuser', required=False)
    class Meta:
        model = get_user_model()
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'is_active', 'is_admin', 'password', 'date_joined', 'last_login']
        read_only_fields = ['id', 'date_joined', 'last_login']

    def validate(self, attrs):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        if self.instance is None and not attrs.get('password'):
            raise serializers.ValidationError({'password': 'A password is required.'})
        if 'password' in attrs:
            candidate = self.Meta.model(**{k: attrs.get(k, getattr(self.instance, k, '')) for k in ['username', 'first_name', 'last_name', 'email']})
            try:
                validate_password(attrs['password'], candidate)
            except ValidationError as exc:
                raise serializers.ValidationError({'password': exc.messages})
        if self.instance and self.instance.pk == self.context['request'].user.pk:
            if attrs.get('is_active') is False or attrs.get('is_superuser') is False:
                raise serializers.ValidationError('You cannot deactivate your own account or remove your administrator access.')
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        return self.Meta.model.objects.create_user(password=password, **validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        instance = super().update(instance, validated_data)
        if password is not None:
            instance.set_password(password)
            instance.save(update_fields=['password'])
        return instance
