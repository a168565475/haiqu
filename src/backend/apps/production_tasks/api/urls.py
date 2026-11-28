from django.urls import path
from rest_framework.routers import SimpleRouter

from ..dashboard import ProductionDashboardView
from .director_workbench import WorkshopDirectorWorkbenchViewSet
from .material_tracking import MaterialTrackingBomFileView, MaterialTrackingDetailView, MaterialTrackingView
from .merchandiser_workbench import MerchandiserWorkbenchViewSet
from .views import ProductionTaskViewSet


router = SimpleRouter()
router.register("production-tasks", ProductionTaskViewSet, basename="production-task")
router.register("workshop-director-workbench", WorkshopDirectorWorkbenchViewSet, basename="workshop-director-workbench")
router.register("merchandiser-workbench", MerchandiserWorkbenchViewSet, basename="merchandiser-workbench")

urlpatterns = [
    path("production-dashboard/", ProductionDashboardView.as_view(), name="production-dashboard"),
    path("material-tracking/", MaterialTrackingView.as_view(), name="material-tracking-list"),
    path("material-tracking/<uuid:product_id>/", MaterialTrackingDetailView.as_view(), name="material-tracking-detail"),
    path("material-tracking/<uuid:product_id>/bom-file/<uuid:bom_id>/", MaterialTrackingBomFileView.as_view(), name="material-tracking-bom-file"),
    *router.urls,
]
