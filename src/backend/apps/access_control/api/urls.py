from rest_framework.routers import SimpleRouter

from .views import AccessAuditViewSet, AccessEmployeeViewSet, CatalogViewSet, RoleViewSet, SalesTeamViewSet

router = SimpleRouter()
router.register("catalog", CatalogViewSet, basename="access-catalog")
router.register("roles", RoleViewSet, basename="access-role")
router.register("employees", AccessEmployeeViewSet, basename="access-employee")
router.register("audit-events", AccessAuditViewSet, basename="access-audit")
router.register("sales-teams", SalesTeamViewSet, basename="access-team")
urlpatterns = router.urls
