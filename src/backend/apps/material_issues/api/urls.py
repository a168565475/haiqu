from rest_framework.routers import SimpleRouter

from .views import MaterialIssueViewSet
from .processing_views import MetalProcessingSourceViewSet
from .p4_views import (
    MetalProcessingExternalOrderViewSet, MetalProcessingOriginalHandoffViewSet,
    MetalProcessingReworkViewSet, MetalProcessingUnsprayedReturnViewSet,
    MetalProcessingOriginalOrderViewSet,
)


router = SimpleRouter()
router.register("material-issues", MaterialIssueViewSet, basename="material-issue")
router.register("metal-processing-sources", MetalProcessingSourceViewSet, basename="metal-processing-source")
router.register("metal-processing-handoffs", MetalProcessingOriginalHandoffViewSet, basename="metal-processing-handoff")
router.register("metal-processing-original-orders", MetalProcessingOriginalOrderViewSet, basename="metal-processing-original-order")
router.register("metal-processing-unsprayed-returns", MetalProcessingUnsprayedReturnViewSet, basename="metal-processing-unsprayed-return")
router.register("metal-processing-reworks", MetalProcessingReworkViewSet, basename="metal-processing-rework")
router.register("metal-processing-external-orders", MetalProcessingExternalOrderViewSet, basename="metal-processing-external-order")

urlpatterns = router.urls
