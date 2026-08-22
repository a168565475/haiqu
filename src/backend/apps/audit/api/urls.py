from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import AuditLogViewSet, CustomerAuditLogNestedViewSet


router = SimpleRouter()
router.register("audit-logs", AuditLogViewSet, basename="audit-log")

customer_audit_logs = CustomerAuditLogNestedViewSet.as_view({"get": "list"})

urlpatterns = [
    path("customers/<uuid:customer_pk>/audit-logs/", customer_audit_logs, name="customer-audit-log-list"),
    *router.urls,
]
