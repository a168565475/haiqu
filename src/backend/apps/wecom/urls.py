from django.urls import path

from .views import AuditsView, BindingsView, ConfigCheckView, ConfigView, EmployeesView
from .message_views import MessageAttemptsView, MessageTemplateView, MessageTestView
from .directory_views import DirectoryMatchView, DirectoryPreviewView, DirectoryRefreshView, DirectorySyncView, DirectoryProgressView
from .department_mapping_views import DepartmentMappingDetailView, DepartmentMappingsRefreshView, DepartmentMappingsView


urlpatterns = [
    path("config/", ConfigView.as_view(), name="wecom-config"),
    path("config/check/", ConfigCheckView.as_view(), name="wecom-config-check"),
    path("bindings/", BindingsView.as_view(), name="wecom-bindings"),
    path("employees/", EmployeesView.as_view(), name="wecom-employees"),
    path("employee-directory/", DirectoryPreviewView.as_view(), name="wecom-directory-preview"),
    path("employee-directory/refresh/", DirectoryRefreshView.as_view(), name="wecom-directory-refresh"),
    path("employee-directory/sync/", DirectorySyncView.as_view(), name="wecom-directory-sync"),
    path("employee-directory/match/", DirectoryMatchView.as_view(), name="wecom-directory-match"),
    path("employee-directory/progress/<uuid:progress_id>/", DirectoryProgressView.as_view(), name="wecom-directory-progress"),
    path("department-mappings/", DepartmentMappingsView.as_view(), name="wecom-department-mappings"),
    path("department-mappings/refresh/", DepartmentMappingsRefreshView.as_view(), name="wecom-department-mappings-refresh"),
    path("department-mappings/<int:department_id>/", DepartmentMappingDetailView.as_view(), name="wecom-department-mapping-detail"),
    path("audits/", AuditsView.as_view(), name="wecom-audits"),
    path("message-template/", MessageTemplateView.as_view(), name="wecom-message-template"),
    path("message-tests/", MessageTestView.as_view(), name="wecom-message-tests"),
    path("message-attempts/", MessageAttemptsView.as_view(), name="wecom-message-attempts"),
]
