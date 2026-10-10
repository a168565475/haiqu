from rest_framework.routers import DefaultRouter

from .views import CraftViewSet, OperationViewSet, WorkshopEmployeeViewSet, WorkshopViewSet


router = DefaultRouter()
router.register("workshop-config/workshops", WorkshopViewSet, basename="workshop-config-workshop")
router.register("workshop-config/employees", WorkshopEmployeeViewSet, basename="workshop-config-employee")
router.register("workshop-config/crafts", CraftViewSet, basename="workshop-config-craft")
router.register("workshop-config/operations", OperationViewSet, basename="workshop-config-operation")

urlpatterns = router.urls
