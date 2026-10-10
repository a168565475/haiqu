from rest_framework.routers import DefaultRouter

from .views import (
    PurchaseContractTemplateViewSet,
    PurchaseOrderViewSet,
    SupplierPurchaseSheetViewSet,
    SupplierViewSet,
)
from .purchase_request_views import PurchaseRequestViewSet
from .return_views import PurchaseReturnViewSet


router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("purchase-orders", PurchaseOrderViewSet, basename="purchase-order")
router.register("purchase-returns", PurchaseReturnViewSet, basename="purchase-return")
router.register("purchase-requests", PurchaseRequestViewSet, basename="purchase-request")
router.register(
    "purchase-contract-templates",
    PurchaseContractTemplateViewSet,
    basename="purchase-contract-template",
)
router.register(
    "supplier-purchase-sheets",
    SupplierPurchaseSheetViewSet,
    basename="supplier-purchase-sheet",
)

urlpatterns = router.urls
