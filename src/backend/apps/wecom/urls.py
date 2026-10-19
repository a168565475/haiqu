from django.urls import path

from .views import AuditsView, BindingsView, ConfigCheckView, ConfigView, EmployeesView


urlpatterns = [
    path("config/", ConfigView.as_view(), name="wecom-config"),
    path("config/check/", ConfigCheckView.as_view(), name="wecom-config-check"),
    path("bindings/", BindingsView.as_view(), name="wecom-bindings"),
    path("employees/", EmployeesView.as_view(), name="wecom-employees"),
    path("audits/", AuditsView.as_view(), name="wecom-audits"),
]
