from rest_framework.routers import SimpleRouter

from .views import ProductionScheduleItemViewSet, ProductionScheduleViewSet


router = SimpleRouter()
router.register("production-schedules", ProductionScheduleViewSet, basename="production-schedule")
router.register("production-schedule-items", ProductionScheduleItemViewSet, basename="production-schedule-item")

urlpatterns = router.urls
