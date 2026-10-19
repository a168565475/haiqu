from django.urls import path

from .views import QRLoginView, oauth_callback, oauth_start


urlpatterns = [
    path("qr/", QRLoginView.as_view(), name="wecom-qr-login"),
    path("start/", oauth_start, name="wecom-oauth-start"),
    path("callback/", oauth_callback, name="wecom-oauth-callback"),
]
