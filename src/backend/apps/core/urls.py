from django.conf import settings
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from .views import auth_login, auth_logout, current_user, health


urlpatterns = [
    path("auth/login/", auth_login, name="auth-login"),
    path("auth/logout/", auth_logout, name="auth-logout"),
    path("auth/me/", current_user, name="auth-me"),
    path("health/", health, name="health"),
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("v1/", include("apps.core.api.urls")),
]

if settings.DEBUG:
    urlpatterns.append(
        path(
            "docs/",
            SpectacularSwaggerView.as_view(url_name="api-schema"),
            name="api-docs",
        )
    )
