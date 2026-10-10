from rest_framework.routers import SimpleRouter

from .views import OutsourcingFactoryViewSet, OutsourcingOrderViewSet
from .unified_views import UnifiedOutsourcingOrderViewSet
from .tube_views import TubeOutsourcingOrderViewSet


router = SimpleRouter()
router.register("outsourcing-factories", OutsourcingFactoryViewSet, basename="outsourcing-factory")
router.register("outsourcing-orders", OutsourcingOrderViewSet, basename="outsourcing-order")
router.register("unified-outsourcing-orders", UnifiedOutsourcingOrderViewSet, basename="unified-outsourcing-order")
router.register("tube-outsourcing-orders", TubeOutsourcingOrderViewSet, basename="tube-outsourcing-order")

urlpatterns = router.urls

