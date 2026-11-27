from django.urls import path
from rest_framework.routers import SimpleRouter

from ..dashboard import ProductionDashboardView
from .director_workbench import WorkshopDirectorWorkbenchViewSet
from .merchandiser_workbench import MerchandiserWorkbenchViewSet
from .views import ProductionTaskViewSet


router = SimpleRouter()
router.register("production-tasks", ProductionTaskViewSet, basename="production-task")
router.register("workshop-director-workbench", WorkshopDirectorWorkbenchViewSet, basename="workshop-director-workbench")
router.register("merchandiser-workbench", MerchandiserWorkbenchViewSet, basename="merchandiser-workbench")

urlpatterns = [
    path("production-dashboard/", ProductionDashboardView.as_view(), name="production-dashboard"),
    *router.urls,
]
