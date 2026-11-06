from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    PurchaseContractTemplateViewSet,
    PurchaseOrderViewSet,
    SupplierPurchaseSheetViewSet,
    SupplierViewSet,
)
from .purchase_request_views import PurchaseRequestViewSet
from .return_views import PurchaseReturnViewSet
from .group_views import PurchaseGroupViewSet
from .tracking_views import PurchaseTrackingViewSet
from .tracking_policy_views import PurchaseTrackingPolicyView


router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("purchase-orders", PurchaseOrderViewSet, basename="purchase-order")
router.register("purchase-groups", PurchaseGroupViewSet, basename="purchase-group")
router.register("purchase-tracking", PurchaseTrackingViewSet, basename="purchase-tracking")
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

urlpatterns = [path("purchase-tracking-policy/", PurchaseTrackingPolicyView.as_view(), name="purchase-tracking-policy"), *router.urls]
