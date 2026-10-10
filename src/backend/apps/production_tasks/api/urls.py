from rest_framework.routers import SimpleRouter

from .views import ProductionTaskViewSet


router = SimpleRouter()
router.register("production-tasks", ProductionTaskViewSet, basename="production-task")

urlpatterns = router.urls
