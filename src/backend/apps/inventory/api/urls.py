from rest_framework.routers import SimpleRouter
from .internal_receipts import InternalReceiptViewSet
from .finished_receipts import AssemblyReceiptViewSet, FinishedRecordViewSet

from .views import (
    FinishedGoodsInventoryViewSet,
    MaterialInventoryViewSet,
    WarehouseLocationViewSet,
    WarehouseViewSet,
    WarehouseZoneViewSet,
)


router = SimpleRouter()
router.register("assembly-finished-receipts", AssemblyReceiptViewSet, basename="assembly-finished-receipt")
router.register("finished-goods-records", FinishedRecordViewSet, basename="finished-goods-record")
router.register("semi-finished-receipts", InternalReceiptViewSet, basename="semi-finished-receipt")
router.register("warehouses", WarehouseViewSet, basename="warehouse")
router.register("warehouse-zones", WarehouseZoneViewSet, basename="warehouse-zone")
router.register("warehouse-locations", WarehouseLocationViewSet, basename="warehouse-location")
router.register("finished-goods-inventory", FinishedGoodsInventoryViewSet, basename="finished-goods-inventory")
router.register("material-inventory", MaterialInventoryViewSet, basename="material-inventory")

urlpatterns = router.urls
