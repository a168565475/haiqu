from django.urls import path
from rest_framework.routers import SimpleRouter

from ..dashboard import ProductionDashboardView
from .views import ProductionTaskViewSet


router = SimpleRouter()
router.register("production-tasks", ProductionTaskViewSet, basename="production-task")

urlpatterns = [path("production-dashboard/", ProductionDashboardView.as_view(), name="production-dashboard"), *router.urls]
