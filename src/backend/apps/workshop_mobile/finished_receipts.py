from copy import copy

from apps.inventory.api.finished_receipts import AssemblyReceiptViewSet
from apps.inventory.models import RecordStatus, Warehouse, WarehouseLocation, WarehouseType, WarehouseZone
from apps.inventory.receipt_permissions import receipt_plans_for_category
from apps.inventory.selectors import locations_with_usage

from .serializers import MobileFinishedReceiptLocationSerializer


FINISHED_RECEIPT_ADD = 'inventory.add_finishedgoodsreceipt'


def finished_receipt_products(request):
    # 复用 ERP 新增入库的来源范围，不借用手机列表的领料/报工动作。
    scoped = copy(request)
    scoped.__dict__.pop('_sales_access_snapshot', None)
    view = AssemblyReceiptViewSet()
    view.action = 'preview'
    view.request = scoped
    scoped.parser_context = {**(getattr(request, 'parser_context', None) or {}), 'view': view}
    return receipt_plans_for_category(scoped, 'ASSEMBLY')


def finished_receipt_options():
    warehouses = Warehouse.objects.filter(status=RecordStatus.ACTIVE, warehouse_type=WarehouseType.FINISHED)
    zones = WarehouseZone.objects.filter(
        status=RecordStatus.ACTIVE, warehouse__status=RecordStatus.ACTIVE,
        warehouse__warehouse_type=WarehouseType.FINISHED,
    )
    locations = locations_with_usage(WarehouseLocation.objects.filter(
        status=RecordStatus.ACTIVE, zone__status=RecordStatus.ACTIVE,
        zone__warehouse__status=RecordStatus.ACTIVE, zone__warehouse__warehouse_type=WarehouseType.FINISHED,
    )).order_by('zone__warehouse__warehouse_number', 'zone__zone_name', 'location_number', 'id')
    return {
        'warehouses': list(warehouses.order_by('warehouse_number', 'id').values(
            'id', 'warehouse_number', 'warehouse_name', 'warehouse_type', 'status')),
        'zones': list(zones.order_by('warehouse__warehouse_number', 'zone_name', 'id').values(
            'id', 'warehouse', 'zone_name', 'status')),
        'locations': MobileFinishedReceiptLocationSerializer(locations, many=True).data,
    }
