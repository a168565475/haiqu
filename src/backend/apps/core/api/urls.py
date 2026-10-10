from django.urls import include, path

from .discovery_views import GlobalSearchView, ManagerDashboardView, MyDashboardView
from .views import api_v1_root


urlpatterns = [
    path("", api_v1_root, name="api-v1-root"),
    path("", include("apps.customers.api.urls")),
    path("", include("apps.crm.api.urls")),
    path("", include("apps.workflow.api.urls")),
    path("", include("apps.inquiries.api.urls")),
    path("", include("apps.quotations.api.urls")),
    path("", include("apps.samples.api.urls")),
    path("", include("apps.sales_orders.api.urls")),
    path("", include("apps.production_tasks.api.urls")),
    path("", include("apps.production_scheduling.api.urls")),
    path("", include("apps.outsourcing.api.urls")),
    path("", include("apps.boms.api.urls")),
    path("", include("apps.procurement.api.urls")),
    path("", include("apps.inventory.api.urls")),
    path("", include("apps.material_issues.api.urls")),
    path("", include("apps.workshop_config.api.urls")),
    path("", include("apps.preferences.api.urls")),
    path("", include("apps.email_accounts.api.urls")),
    path("", include("apps.imports.api.urls")),
    path("", include("apps.audit.api.urls")),
    path("", include("apps.reference_data.api.urls")),
    path("", include("apps.products.api.urls")),
    path("search/", GlobalSearchView.as_view(), name="global-search"),
    path("dashboard/me/", MyDashboardView.as_view(), name="dashboard-me"),
    path("dashboard/manager/", ManagerDashboardView.as_view(), name="dashboard-manager"),
]
