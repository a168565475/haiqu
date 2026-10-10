from rest_framework.routers import SimpleRouter

from .inventory_views import SampleInventoryLineViewSet
from .loan_views import SampleInventoryLoanLineViewSet
from .outbound_views import SampleInventoryOutboundLineViewSet
from .views import SampleItemViewSet, SampleRequestViewSet, SampleShipmentViewSet


router = SimpleRouter()
router.register("sample-requests", SampleRequestViewSet, basename="sample-request")
router.register("sample-items", SampleItemViewSet, basename="sample-item")
router.register("sample-shipments", SampleShipmentViewSet, basename="sample-shipment")
router.register("sample-inventory", SampleInventoryLineViewSet, basename="sample-inventory")
router.register("sample-outbound", SampleInventoryOutboundLineViewSet, basename="sample-outbound")
router.register("sample-loans", SampleInventoryLoanLineViewSet, basename="sample-loan")

urlpatterns = router.urls
