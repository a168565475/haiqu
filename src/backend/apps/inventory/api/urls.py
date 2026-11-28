from rest_framework.routers import SimpleRouter
from .internal_receipts import InternalReceiptViewSet
from .finished_receipts import AssemblyReceiptViewSet, FinishedRecordViewSet
from .material_inbound_sources import MaterialInboundSourceViewSet
from .material_transfers import MaterialTransferViewSet
from .material_stock_records import MaterialStockRecordsView
from .warehouse_workbench import WarehouseWorkbenchViewSet
from django.urls import path

from .views import (
    FinishedGoodsInventoryViewSet,
    MaterialInventoryViewSet,
    WarehouseLocationViewSet,
    WarehouseViewSet,
    WarehouseZoneViewSet,
)


router = SimpleRouter()
router.register("warehouse-workbench", WarehouseWorkbenchViewSet, basename="warehouse-workbench")
router.register("assembly-finished-receipts", AssemblyReceiptViewSet, basename="assembly-finished-receipt")
router.register("finished-goods-records", FinishedRecordViewSet, basename="finished-goods-record")
router.register("semi-finished-receipts", InternalReceiptViewSet, basename="semi-finished-receipt")
router.register("warehouses", WarehouseViewSet, basename="warehouse")
router.register("warehouse-zones", WarehouseZoneViewSet, basename="warehouse-zone")
router.register("warehouse-locations", WarehouseLocationViewSet, basename="warehouse-location")
router.register("finished-goods-inventory", FinishedGoodsInventoryViewSet, basename="finished-goods-inventory")
router.register("material-inventory", MaterialInventoryViewSet, basename="material-inventory")
router.register("material-transfers", MaterialTransferViewSet, basename="material-transfer")

urlpatterns = [
    path("material-stock-records/", MaterialStockRecordsView.as_view(), name="material-stock-records"),
    path("material-inbound-sources/", MaterialInboundSourceViewSet.as_view({"get": "list"}), name="material-inbound-source-list"),
    path("material-inbound-sources/options/", MaterialInboundSourceViewSet.as_view({"get": "options_list"}), name="material-inbound-source-options"),
    path("material-inbound-sources/public-options/", MaterialInboundSourceViewSet.as_view({"get": "public_options"}), name="material-inbound-source-public-options"),
    path("material-inbound-sources/<uuid:pk>/", MaterialInboundSourceViewSet.as_view({"get": "retrieve"}), name="material-inbound-source-detail"),
    *router.urls,
]
