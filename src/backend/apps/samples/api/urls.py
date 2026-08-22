from rest_framework.routers import SimpleRouter

from .views import SampleItemViewSet, SampleRequestViewSet, SampleShipmentViewSet


router = SimpleRouter()
router.register("sample-requests", SampleRequestViewSet, basename="sample-request")
router.register("sample-items", SampleItemViewSet, basename="sample-item")
router.register("sample-shipments", SampleShipmentViewSet, basename="sample-shipment")

urlpatterns = router.urls
