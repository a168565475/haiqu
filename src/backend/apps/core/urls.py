from django.conf import settings
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from .views import (
    account_return_admin, account_switch, account_switch_targets,
    auth_login, auth_logout, current_user, development_auto_login, health,
)


urlpatterns = [
    path("auth/login/", auth_login, name="auth-login"),
    path("auth/development-auto-login/", development_auto_login, name="development-auto-login"),
    path("auth/logout/", auth_logout, name="auth-logout"),
    path("auth/me/", current_user, name="auth-me"),
    path("auth/switch-targets/", account_switch_targets, name="auth-switch-targets"),
    path("auth/switch/", account_switch, name="auth-switch"),
    path("auth/return-admin/", account_return_admin, name="auth-return-admin"),
    path("auth/wecom/", include("apps.wecom.auth_urls")),
    path("health/", health, name="health"),
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("v1/", include("apps.core.api.urls")),
    path("v1/access/", include("apps.access_control.api.urls")),
    path("v1/wecom/", include("apps.wecom.urls")),
    path("v1/notifications/", include("apps.wecom.notification_urls")),
    path("v1/codex-connection/", include("apps.codex_connection.urls")),
    path("v1/", include("apps.production_task_imports.urls")),
    path("v1/attendance/", include("apps.attendance.urls")),
    path("v1/workshop-reporting/", include("apps.workshop_reporting.api.urls")),
]

if settings.DEBUG:
    urlpatterns.append(
        path(
            "docs/",
            SpectacularSwaggerView.as_view(url_name="api-schema"),
            name="api-docs",
        )
    )
