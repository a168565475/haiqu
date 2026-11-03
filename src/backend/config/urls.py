from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/workshop-mobile/", include("apps.workshop_mobile.urls")),
    path("api/", include("apps.core.urls")),
]
