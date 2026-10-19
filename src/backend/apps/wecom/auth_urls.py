from django.urls import path

from .views import oauth_callback, oauth_start


urlpatterns = [
    path("start/", oauth_start, name="wecom-oauth-start"),
    path("callback/", oauth_callback, name="wecom-oauth-callback"),
]
