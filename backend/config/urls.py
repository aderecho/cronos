from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenBlacklistView
from monitoring import views as v
router=DefaultRouter(trailing_slash=False)
router.register('users',v.UserViewSet,basename='user')
router.register('servers',v.ServerViewSet,basename='server')
router.register('applications',v.ApplicationViewSet,basename='application')
router.register('incidents',v.IncidentViewSet,basename='incident')
router.register('alert-rules',v.RuleViewSet,basename='rule')
router.register('maintenance-windows',v.MaintenanceViewSet,basename='maintenance')
urlpatterns=[path('admin/',admin.site.urls),path('api/v1/',include(router.urls)),path('api/v1/auth/login',v.LoginView.as_view()),path('api/v1/auth/refresh',TokenRefreshView.as_view()),path('api/v1/auth/logout',TokenBlacklistView.as_view()),path('api/v1/auth/me',v.me),path('api/v1/dashboard',v.dashboard),path('api/v1/agent/telemetry',v.TelemetryView.as_view()),path('api/v1/devices',v.devices),path('api/v1/devices/<int:pk>',v.device_remove),path('api/v1/notifications',v.notifications),path('api/v1/notifications/test',v.test_notification),path('api/v1/notification-preferences',v.preferences),path('api/v1/health/live',v.live),path('api/v1/health/ready',v.ready)]
urlpatterns += [path('api/v1/auth/demo',v.demo_login)]

from monitoring.agent_downloads import download as agent_download
urlpatterns += [path("api/v1/agent/install.sh",agent_download),path("api/v1/agent/files/<str:filename>",agent_download)]

urlpatterns += [path('api/v1/realtime/config', v.realtime_config), path('api/v1/realtime/device-status',v.realtime_device_status)]

