from apps.procurement.source_access import purchase_order_access
from uuid import UUID
from collections.abc import Mapping
from pathlib import Path
import json

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.procurement.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchaseReturn,
    PurchaseReturnStatus,
    Supplier,
    SupplierType,
)
from apps.products.models import RawMaterialInformation
from apps.production_tasks.models import ProductionTask, ProductionTaskStatus
from apps.organizations.models import Employee, EmployeeStatus
from apps.files.uploads import save_scanned_image
from apps.production_tasks.selectors import accessible_production_tasks
from apps.reference_data.models import AccessoryMaterial, FabricMaterial, ProductColor, ReferenceStatus
from apps.reference_data.pinyin_search import build_pinyin_search

from ..models import (
    FinishedGoodsReceipt,
    FinishedGoodsReceiptStatus,
    FinishedGoodsOutbound,
    MaterialInbound,
    MaterialInboundLine,
    MaterialInboundStatus,
    MaterialStockBalance,
    MaterialStockDirection,
    MaterialStockMovement,
    MaterialStockQuality,
    RecordStatus,
    Warehouse,
    WarehouseLocation,
    WarehouseType,
    WarehouseZone,
)
from ..selectors import (
    eligible_material_lines,
    eligible_material_purchase_orders,
    finished_goods_inventory_rows,
    finished_goods_outbounds,
    locations_with_usage,
    material_inbounds,
    material_inbound_order_totals,
    material_inventory_rows,
    material_received_totals,
    procurement_inbound_product_summaries,
    procurement_inbound_supplier_summaries,
    receipt_batches,
    warehouses_with_usage,
    zones_with_usage,
)
from ..services import (
    create_finished_goods_outbound,
    create_manual_material_inbound,
    create_material_inbound,
    confirm_material_quality,
    save_location,
    save_warehouse,
    save_zone,
)
from ..workflow import purchase_inbound_workflow_status
from ..sample_receiving_services import receive_sample_purchase
from ..public_stock_mode import public_flow_enabled
from ..public_inventory_queries import public_pipe_summary, public_raw_inventory_rows, public_semi_inventory_page
from .serializers import (
    FinishedGoodsOutboundInputSerializer,
    FinishedGoodsOutboundSerializer,
    FinishedGoodsOutboundResponseSerializer,
    FinishedGoodsOutboundListResponseSerializer,
    FinishedGoodsReceiptSerializer,
    FinishedGoodsInventoryScopeSerializer,
    MaterialInboundInputSerializer,
    SampleMaterialInboundInputSerializer,
    SampleMaterialInboundResponseSerializer,
    ManualMaterialInboundInputSerializer,
    MaterialQualityConfirmationInputSerializer,
    MaterialInboundSerializer,
    ProcurementInboundOrderListResponseSerializer,
    WarehouseLocationSerializer,
    WarehouseSerializer,
    WarehouseZoneSerializer,
)


def uuid_value(value, field_name):
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError({field_name: "参数不正确。"}) from exc


def positive_int(value, field_name, default):
    if value in {None, ""}:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field_name: "参数必须为正整数。"}) from exc
    if parsed <= 0:
        raise ValidationError({field_name: "参数必须为正整数。"})
    return parsed


class BaseConfigurationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    service = None

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        response = Response({"data": self.get_serializer(instance).data})
        response["ETag"] = etag_for_instance(instance)
        return response

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            instance = self.service(
                instance=None,
                validated_data=serializer.validated_data,
                actor_employee=request.employee,
                request=request,
            )
        except (IntegrityError, DjangoValidationError) as exc:
            raise ValidationError({"detail": "编码或名称已存在。"}) from exc
        instance = self.get_queryset().get(pk=instance.pk)
        response = Response({"data": self.get_serializer(instance).data}, status=status.HTTP_201_CREATED)
        response["ETag"] = etag_for_instance(instance)
        return response

    def _update(self, request, partial):
        current = self.get_object()
        require_matching_etag(request, current)
        serializer = self.get_serializer(current, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            instance = self.service(
                instance=current,
                validated_data=serializer.validated_data,
                actor_employee=request.employee,
                request=request,
            )
        except (IntegrityError, DjangoValidationError) as exc:
            raise ValidationError({"detail": "编码或名称已存在。"}) from exc
        instance = self.get_queryset().get(pk=instance.pk)
        response = Response({"data": self.get_serializer(instance).data})
        response["ETag"] = etag_for_instance(instance)
        return response

    def update(self, request, *args, **kwargs):
        return self._update(request, kwargs.pop("partial", False))

    def partial_update(self, request, *args, **kwargs):
        return self._update(request, True)


class WarehouseViewSet(BaseConfigurationViewSet):
    serializer_class = WarehouseSerializer
    service = staticmethod(save_warehouse)
    action_permission_map = {
        "list": "inventory.view_warehouse", "retrieve": "inventory.view_warehouse",
        "create": "inventory.add_warehouse", "update": "inventory.change_warehouse",
        "partial_update": "inventory.change_warehouse",
    }

    def get_queryset(self):
        queryset = Warehouse.objects.all()
        warehouse_type = self.request.query_params.get("warehouse_type", "").strip().upper()
        record_status = self.request.query_params.get("status", "").strip().upper()
        keyword = self.request.query_params.get("q", "").strip()
        if warehouse_type:
            if warehouse_type not in WarehouseType.values:
                raise ValidationError({"warehouse_type": "仓库类型参数不正确。"})
            queryset = queryset.filter(warehouse_type=warehouse_type)
        if record_status:
            if record_status not in RecordStatus.values:
                raise ValidationError({"status": "状态参数不正确。"})
            queryset = queryset.filter(status=record_status)
        if keyword:
            queryset = queryset.filter(Q(warehouse_number__icontains=keyword) | Q(warehouse_name__icontains=keyword))
        return warehouses_with_usage(queryset)


class WarehouseZoneViewSet(BaseConfigurationViewSet):
    serializer_class = WarehouseZoneSerializer
    service = staticmethod(save_zone)
    action_permission_map = {
        "list": "inventory.view_warehousezone", "retrieve": "inventory.view_warehousezone",
        "create": "inventory.add_warehousezone", "update": "inventory.change_warehousezone",
        "partial_update": "inventory.change_warehousezone",
    }

    def get_queryset(self):
        queryset = WarehouseZone.objects.all()
        warehouse_id = self.request.query_params.get("warehouse_id", "").strip()
        record_status = self.request.query_params.get("status", "").strip().upper()
        if warehouse_id:
            queryset = queryset.filter(warehouse_id=uuid_value(warehouse_id, "warehouse_id"))
        if record_status:
            if record_status not in RecordStatus.values:
                raise ValidationError({"status": "状态参数不正确。"})
            queryset = queryset.filter(status=record_status)
        return zones_with_usage(queryset)


class WarehouseLocationViewSet(BaseConfigurationViewSet):
    serializer_class = WarehouseLocationSerializer
    service = staticmethod(save_location)
    action_permission_map = {
        "list": "inventory.view_warehouselocation", "retrieve": "inventory.view_warehouselocation",
        "create": "inventory.add_warehouselocation", "update": "inventory.change_warehouselocation",
        "partial_update": "inventory.change_warehouselocation",
    }

    def get_queryset(self):
        queryset = WarehouseLocation.objects.all()
        warehouse_id = self.request.query_params.get("warehouse_id", "").strip()
        zone_id = self.request.query_params.get("zone_id", "").strip()
        record_status = self.request.query_params.get("status", "").strip().upper()
        keyword = self.request.query_params.get("q", "").strip()
        if warehouse_id:
            queryset = queryset.filter(zone__warehouse_id=uuid_value(warehouse_id, "warehouse_id"))
        if zone_id:
            queryset = queryset.filter(zone_id=uuid_value(zone_id, "zone_id"))
        if record_status:
            if record_status not in RecordStatus.values:
                raise ValidationError({"status": "状态参数不正确。"})
            queryset = queryset.filter(status=record_status)
        if keyword:
            queryset = queryset.filter(Q(location_number__icontains=keyword) | Q(zone__zone_name__icontains=keyword))
        return locations_with_usage(queryset)


class FinishedGoodsInventoryViewSet(viewsets.ViewSet):
    serializer_class = FinishedGoodsReceiptSerializer
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "list": "inventory.view_finishedgoodsreceipt",
        "options": "inventory.view_finishedgoodsreceipt",
        "receipts.GET": "inventory.view_finishedgoodsreceipt",
        "outbound_batches": "inventory.add_finishedgoodsoutbound",
        "outbounds": "inventory.add_finishedgoodsoutbound",
        "outbounds.GET": "inventory.view_finishedgoodsoutbound",
        "outbound_detail": "inventory.view_finishedgoodsoutbound",
        "outbound_attachment": "inventory.view_finishedgoodsoutbound",
    }

    def get_permissions(self):
        if self.action == "options" and self.request.method == "GET" and self.request.query_params.get("scope") == "filters":
            # 仅共享仓库/库区筛选选项；完整入库选项仍要求查看入库权限。
            self.action_permission_map = {
                **self.action_permission_map,
                "options.GET": ["inventory.view_finishedgoodsreceipt", "inventory.view_finishedgoodsoutbound"],
            }
        return super().get_permissions()

    @extend_schema(parameters=[FinishedGoodsInventoryScopeSerializer])
    def list(self, request):
        scope = FinishedGoodsInventoryScopeSerializer(data=request.query_params)
        scope.is_valid(raise_exception=True)
        warehouse_id = request.query_params.get("warehouse_id", "").strip()
        zone_id = request.query_params.get("zone_id", "").strip()
        if warehouse_id:
            warehouse_id = str(uuid_value(warehouse_id, "warehouse_id"))
        if zone_id:
            zone_id = str(uuid_value(zone_id, "zone_id"))
        production_task_id = scope.validated_data.get("production_task_id")
        rows = finished_goods_inventory_rows(
            keyword=request.query_params.get("q", "").strip(),
            warehouse_id=warehouse_id,
            zone_id=zone_id,
            category=request.query_params.get("category", "").strip(),
            production_task_id=str(production_task_id) if production_task_id else "",
            exclude_sample=scope.validated_data["exclude_sample"],
        )
        page = positive_int(request.query_params.get("page"), "page", 1)
        page_size = min(positive_int(request.query_params.get("page_size"), "page_size", 20), 100)
        start = (page - 1) * page_size
        normalized = [self._inventory_payload(item) for item in rows[start:start + page_size]]
        return Response({"count": rows.count(), "next": None, "previous": None, "results": normalized})

    @staticmethod
    def _inventory_payload(item):
        return {
            "inventory_key": "|".join(str(item[key]) for key in (
                "production_task_product__product_id", "task_number_snapshot", "category_snapshot", "product_number_snapshot", "product_code_snapshot", "product_name_snapshot", "item_number_snapshot",
                "specification_snapshot", "actual_color", "unit_id", "location__zone__warehouse_id", "location__zone_id"
            )),
            "product_id": item["production_task_product__product_id"],
            "task_number": item["task_number_snapshot"],
            "category": item["category_snapshot"],
            "product_number": item["product_number_snapshot"],
            "product_code": item["product_code_snapshot"],
            "product_name": item["product_name_snapshot"],
            "item_number": item["item_number_snapshot"],
            "specification": item["specification_snapshot"],
            "actual_color": item["actual_color"], "inventory_quantity": item["inventory_quantity"],
            "unit_id": item["unit_id"], "unit_code": item["unit__unit_code"], "unit_name": item["unit__unit_name"],
            "warehouse_id": item["location__zone__warehouse_id"],
            "warehouse_number": item["location__zone__warehouse__warehouse_number"],
            "warehouse_name": item["location__zone__warehouse__warehouse_name"],
            "zone_id": item["location__zone_id"], "zone_name": item["location__zone__zone_name"],
            "batch_count": item["batch_count"], "occupied_box_slots": item["occupied_box_slots"],
            "latest_inbound_time": item["latest_inbound_time"], "receipt_ids": item["receipt_ids"],
        }

    @extend_schema(parameters=[OpenApiParameter(name="scope", type=str, enum=["full", "filters"])])
    @action(detail=False, methods=["get"])
    def options(self, request):
        scope = request.query_params.get("scope", "full")
        if scope not in {"full", "filters"}:
            raise ValidationError({"scope": "选项范围必须为 full 或 filters。"})
        if scope == "filters":
            return Response({"data": {
                "warehouses": list(Warehouse.objects.filter(status=RecordStatus.ACTIVE, warehouse_type=WarehouseType.FINISHED)
                    .order_by("warehouse_number", "id").values("id", "warehouse_number", "warehouse_name")),
                "zones": list(WarehouseZone.objects.filter(status=RecordStatus.ACTIVE, warehouse__status=RecordStatus.ACTIVE,
                    warehouse__warehouse_type=WarehouseType.FINISHED).order_by("warehouse__warehouse_number", "zone_name", "id")
                    .values("id", "warehouse", "zone_name")),
            }})
        warehouses = warehouses_with_usage(
            Warehouse.objects.filter(status=RecordStatus.ACTIVE, warehouse_type=WarehouseType.FINISHED)
        ).order_by("warehouse_number", "id")
        zones = zones_with_usage(
            WarehouseZone.objects.filter(
                status=RecordStatus.ACTIVE,
                warehouse__status=RecordStatus.ACTIVE,
                warehouse__warehouse_type=WarehouseType.FINISHED,
            )
        ).order_by("warehouse__warehouse_number", "zone_name", "id")
        locations = locations_with_usage(
            WarehouseLocation.objects.filter(
                status=RecordStatus.ACTIVE,
                zone__status=RecordStatus.ACTIVE,
                zone__warehouse__status=RecordStatus.ACTIVE,
                zone__warehouse__warehouse_type=WarehouseType.FINISHED,
            )
        ).order_by("zone__warehouse__warehouse_number", "zone__zone_name", "location_number", "id")
        suppliers = Supplier.objects.filter(archived_at__isnull=True, is_disabled=False, supplier_type=SupplierType.FINISHED).order_by("supplier_number")
        product_colors = ProductColor.objects.filter(
            archived_at__isnull=True,
            status=ReferenceStatus.ACTIVE,
        ).order_by("sort_order", "color_card", "color_code", "color_name", "id")
        production_orders = ProductionTask.objects.filter(archived_at__isnull=True).exclude(status=ProductionTaskStatus.CANCELLED).order_by("-updated_at").values("id", "task_number", "order_number")[:500]
        return Response({"data": {
            "warehouses": WarehouseSerializer(warehouses, many=True).data,
            "zones": WarehouseZoneSerializer(zones, many=True).data,
            "locations": WarehouseLocationSerializer(locations, many=True).data,
            "suppliers": [{"id": item.pk, "supplier_number": item.supplier_number, "supplier_name": item.supplier_name} for item in suppliers],
            "product_colors": [
                {
                    "id": item.pk,
                    "color_card": item.color_card,
                    "color_code": item.color_code,
                    "color_name": item.color_name,
                }
                for item in product_colors
            ],
            "production_orders": list(production_orders),
            "employees": list(Employee.objects.filter(status=EmployeeStatus.ACTIVE, archived_at__isnull=True)
                .order_by("employee_code", "id").values("id", "employee_code", "display_name")),
        }})

    @action(detail=False, methods=["get"])
    def receipts(self, request):
        queryset = receipt_batches()
        receipt_ids = request.query_params.get("receipt_ids", "").strip()
        if receipt_ids:
            queryset = queryset.filter(pk__in=[uuid_value(item, "receipt_ids") for item in receipt_ids.split(",") if item])
        return Response({"data": FinishedGoodsReceiptSerializer(queryset[:1000], many=True).data})

    @action(detail=False, methods=["get"], url_path="outbound-batches")
    def outbound_batches(self, request):
        receipt_ids = [item for item in request.query_params.get("receipt_ids", "").split(",") if item]
        if not receipt_ids:
            raise ValidationError({"receipt_ids": "请至少选择一条库存。"})
        queryset = receipt_batches(FinishedGoodsReceipt.objects.filter(
            pk__in=[uuid_value(item, "receipt_ids") for item in receipt_ids],
            status=FinishedGoodsReceiptStatus.CONFIRMED,
            remaining_quantity__gt=0,
        ))
        return Response({"data": FinishedGoodsReceiptSerializer(queryset, many=True).data})

    @extend_schema(methods=["GET"], operation_id="finished_goods_outbounds_list",
        parameters=[OpenApiParameter("production_task_id", UUID), OpenApiParameter("product_line_id", UUID),
                    OpenApiParameter("q", str, description="搜索出货单号、生产任务单号、产品编码、品名、货号、规格或颜色，最长300字；命中后返回完整出货单。"),
                    OpenApiParameter("warehouse_id", UUID, description="出库仓库；与其他条件须命中同一明细。"),
                    OpenApiParameter("page", int), OpenApiParameter("page_size", int)],
        responses=FinishedGoodsOutboundListResponseSerializer)
    @extend_schema(methods=["POST"], operation_id="finished_goods_outbounds_create",
        request=FinishedGoodsOutboundInputSerializer, responses={201: FinishedGoodsOutboundResponseSerializer})
    @action(detail=False, methods=["get", "post"])
    def outbounds(self, request):
        if request.method == "GET":
            keyword = request.query_params.get("q", "").strip()
            if len(keyword) > 300:
                raise ValidationError({"q": "搜索内容不能超过300字。"})
            task_id = request.query_params.get("production_task_id", "").strip()
            product_line_id = request.query_params.get("product_line_id", "").strip()
            warehouse_id = request.query_params.get("warehouse_id", "").strip()
            queryset = finished_goods_outbounds(
                keyword=keyword,
                production_task_id=uuid_value(task_id, "production_task_id") if task_id else None,
                product_line_id=uuid_value(product_line_id, "product_line_id") if product_line_id else None,
                warehouse_id=uuid_value(warehouse_id, "warehouse_id") if warehouse_id else None,
            )
            page = positive_int(request.query_params.get("page"), "page", 1)
            page_size = min(positive_int(request.query_params.get("page_size"), "page_size", 20), 100)
            start = (page - 1) * page_size
            return Response({"data": {"items": FinishedGoodsOutboundSerializer(queryset[start:start + page_size], many=True).data, "total": queryset.count()}})
        if not isinstance(request.data, Mapping):
            raise ValidationError("出库请求必须为对象。")
        # multipart 的 QueryDict 不适合承载嵌套明细，先转换为普通字典。
        payload = {key: request.data.get(key) for key in request.data}
        if isinstance(payload.get("items"), str):
            try:
                payload["items"] = json.loads(payload["items"])
            except (TypeError, ValueError) as exc:
                raise ValidationError({"items": "出库明细格式不正确。"}) from exc
        images = request.FILES.getlist("loading_images")
        if images:
            payload["loading_images"] = images
        serializer = FinishedGoodsOutboundInputSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        uploaded = []
        try:
            for image in images:
                uploaded.append(save_scanned_image(image, request.employee,
                    storage_folder="inventory/finished-goods-loading", field_label="装卸图片"))
            outbound = create_finished_goods_outbound(
                items=values["items"], receiver_name=values["receiver_name"],
                used_for_order_number=values["used_for_order_number"], remark=values["remark"],
                actor_employee=request.employee, request=request,
                responsible_employee_id=values["responsible_employee_id"], shipment_date=values["shipment_date"],
                loading_fee=values["loading_fee"], other_fee=values["other_fee"], attachment_ids=[file.pk for file in uploaded],
            )
        except Exception:
            # 数据库事务回滚不会删除磁盘文件，只清理当前请求刚创建的上传副本。
            folder = (Path(settings.MEDIA_ROOT) / "inventory/finished-goods-loading").resolve()
            for file in uploaded:
                path = (Path(settings.MEDIA_ROOT) / file.storage_key).resolve()
                if folder not in path.parents:
                    raise RuntimeError("装卸图片清理路径超出本次上传目录。")
                path.unlink(missing_ok=True)
                file.archived_at = timezone.now()
                file.archived_by_employee = request.employee
                file.archive_reason = "出库提交失败，清理本次上传副本"
                file.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])
            raise
        outbound = finished_goods_outbounds().get(pk=outbound.pk)
        return Response({"data": FinishedGoodsOutboundSerializer(outbound).data}, status=status.HTTP_201_CREATED)

    @extend_schema(operation_id="finished_goods_outbound_detail", responses=FinishedGoodsOutboundResponseSerializer,
        parameters=[OpenApiParameter("outbound_id", UUID, location=OpenApiParameter.PATH)])
    @action(detail=False, methods=["get"], url_path=r"outbounds/(?P<outbound_id>[^/.]+)")
    def outbound_detail(self, request, outbound_id=None):
        outbound = finished_goods_outbounds().filter(pk=uuid_value(outbound_id, "outbound_id")).first()
        if outbound is None:
            raise NotFound("出库单不存在。")
        return Response({"data": FinishedGoodsOutboundSerializer(outbound).data})

    @extend_schema(responses={(200, 'image/*'): bytes}, parameters=[
        OpenApiParameter("outbound_id", UUID, location=OpenApiParameter.PATH),
        OpenApiParameter("file_id", UUID, location=OpenApiParameter.PATH)])
    @action(detail=False, methods=["get"], url_path=r"outbounds/(?P<outbound_id>[^/.]+)/attachments/(?P<file_id>[^/.]+)")
    def outbound_attachment(self, request, outbound_id=None, file_id=None):
        outbound = FinishedGoodsOutbound.objects.filter(pk=uuid_value(outbound_id, "outbound_id")).first()
        if outbound is None:
            raise NotFound("出库单不存在。")
        link = outbound.attachments.select_related("business_file").filter(business_file_id=uuid_value(file_id, "file_id")).first()
        if link is None or link.business_file.archived_at is not None or link.business_file.scan_status not in {"CLEAN", "SKIPPED"}:
            raise NotFound("装卸图片不存在或尚未通过安全扫描。")
        storage_root = Path(settings.MEDIA_ROOT).resolve()
        path = (storage_root / link.business_file.storage_key).resolve()
        if storage_root not in path.parents or not path.is_file():
            raise NotFound("装卸图片文件不存在。")
        return FileResponse(path.open("rb"), content_type=link.business_file.content_type)


class MaterialInventoryViewSet(viewsets.ViewSet):
    serializer_class = MaterialInboundSerializer
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "list": "inventory.view_materialinbound",
        "options": "inventory.view_materialinbound",
        "eligible_purchase_orders": "inventory.receive_material",
        "procurement_inbound_orders": ("inventory.receive_material", "inventory.quality_confirm_material"),
        "eligible_lines": "inventory.receive_material",
        "manual_material_options": "inventory.receive_material",
        "manual_receipts": "inventory.receive_material",
        "receipts.GET": "inventory.view_material_receipt",
        "receipts.POST": "inventory.receive_material",
        "batch_receipts": "inventory.receive_material",
        "receivings": "inventory.receive_material",
        "sample_receivings": "inventory.receive_material",
        "quality_batches": "inventory.quality_confirm_material",
        "quality_batch": "inventory.quality_confirm_material",
        "confirm_quality": "inventory.quality_confirm_material",
        "inbound_details": "inventory.view_material_receipt",
        "summary": "inventory.view_materialinbound",
        "order_purchases": "inventory.view_materialinbound",
        "order_issues": "inventory.view_materialinbound",
    }

    @staticmethod
    def _optional_uuid(request, name):
        value = request.query_params.get(name, "").strip()
        return str(uuid_value(value, name)) if value else ""

    def _accessible_task_ids(self, request):
        return accessible_production_tasks(request).order_by().values_list("id", flat=True)

    def list(self, request):
        kind = request.query_params.get('stock_kind', 'RAW')
        if kind not in ('RAW', 'SEMI'):
            raise ValidationError({'stock_kind': '请选择原材料或半成品。'})
        if kind == 'SEMI':
            return self._semi_finished_rows(request)
        public_enabled = public_flow_enabled()
        inventory_rows = public_raw_inventory_rows if public_enabled else material_inventory_rows
        rows_query = inventory_rows(
            keyword=request.query_params.get("q", "").strip(),
            section_title=request.query_params.get("section_title", "").strip(),
            warehouse_id=self._optional_uuid(request, "warehouse_id"),
            zone_id=self._optional_uuid(request, "zone_id"),
            location_id=self._optional_uuid(request, "location_id"),
        )
        # 公共查询已在各余额分支中筛选；旧库存查询返回的是聚合 QuerySet。
        rows = list(rows_query if public_enabled else rows_query.filter(inventory_quantity__gt=0))
        page = positive_int(request.query_params.get("page"), "page", 1)
        page_size = min(positive_int(request.query_params.get("page_size"), "page_size", 20), 100)
        start = (page - 1) * page_size
        results = []
        for row in rows[start:start + page_size]:
            identity = f"{row['raw_material_id']}|{row['unit__unit_name']}|{row['zone_id']}|{row['measurement_kind']}|{row['raw_bar_length_m']}"
            color = row["raw_material__color__color_name"] or row["raw_material__color_snapshot"]
            results.append({
                "inventory_key": identity,
                'stock_kind': 'RAW',
                'stock_mode': 'PUBLIC_V2' if public_flow_enabled() else 'LEGACY',
                'measurement_kind': row['measurement_kind'],
                'raw_bar_length_m': row['raw_bar_length_m'],
                'meter_quantity': row['meter_quantity'],
                "stock_item_id": row["raw_material_id"],
                "section_type": row["raw_material__item_type"],
                "section_title": row["raw_material__category__category_name"],
                "category": row["raw_material__category__category_name"],
                "material_number": row["raw_material__material_number"],
                "material": row["raw_material__material"],
                "part_name": row["raw_material__material_name"],
                "specification": row["raw_material__specification"],
                "color": color,
                "raw_material": row["raw_material__material"],
                "unit": row["unit__unit_name"],
                "inventory_quantity": row["inventory_quantity"],
                "warehouse_id": row["zone__warehouse_id"],
                "warehouse_number": row["zone__warehouse__warehouse_number"],
                "warehouse_name": row["zone__warehouse__warehouse_name"],
                "zone_id": row["zone_id"],
                "zone_name": row["zone__zone_name"],
                "location_id": None,
                "location_number": None,
                "inbound_count": row["inbound_count"],
                "latest_inbound_date": (
                    row["latest_inbound_time"].date() if row["latest_inbound_time"] else None
                ),
                "latest_inbound_time": row["latest_inbound_time"],
            })
        return Response({"count": len(rows), "next": None, "previous": None, "results": results})

    def _semi_finished_rows(self, request):
        if public_flow_enabled():
            return Response(public_semi_inventory_page(
                page=positive_int(request.query_params.get("page"), "page", 1),
                page_size=min(positive_int(request.query_params.get("page_size"), "page_size", 20), 100),
                keyword=request.query_params.get("q", "").strip(),
                section_title=request.query_params.get("section_title", "").strip(),
                processing_status=request.query_params.get("processing_status", "").strip().upper(),
                warehouse_id=self._optional_uuid(request, "warehouse_id"),
                zone_id=self._optional_uuid(request, "zone_id"),
                location_id=self._optional_uuid(request, "location_id"),
            ))
        from apps.inventory.models import SemiFinishedStockBalance
        queryset = SemiFinishedStockBalance.objects.filter(
            production_task_id__in=self._accessible_task_ids(request), quality='AVAILABLE', quantity__gt=0,
        ).select_related('production_task', 'product_line', 'bom_line__section', 'completed_craft', 'unit', 'zone__warehouse')
        keyword = request.query_params.get('q', '').strip()
        if keyword:
            queryset = queryset.filter(Q(bom_line__part_name__icontains=keyword) | Q(bom_line__specification__icontains=keyword)
                                       | Q(production_task__task_number__icontains=keyword))
        section = request.query_params.get('section_title', '').strip()
        if section:
            queryset = queryset.filter(Q(bom_line__section__title=section) | Q(bom_line__category=section))
        for parameter, field in (('warehouse_id', 'zone__warehouse_id'), ('zone_id', 'zone_id')):
            value = self._optional_uuid(request, parameter)
            if value:
                queryset = queryset.filter(**{field: value})
        if self._optional_uuid(request, 'location_id'):
            queryset = queryset.none()
        page = positive_int(request.query_params.get('page'), 'page', 1)
        page_size = min(positive_int(request.query_params.get('page_size'), 'page_size', 20), 100)
        count = queryset.count()
        results = []
        for item in queryset.order_by('-updated_at', 'id')[(page - 1) * page_size:page * page_size]:
            results.append({
                'inventory_key': f'SEMI|{item.pk}', 'stock_kind': 'SEMI', 'stock_item_id': '',
                'section_type': item.bom_line.section.section_type, 'section_title': item.bom_line.section.title,
                'category': item.completed_craft.name, 'material_number': item.production_task.task_number,
                'material': item.bom_line.material, 'part_name': item.bom_line.part_name,
                'specification': item.bom_line.specification, 'color': item.color_snapshot,
                'raw_material': '', 'unit': item.unit.unit_name, 'inventory_quantity': item.quantity,
                'raw_bar_length_m': None, 'meter_quantity': None,
                'warehouse_id': item.zone.warehouse_id, 'warehouse_number': item.zone.warehouse.warehouse_number,
                'warehouse_name': item.zone.warehouse.warehouse_name, 'zone_id': item.zone_id,
                'zone_name': item.zone.zone_name, 'location_id': None, 'location_number': None,
                'inbound_count': None, 'latest_inbound_date': None, 'latest_inbound_time': None,
                'production_task_number': item.production_task.task_number, 'product_name': item.product_line.product_name_snapshot,
            })
        return Response({'count': count, 'next': None, 'previous': None, 'results': results})

    def _stock_material(self, pk):
        return RawMaterialInformation.objects.select_related("category", "unit", "color").filter(
            pk=uuid_value(pk, "stock_item_id"), archived_at__isnull=True
        ).first()

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        material = self._stock_material(pk)
        if material is None:
            raise NotFound("材料库存项不存在。")
        if public_flow_enabled() and material.category.category_name == "管材":
            return Response({"data": public_pipe_summary(material)})
        balances = MaterialStockBalance.objects.filter(raw_material=material)
        if material.category.category_name == '管材':
            balances = balances.filter(measurement_kind='PIPE')
        available = balances.filter(quality=MaterialStockQuality.AVAILABLE).aggregate(total=Sum("quantity"))["total"] or 0
        defective = balances.filter(quality=MaterialStockQuality.DEFECTIVE).aggregate(total=Sum("quantity"))["total"] or 0
        movements = MaterialStockMovement.objects.filter(balance__in=balances)
        inbound = movements.filter(direction=MaterialStockDirection.IN).aggregate(total=Sum("quantity"))["total"] or 0
        issued = movements.filter(direction=MaterialStockDirection.OUT).aggregate(total=Sum("quantity"))["total"] or 0
        return Response({"data": {
            "stock_item_id": str(material.pk),
            "material_number": material.material_number,
            "material_name": material.material_name,
            "category": material.category.category_name,
            "specification": material.specification,
            "color": material.color.color_name if material.color_id else material.color_snapshot,
            "unit": material.unit.unit_name,
            "current_quantity": str(available),
            'stock_kind': 'RAW',
            'measurement_kind': 'PIPE' if material.category.category_name == '管材' else 'OTHER',
            'meter_quantity': str(balances.filter(quality=MaterialStockQuality.AVAILABLE).aggregate(total=Sum('meter_quantity'))['total'] or 0),
            "available_quantity": str(available),
            "defective_quantity": str(defective),
            "cumulative_inbound_quantity": str(inbound),
            "cumulative_issued_quantity": str(issued),
            "zones": [
                {
                    "zone_id": str(item.zone_id),
                    'balance_id': str(item.pk),
                    "warehouse_number": item.zone.warehouse.warehouse_number,
                    "warehouse_name": item.zone.warehouse.warehouse_name,
                    "zone_name": item.zone.zone_name,
                    "quality": item.quality,
                    "quantity": str(item.quantity),
                    'inbound_line_id': str(item.inbound_line_id) if item.inbound_line_id else None,
                    'raw_bar_length_m': str(item.raw_bar_length_m) if item.raw_bar_length_m else None,
                    'meter_quantity': str(item.meter_quantity) if item.meter_quantity is not None else None,
                }
                for item in balances.select_related("zone", "zone__warehouse").order_by(
                    "zone__warehouse__warehouse_number", "zone__zone_name", "quality"
                )
            ],
        }})

    @action(detail=True, methods=["get"], url_path="order-purchases")
    def order_purchases(self, request, pk=None):
        material = self._stock_material(pk)
        if material is None:
            raise NotFound("材料库存项不存在。")
        raw_id = str(material.pk)
        fabric_material_ids = [
            str(item)
            for item in FabricMaterial.objects.filter(
                inventory_raw_material=material,
                archived_at__isnull=True,
            ).values_list("pk", flat=True)
        ]
        accessory_material_ids = [
            str(item)
            for item in AccessoryMaterial.objects.filter(
                inventory_raw_material=material,
                archived_at__isnull=True,
            ).values_list("pk", flat=True)
        ]
        current_material_source = (
            Q(bom_line__raw_values__source_raw_material_id=raw_id)
            | Q(bom_line__raw_values__source_inventory_material_id=raw_id)
            | Q(calculation_snapshot__raw_material_id=raw_id)
            | Q(bom_line__raw_values__source_cutting_material_id=raw_id)
            | Q(bom_line__raw_values__source_packaging_material_id=raw_id)
        )
        if fabric_material_ids:
            current_material_source |= Q(bom_line__raw_values__source_fabric_material_id__in=fabric_material_ids)
        if accessory_material_ids:
            current_material_source |= Q(bom_line__raw_values__source_accessory_material_id__in=accessory_material_ids)
        frozen_inbound_identity = MaterialInboundLine.objects.filter(
            purchase_order_line_id=OuterRef("pk"),
            raw_material_information__isnull=False,
        )
        lines = list(PurchaseOrderLine.objects.annotate(
            has_frozen_inbound_identity=Exists(frozen_inbound_identity),
        ).filter(
            purchase_order_access(self._accessible_task_ids(request), request, "purchase_order__"),
            Q(material_inbound_lines__raw_material_information=material)
            | (Q(has_frozen_inbound_identity=False) & current_material_source),
        ).select_related("purchase_order", "purchase_order__production_task").distinct().order_by(
            "purchase_order__order_number", "line_number", "id"
        ))
        has_conflicting_line = (
            MaterialInboundLine.objects.filter(
                purchase_order_line_id__in=[line.pk for line in lines],
                raw_material_information__isnull=False,
            )
            .values("purchase_order_line_id")
            .annotate(identity_count=Count("raw_material_information", distinct=True))
            .filter(identity_count__gt=1)
            .exists()
        )
        if has_conflicting_line:
            raise Conflict("采购明细存在多个已冻结库存原料身份，追溯数量不可靠，请先完成受控数据修复。")
        inbound_totals = dict(MaterialInboundLine.objects.filter(
            purchase_order_line_id__in=[line.pk for line in lines],
            inbound__status=MaterialInboundStatus.CONFIRMED,
            raw_material_information=material,
        ).values("purchase_order_line_id").annotate(total=Sum("accepted_quantity")).values_list("purchase_order_line_id", "total"))
        rows = []
        for line in lines:
            inbound = inbound_totals.get(line.pk) or 0
            purchased = line.actual_purchase_quantity or 0
            rows.append({
                "purchase_order_id": str(line.purchase_order_id),
                "purchase_order_number": line.purchase_order.order_number,
                "production_task_id": str(line.purchase_order.production_task_id) if line.purchase_order.production_task_id else None,
                "production_task_number": line.purchase_order.production_task_number_snapshot,
                "purchase_quantity": str(purchased),
                "actual_inbound_quantity": str(inbound),
                "pending_inbound_quantity": str(max(purchased - inbound, 0)),
                "unit": line.source_unit_text,
                "can_view_purchase_detail": request.user.has_perm("procurement.view_purchaseorder"),
            })
        return Response({"data": rows})

    @action(detail=True, methods=["get"], url_path="order-issues")
    def order_issues(self, request, pk=None):
        material = self._stock_material(pk)
        if material is None:
            raise NotFound("材料库存项不存在。")
        from apps.material_issues.models import MaterialIssueLine, MaterialIssueStatus

        lines = MaterialIssueLine.objects.filter(
            raw_material=material,
            issue__status=MaterialIssueStatus.ISSUED,
            issue__production_task_id__in=self._accessible_task_ids(request),
        ).select_related(
            "issue",
            "issue__production_task",
            "issue__workshop",
            "issue__recipient_workshop_employee",
            "issue__issued_by_employee",
        ).order_by("-issue__issued_at", "-issue__id", "line_number")
        return Response({"data": [
            {
                "material_issue_id": str(line.issue_id),
                "issue_number": line.issue.issue_number,
                "production_task_id": str(line.issue.production_task_id),
                "production_task_number": line.issue.production_task.task_number,
                "workshop": line.issue.workshop.name,
                "recipient": line.issue.recipient_workshop_employee.name,
                "issue_at": line.issue.issue_at,
                "issued_quantity": str(line.issued_quantity),
                "unit": line.unit_snapshot,
                "reviewer": line.issue.issued_by_employee.display_name,
                "reviewed_at": line.issue.issued_at,
            }
            for line in lines
        ]})

    @extend_schema(parameters=[OpenApiParameter(
        name="scope", type=str, enum=["full", "receiving", "filters"],
        description="默认 full 为完整库存选项；receiving 返回材料仓和库区；filters 增加库存分类。",
    )])
    @action(detail=False, methods=["get"])
    def options(self, request):
        scope = request.query_params.get("scope", "full")
        if scope not in {"full", "receiving", "filters"}:
            raise ValidationError({"scope": "选项范围必须为 full、receiving 或 filters。"})
        warehouse_types = [WarehouseType.MATERIAL]
        if public_flow_enabled() and scope == "filters":
            warehouse_types.append(WarehouseType.SEMI_FINISHED)
        warehouses = Warehouse.objects.filter(status=RecordStatus.ACTIVE, warehouse_type__in=warehouse_types).order_by("warehouse_number")
        zones = WarehouseZone.objects.filter(
            status=RecordStatus.ACTIVE,
            warehouse__status=RecordStatus.ACTIVE,
            warehouse__warehouse_type__in=warehouse_types,
        ).select_related("warehouse").order_by("warehouse__warehouse_number", "zone_name")
        if scope in {"receiving", "filters"}:
            data = {
                "stock_mode": "PUBLIC_V2" if public_flow_enabled() else "LEGACY",
                "warehouses": list(warehouses.values("id", "warehouse_number", "warehouse_name", "warehouse_type")),
                "zones": list(zones.values("id", "warehouse", "zone_name")),
            }
            if scope == "filters":
                data["sections"] = list(MaterialInboundLine.objects.values_list("section_title_snapshot", flat=True)
                    .distinct().order_by("section_title_snapshot"))
                if public_flow_enabled():
                    data["sections"] = sorted(set(data["sections"]) | {"型材明细", "裁剪明细", "五金件"})
            return Response({"data": data})
        locations = WarehouseLocation.objects.filter(
            status=RecordStatus.ACTIVE,
            zone__status=RecordStatus.ACTIVE,
            zone__warehouse__status=RecordStatus.ACTIVE,
            zone__warehouse__warehouse_type=WarehouseType.MATERIAL,
        ).select_related("zone", "zone__warehouse").order_by("zone__warehouse__warehouse_number", "zone__zone_name", "location_number")
        accessible_orders = PurchaseOrder.objects.filter(purchase_order_access(self._accessible_task_ids(request), request))
        order_queryset = eligible_material_purchase_orders(accessible_orders)
        purchasing_count = accessible_orders.filter(
            archived_at__isnull=True, status=PurchaseOrderStatus.PURCHASING,
        ).count() if request.user.has_perm("inventory.receive_material") else 0
        sections = list(
            MaterialInboundLine.objects.values_list("section_title_snapshot", flat=True)
            .distinct()
            .order_by("section_title_snapshot")
        )
        return Response({"data": {
            "purchasing_order_count": purchasing_count,
            "warehouses": WarehouseSerializer(warehouses_with_usage(warehouses), many=True).data,
            "zones": WarehouseZoneSerializer(zones_with_usage(zones), many=True).data,
            "locations": WarehouseLocationSerializer(locations_with_usage(locations), many=True).data,
            "sections": sections,
            "production_orders": [
                {
                    "id": order.production_task_id,
                    "task_number": order.production_task_number_snapshot,
                    "order_number": order.sales_order_number_snapshot,
                }
                for order in order_queryset
                if order.production_task_id and order.production_task.status not in {ProductionTaskStatus.COMPLETED, ProductionTaskStatus.CANCELLED}
            ],
        }})

    @action(detail=False, methods=["get"], url_path="eligible-purchase-orders")
    def eligible_purchase_orders(self, request):
        queryset = eligible_material_purchase_orders(
            PurchaseOrder.objects.filter(purchase_order_access(self._accessible_task_ids(request), request)),
            read_optimized=True,
        )
        production_task_id = request.query_params.get("production_task_id", "").strip()
        if production_task_id:
            queryset = queryset.filter(production_task_id=uuid_value(production_task_id, "production_task_id"))
        purchase_order_id = request.query_params.get("purchase_order_id", "").strip()
        if purchase_order_id:
            queryset = queryset.filter(pk=uuid_value(purchase_order_id, "purchase_order_id"))
        keyword = request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(order_number__icontains=keyword)
                | Q(production_task_number_snapshot__icontains=keyword)
                | Q(lines__supplier_name_snapshot__icontains=keyword)
            ).distinct()
        orders = list(queryset[:500])
        totals = material_received_totals([line.pk for order in orders for line in order.lines.all()])
        data = []
        for order in orders:
            remaining_lines = [
                line for line in order.lines.all()
                if line.actual_purchase_quantity is not None
                and line.actual_purchase_quantity - totals.get(line.pk, 0) > 0
            ]
            if not remaining_lines:
                continue
            supplier_names = list(dict.fromkeys(line.supplier_name_snapshot for line in remaining_lines if line.supplier_name_snapshot))
            data.append({
                "id": order.pk,
                "order_number": order.order_number,
                "production_task_id": order.production_task_id,
                "production_task_number": order.production_task_number_snapshot,
                "source_type": order.source_type,
                "source_number": order.sample_number_snapshot if order.source_type == "SAMPLE" else order.production_task_number_snapshot,
                "sales_order_number": order.sales_order_number_snapshot,
                "supplier_names": supplier_names,
                "remaining_line_count": len(remaining_lines),
            })
        return Response({"data": data})

    @extend_schema(responses=ProcurementInboundOrderListResponseSerializer)
    @action(detail=False, methods=["get"], url_path="procurement-inbound-orders")
    def procurement_inbound_orders(self, request):
        queryset = (
            PurchaseOrder.objects.filter(
                purchase_order_access(self._accessible_task_ids(request), request),
                status__in=[PurchaseOrderStatus.PURCHASING, PurchaseOrderStatus.COMPLETED],
                archived_at__isnull=True,
            )
            .prefetch_related("lines")
            .order_by("-created_at", "-id")
        )
        keyword = request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(order_number__icontains=keyword)
                | Q(production_task_number_snapshot__icontains=keyword)
                | Q(sample_number_snapshot__icontains=keyword)
                | Q(sales_order_number_snapshot__icontains=keyword)
                | Q(lines__supplier_name_snapshot__icontains=keyword)
            ).distinct()
        orders = list(queryset[:500])
        order_ids = [order.pk for order in orders]
        product_summaries = procurement_inbound_product_summaries(orders)
        purchase_lines = [line for order in orders for line in order.lines.all()]
        received_totals = material_received_totals([line.pk for line in purchase_lines])
        batch_totals = material_inbound_order_totals(order_ids)
        return_statuses_by_order = {order_id: set() for order_id in order_ids}
        for order_id, return_status in PurchaseReturn.objects.filter(
            inbound__purchase_order_id__in=order_ids,
        ).values_list("inbound__purchase_order_id", "status"):
            return_statuses_by_order.setdefault(order_id, set()).add(return_status)

        data = []
        for order in orders:
            lines = [line for line in order.lines.all() if line.actual_purchase_quantity is not None]
            remaining_lines = [
                line for line in lines
                if line.actual_purchase_quantity - received_totals.get(line.pk, 0) > 0
            ]
            progress = batch_totals.get(order.pk, {})
            pending_count = progress.get("pending_count", 0)
            confirmed_count = progress.get("confirmed_count", 0)
            return_quantity = progress.get("return_quantity", 0)
            received_quantity = progress.get("received_quantity", 0)
            return_statuses = return_statuses_by_order.get(order.pk, set())
            if PurchaseReturnStatus.QUALITY_GENERATED in return_statuses:
                current_return_status = PurchaseReturnStatus.QUALITY_GENERATED
            elif PurchaseReturnStatus.PROCUREMENT_CONFIRMED in return_statuses:
                current_return_status = PurchaseReturnStatus.PROCUREMENT_CONFIRMED
            elif PurchaseReturnStatus.COMPLETED in return_statuses:
                current_return_status = PurchaseReturnStatus.COMPLETED
            else:
                current_return_status = "NONE"
            workflow_status, workflow_status_display = purchase_inbound_workflow_status(
                order_status=order.status,
                has_lines=bool(lines),
                has_remaining_lines=bool(remaining_lines),
                pending_quality_count=pending_count,
                received_quantity=received_quantity,
                return_status=current_return_status,
            )
            supplier_names = list(dict.fromkeys(line.supplier_name_snapshot for line in lines if line.supplier_name_snapshot))
            data.append({
                "id": order.pk,
                "order_number": order.order_number,
                "source_type": order.source_type,
                "source_number": order.sample_number_snapshot if order.source_type == "SAMPLE" else order.production_task_number_snapshot,
                "sales_order_number": order.sales_order_number_snapshot,
                "product_summary": product_summaries.get(order.pk, []),
                "supplier_summary": procurement_inbound_supplier_summaries(lines),
                "currency_code": order.currency_code_snapshot,
                "supplier_names": supplier_names,
                "line_count": len(lines),
                "remaining_line_count": len(remaining_lines),
                "pending_quality_count": pending_count,
                "confirmed_batch_count": confirmed_count,
                "received_quantity": f"{received_quantity:.4f}",
                "return_quantity": f"{return_quantity:.4f}",
                "return_status": current_return_status,
                "workflow_status": workflow_status,
                "workflow_status_display": workflow_status_display,
                "updated_at": order.updated_at,
            })
        return Response({"data": data})

    @action(detail=False, methods=["get"], url_path="manual-material-options")
    def manual_material_options(self, request):
        queryset = RawMaterialInformation.objects.filter(
            archived_at__isnull=True,
            category__archived_at__isnull=True,
            category__status=ReferenceStatus.ACTIVE,
            unit__archived_at__isnull=True,
            unit__status=ReferenceStatus.ACTIVE,
        ).select_related("category", "unit", "color")
        category_id = request.query_params.get("category_id", "").strip()
        if category_id:
            queryset = queryset.filter(category_id=uuid_value(category_id, "category_id"))
        keyword = request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(material_number__icontains=keyword)
                | Q(material_name__icontains=keyword)
                | Q(specification__icontains=keyword)
                | Q(material__icontains=keyword)
                | Q(color_snapshot__icontains=keyword)
            )
        categories = RawMaterialInformation.objects.filter(
            archived_at__isnull=True,
            category__archived_at__isnull=True,
            category__status=ReferenceStatus.ACTIVE,
        ).values("category_id", "category__category_name").distinct().order_by("category__category_name")
        items = queryset.order_by("material_number", "id")[:100]
        return Response({"data": {
            "categories": [
                {"id": row["category_id"], "name": row["category__category_name"]}
                for row in categories
            ],
            "materials": [
                {
                    "id": item.pk,
                    "material_number": item.material_number,
                    "category_id": item.category_id,
                    "category_name": item.category.category_name,
                    "material_name": item.material_name,
                    "specification": item.specification,
                    "material": item.material,
                    "color_name": item.color.color_name if item.color_id else item.color_snapshot,
                    "unit_name": item.unit.unit_name,
                }
                for item in items
            ],
        }})

    @action(detail=False, methods=["post"], url_path="manual-receipts")
    def manual_receipts(self, request):
        serializer = ManualMaterialInboundInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inbound = create_manual_material_inbound(
            **serializer.validated_data,
            actor_employee=request.employee,
            request=request,
        )
        inbound = material_inbounds(MaterialInbound.objects.filter(pk=inbound.pk)).get()
        return Response({"data": MaterialInboundSerializer(inbound).data}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="eligible-lines")
    def eligible_lines(self, request):
        purchase_order_id = request.query_params.get("purchase_order_id", "").strip()
        if not purchase_order_id:
            raise ValidationError({"purchase_order_id": "请选择采购单。"})
        order_id = uuid_value(purchase_order_id, "purchase_order_id")
        order = PurchaseOrder.objects.filter(purchase_order_access(self._accessible_task_ids(request), request), pk=order_id).first()
        if order is None:
            raise NotFound("采购单不存在或无权访问。")
        rows = []
        for line, remaining in eligible_material_lines(order_id, read_optimized=True):
            text = " ".join(filter(None, [
                line.section_title_snapshot, line.category_snapshot, line.material_snapshot,
                line.part_name_snapshot, line.specification_snapshot, line.raw_material_snapshot,
            ]))
            rows.append({
                "id": line.pk,
                "line_number": line.line_number,
                "section_type": line.section_type_snapshot,
                "section_title": line.section_title_snapshot,
                "category": line.category_snapshot,
                "material": line.material_snapshot,
                "part_name": line.part_name_snapshot,
                "specification": line.specification_snapshot,
                "raw_material": line.raw_material_snapshot,
                "material_attributes_snapshot": line.material_attributes_snapshot,
                "unit": line.source_unit_text,
                "supplier_name": line.supplier_name_snapshot,
                "purchased_quantity": f"{line.actual_purchase_quantity:.4f}",
                'raw_bar_length_m': str(line.raw_bar_length_m) if line.raw_bar_length_m else None,
                'actual_bar_count': line.actual_bar_count,
                'remaining_bar_count': int(remaining / line.raw_bar_length_m) if line.raw_bar_length_m else None,
                "remaining_quantity": f"{remaining:.4f}",
                "pinyin_search": build_pinyin_search(text),
            })
        return Response({"data": rows}, headers={"ETag": etag_for_instance(order)})

    @action(detail=False, methods=["get", "post"])
    def receipts(self, request):
        if request.method == "POST":
            serializer = MaterialInboundInputSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            inbound = create_material_inbound(
                **serializer.validated_data,
                actor_employee=request.employee,
                request=request,
            )
            inbound = material_inbounds(MaterialInbound.objects.filter(pk=inbound.pk)).get()
            return Response({"data": MaterialInboundSerializer(inbound).data}, status=status.HTTP_201_CREATED)
        queryset = material_inbounds(MaterialInbound.objects.filter(
            Q(purchase_order__isnull=True)
            | purchase_order_access(self._accessible_task_ids(request), request, "purchase_order__"),
            status=MaterialInboundStatus.CONFIRMED,
        ))
        purchase_order_id = request.query_params.get("purchase_order_id", "").strip()
        if purchase_order_id:
            queryset = queryset.filter(lines__purchase_order_line__purchase_order_id=uuid_value(purchase_order_id, "purchase_order_id"))
        return Response({"data": MaterialInboundSerializer(queryset.distinct()[:1000], many=True).data})

    @action(detail=False, methods=["post"], url_path="batch-receipts")
    def batch_receipts(self, request):
        return self.receipts(request)

    @action(detail=False, methods=["post"])
    def receivings(self, request):
        serializer = MaterialInboundInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inbound = create_material_inbound(
            **serializer.validated_data,
            actor_employee=request.employee,
            request=request,
        )
        inbound = material_inbounds(MaterialInbound.objects.filter(pk=inbound.pk)).get()
        return Response({"data": MaterialInboundSerializer(inbound).data}, status=status.HTTP_201_CREATED)

    @extend_schema(request=SampleMaterialInboundInputSerializer,
                   parameters=[OpenApiParameter('If-Match', str, location='header', required=True)],
                   responses={200: SampleMaterialInboundResponseSerializer, 201: SampleMaterialInboundResponseSerializer})
    @action(detail=False, methods=['post'], url_path='sample-receivings')
    def sample_receivings(self, request):
        serializer = SampleMaterialInboundInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inbound, created = receive_sample_purchase(**serializer.validated_data,
            actor_employee=request.employee, request=request)
        inbound = material_inbounds(MaterialInbound.objects.filter(pk=inbound.pk)).get()
        return Response({'data': MaterialInboundSerializer(inbound).data},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def _accessible_inbounds(self, request, *, read_optimized=False):
        return material_inbounds(
            MaterialInbound.objects.filter(
                purchase_order_access(self._accessible_task_ids(request), request, "purchase_order__"),
            ),
            read_optimized=read_optimized,
        )

    @action(detail=False, methods=["get"], url_path="quality-batches")
    def quality_batches(self, request):
        queryset = self._accessible_inbounds(request, read_optimized=True).filter(status=MaterialInboundStatus.PENDING_QUALITY)
        keyword = request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(inbound_number__icontains=keyword)
                | Q(purchase_order__order_number__icontains=keyword)
                | Q(lines__supplier_name_snapshot__icontains=keyword)
            ).distinct()
        return Response({"data": MaterialInboundSerializer(queryset[:500], many=True).data})

    @action(
        detail=False,
        methods=["get"],
        url_path=r"quality-batches/(?P<inbound_id>[^/.]+)",
    )
    def quality_batch(self, request, inbound_id=None):
        inbound = self._accessible_inbounds(request, read_optimized=True).filter(pk=uuid_value(inbound_id, "inbound_id")).first()
        if inbound is None:
            raise NotFound("待检批次不存在或无权访问。")
        return Response({"data": MaterialInboundSerializer(inbound).data})

    @action(
        detail=False,
        methods=["post"],
        url_path=r"quality-batches/(?P<inbound_id>[^/.]+)/confirm",
    )
    def confirm_quality(self, request, inbound_id=None):
        inbound_uuid = uuid_value(inbound_id, "inbound_id")
        if not self._accessible_inbounds(request).filter(pk=inbound_uuid).exists():
            raise NotFound("待检批次不存在或无权访问。")
        serializer = MaterialQualityConfirmationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inbound = confirm_material_quality(
            inbound_id=inbound_uuid,
            items=serializer.validated_data["items"],
            actor_employee=request.employee,
            request=request,
        )
        inbound = material_inbounds(MaterialInbound.objects.filter(pk=inbound.pk)).get()
        return Response({"data": MaterialInboundSerializer(inbound).data})

    @action(detail=False, methods=["get"], url_path="inbound-details")
    def inbound_details(self, request):
        queryset = material_inbounds(MaterialInbound.objects.filter(
            Q(purchase_order__isnull=True)
            | purchase_order_access(self._accessible_task_ids(request), request, "purchase_order__"),
            status=MaterialInboundStatus.CONFIRMED,
        ), read_optimized=True)
        inbound_date = request.query_params.get("inbound_date", "").strip()
        if inbound_date:
            queryset = queryset.filter(inbound_date=serializers.DateField().run_validation(inbound_date))
        keyword = request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(inbound_number__icontains=keyword)
                | Q(purchase_order__order_number__icontains=keyword)
                | Q(lines__purchase_order_number_snapshot__icontains=keyword)
                | Q(lines__part_name_snapshot__icontains=keyword)
                | Q(lines__material_snapshot__icontains=keyword)
                | Q(lines__raw_material_snapshot__icontains=keyword)
                | Q(lines__supplier_name_snapshot__icontains=keyword)
            ).distinct()
        warehouse_id = request.query_params.get("warehouse_id", "").strip()
        if warehouse_id:
            queryset = queryset.filter(lines__zone__warehouse_id=uuid_value(warehouse_id, "warehouse_id"))
        section_title = request.query_params.get("section_title", "").strip()
        if section_title:
            queryset = queryset.filter(lines__section_title_snapshot=section_title)
        zone_id = request.query_params.get("zone_id", "").strip()
        if zone_id:
            queryset = queryset.filter(lines__zone_id=uuid_value(zone_id, "zone_id"))
        exact_line_filters = {
            "section_type": "lines__section_type_snapshot",
            "category": "lines__category_snapshot",
            "material": "lines__material_snapshot",
            "part_name": "lines__part_name_snapshot",
            "specification": "lines__specification_snapshot",
            "raw_material": "lines__raw_material_snapshot",
            "unit": "lines__source_unit_text_snapshot",
        }
        for parameter, field_name in exact_line_filters.items():
            value = request.query_params.get(parameter)
            if value is not None:
                queryset = queryset.filter(**{field_name: value})
        return Response({"data": MaterialInboundSerializer(queryset.distinct()[:1000], many=True).data})
