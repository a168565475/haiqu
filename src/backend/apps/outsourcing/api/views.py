from ..selectors import outsourcing_source_schedules
from apps.organizations.selectors import active_department_employees
from apps.access_control.resource_scopes import filter_crafts, require_craft, enabled
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.db.models import Prefetch, Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.boms.api.serializers import BomLineSerializer
from apps.boms.material_attributes import bom_attribute_fields, spray_color_value
from apps.boms.models import Bom, BomLine, BomLineImage
from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
from apps.inventory.models import RecordStatus as InventoryRecordStatus, WarehouseType, WarehouseZone
from apps.organizations.models import Employee, EmployeeStatus
from apps.production_scheduling.models import (
    ProductionScheduleProduct,
    ProductionScheduleProductCraft,
    ScheduleStatus,
)
from apps.production_scheduling.selectors import accessible_production_schedules, schedules_with_context
from apps.workshop_config.models import Craft, CraftType, OutsourcingCode, RecordStatus

from ..models import (
    FactoryStatus,
    OutsourcingFactory,
    OutsourcingOrderStatus,
    OutsourcingProcessingItem,
)
from ..selectors import accessible_outsourcing_orders, factories_with_context, orders_with_context
from ..services import (
    SUPPORTED_OUTSOURCING_CRAFT_CODES,
    cancel_order,
    confirm_dispatch,
    confirm_return,
    create_factory,
    create_order,
    delete_order,
    disable_factory,
    dispatch_context,
    material_required_quantity,
    processing_required_quantity,
    processing_reference_usage,
    update_factory,
)
from .serializers import (
    ReconciliationWriteSerializer, RawReturnWriteSerializer, CompleteWriteSerializer,
    FactoryReadSerializer,
    FactoryWriteSerializer,
    OutsourcingOrderCancelSerializer,
    OutsourcingOrderRevokeSerializer,
    OutsourcingOrderDetailSerializer,
    OutsourcingDispatchConfirmSerializer,
    OutsourcingOrderReadSerializer,
    OutsourcingReturnConfirmSerializer,
    OutsourcingOrderWriteSerializer,
)


def _uuid(value, field):
    if not value:
        return None
    try:
        return UUID(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field: f"{field} 参数不是有效 UUID。"}) from exc


def _line_image_url(line_data):
    images = line_data.get("images") or []
    return images[0].get("content_url", "") if images else ""


def _line_color(line_data, section_title):
    if section_title == "管材类":
        return spray_color_value(line_data)
    if section_title == "五金件":
        return spray_color_value(line_data) or line_data.get("hardware_color", "")
    if section_title == "面料类":
        return line_data.get("fabric_color_name", "")
    if section_title == "辅料类":
        return line_data.get("accessory_color", "")
    if section_title == "裁剪明细":
        return line_data.get("cutting_color", "")
    return ""


def _material_category(section_title):
    return {
        "管材类": ("PROFILE", "管材"),
        "五金件": ("HARDWARE", "五金"),
        "面料类": ("FABRIC", "面料类"),
        "辅料类": ("AUXILIARY", "辅料类"),
        "塑料件类": ("PLASTIC", "塑料"),
        "包材类": ("PACKAGING", "包材"),
    }.get(section_title, ("OTHER", section_title))


class OutsourcingFactoryViewSet(viewsets.GenericViewSet):
    serializer_class = FactoryReadSerializer
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "list": "outsourcing.view_outsourcingfactory",
        "retrieve": "outsourcing.view_outsourcingfactory",
        "create": "outsourcing.add_outsourcingfactory",
        "partial_update": "outsourcing.change_outsourcingfactory",
        "disable": "outsourcing.disable_outsourcingfactory",
        "options": "outsourcing.view_outsourcingfactory",
        "related_orders": "outsourcing.view_outsourcingfactory",
    }

    def get_queryset(self):
        return factories_with_context()

    def list(self, request):
        queryset = self.get_queryset()
        keyword = request.query_params.get("search", "").strip()
        if len(keyword) > 200:
            raise ValidationError({"search": "搜索内容不能超过 200 个字符。"})
        if keyword:
            queryset = queryset.filter(
                Q(name__icontains=keyword) | Q(contact_name__icontains=keyword) | Q(contact_phone__icontains=keyword)
            )
        craft_id = _uuid(request.query_params.get("craft_id", "").strip(), "craft_id")
        if craft_id:
            queryset = queryset.filter(craft_links__craft_id=craft_id)
        processing_type = request.query_params.get("processing_type", "").strip()
        if processing_type:
            queryset = queryset.filter(processing_type=processing_type)
        status_value = request.query_params.get("status", "").strip().upper()
        if status_value:
            if status_value not in FactoryStatus.values:
                raise ValidationError({"status": "加工厂状态参数不正确。"})
            queryset = queryset.filter(status=status_value)
        queryset = queryset.distinct().order_by("-updated_at", "-id")
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(FactoryReadSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        factory = get_object_or_404(self.get_queryset(), pk=pk)
        data = FactoryReadSerializer(factory).data
        response = Response({"data": data})
        response["ETag"] = etag_for_instance(factory)
        return response

    @action(detail=True, methods=["get"], url_path="related-orders")
    def related_orders(self, request, pk=None):
        if not request.user.has_perm("outsourcing.view_outsourcingorder"):
            raise PermissionDenied("缺少外发单查看权限。")
        factory = get_object_or_404(self.get_queryset(), pk=pk)
        queryset = orders_with_context(
            accessible_outsourcing_orders(request).filter(
                products__processing_items__allocations__factory=factory
            ).distinct()
        ).order_by("-updated_at", "-id")
        page = list(self.paginate_queryset(queryset))
        from ..reconciliation_services import order_action_candidates

        serializer = OutsourcingOrderReadSerializer(
            page, many=True, context={"factory_id": factory.pk, "request": request,
                                      "action_candidates": order_action_candidates(page)}
        )
        return self.get_paginated_response(serializer.data)

    def create(self, request):
        serializer = FactoryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        factory = create_factory(
            validated_data=dict(serializer.validated_data), actor_employee=request.employee, request=request
        )
        factory = self.get_queryset().get(pk=factory.pk)
        response = Response({"data": FactoryReadSerializer(factory).data}, status=201)
        response["ETag"] = etag_for_instance(factory)
        return response

    def partial_update(self, request, pk=None):
        get_object_or_404(self.get_queryset(), pk=pk)
        serializer = FactoryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        factory = update_factory(
            factory_id=pk, validated_data=dict(serializer.validated_data),
            actor_employee=request.employee, request=request,
        )
        factory = self.get_queryset().get(pk=factory.pk)
        response = Response({"data": FactoryReadSerializer(factory).data})
        response["ETag"] = etag_for_instance(factory)
        return response

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        get_object_or_404(self.get_queryset(), pk=pk)
        factory = disable_factory(factory_id=pk, actor_employee=request.employee, request=request)
        factory = self.get_queryset().get(pk=factory.pk)
        response = Response({"data": FactoryReadSerializer(factory).data})
        response["ETag"] = etag_for_instance(factory)
        return response

    @action(detail=False, methods=["get"])
    def options(self, request):
        crafts = Craft.objects.filter(
            craft_type=CraftType.EXTERNAL,
            status=RecordStatus.ACTIVE,
            outsourcing_code__in=OutsourcingCode.values,
        ).order_by("name", "id")
        processing_types = list(
            OutsourcingFactory.objects.exclude(processing_type="")
            .order_by("processing_type").values_list("processing_type", flat=True).distinct()
        )
        return Response({"data": {
            "crafts": [
                {"id": str(item.pk), "name": item.name, "outsourcing_code": item.outsourcing_code}
                for item in crafts
            ],
            "processing_types": processing_types,
        }})


class OutsourcingOrderViewSet(viewsets.GenericViewSet):
    serializer_class = OutsourcingOrderReadSerializer
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "list": "outsourcing.view_outsourcingorder",
        "retrieve": "outsourcing.view_outsourcingorder",
        "create": "outsourcing.add_outsourcingorder",
        "destroy": "outsourcing.delete_outsourcingorder",
        "cancel": "outsourcing.cancel_outsourcingorder",
        "revoke_dispatched": "outsourcing.cancel_outsourcingorder",
        "confirm_dispatch": "outsourcing.confirm_dispatch_outsourcingorder",
        "dispatch_context": "outsourcing.confirm_dispatch_outsourcingorder",
        "confirm_return": "outsourcing.confirm_return_outsourcingorder",
        "reconciliation": "outsourcing.view_outsourcingorder",
        "confirm_raw_return": "outsourcing.return_raw_outsourcingorder",
        "confirm_reconciliation": "outsourcing.reconcile_outsourcingorder",
        "complete": "outsourcing.complete_outsourcingorder",
        "product_file": "outsourcing.view_outsourcingorder",
        "options": "outsourcing.view_outsourcingorder",
        "source_plans": "outsourcing.view_outsourcingorder",
        "source_product_bom": "outsourcing.view_outsourcingorder",
    }

    def get_queryset(self):
        include_detail_records = self.action in {
            "retrieve", "create", "cancel", "revoke_dispatched", "confirm_dispatch", "confirm_return",
        }
        return orders_with_context(
            accessible_outsourcing_orders(self.request),
            include_detail_records=include_detail_records,
        )

    def list(self, request):
        queryset = self.get_queryset()
        keyword = request.query_params.get("search", "").strip()
        if len(keyword) > 200:
            raise ValidationError({"search": "搜索内容不能超过 200 个字符。"})
        if keyword:
            queryset = queryset.filter(
                Q(order_number__icontains=keyword)
                | Q(schedule__schedule_number__icontains=keyword)
                | Q(schedule__production_task__task_number__icontains=keyword)
            )
        status_value = request.query_params.get("status", "").strip().upper()
        if status_value:
            if status_value not in OutsourcingOrderStatus.values:
                raise ValidationError({"status": "外发单状态参数不正确。"})
            queryset = queryset.filter(status=status_value)
        craft_id = _uuid(request.query_params.get("craft_id", "").strip(), "craft_id")
        if craft_id:
            queryset = queryset.filter(craft_id=craft_id)
        factory_id = _uuid(request.query_params.get("factory_id", "").strip(), "factory_id")
        if factory_id:
            queryset = queryset.filter(products__processing_items__allocations__factory_id=factory_id)
        queryset = queryset.distinct().order_by("-updated_at", "-id")
        page = list(self.paginate_queryset(queryset))
        from ..reconciliation_services import order_action_candidates

        return self.get_paginated_response(OutsourcingOrderReadSerializer(
            page, many=True, context={"request": request, "action_candidates": order_action_candidates(page)}
        ).data)

    def retrieve(self, request, pk=None):
        order = get_object_or_404(self.get_queryset(), pk=pk)
        response = Response({"data": OutsourcingOrderDetailSerializer(order, context={"request": request}).data})
        response["ETag"] = etag_for_instance(order)
        return response

    @action(
        detail=True,
        methods=["get"],
        url_path=r"product-files/(?P<file_id>[^/.]+)",
    )
    def product_file(self, request, pk=None, file_id=None):
        order = get_object_or_404(accessible_outsourcing_orders(request).only("pk"), pk=pk)
        business_file = get_object_or_404(
            BusinessFile.objects.filter(
                schedule_products__outsourcing_order_products__order=order,
                pk=file_id,
                archived_at__isnull=True,
            ).distinct()
        )
        if business_file.scan_status not in USABLE_FILE_SCAN_STATUSES:
            raise ValidationError({"file": "文件尚未通过安全扫描，暂不能查看。"})
        media_root = Path(settings.MEDIA_ROOT).resolve()
        storage_path = (media_root / business_file.storage_key).resolve()
        try:
            storage_path.relative_to(media_root)
        except ValueError as exc:
            raise Http404("文件路径无效。") from exc
        if not storage_path.is_file():
            raise Http404("文件不存在。")
        response = FileResponse(storage_path.open("rb"), content_type=business_file.content_type)
        response["Content-Disposition"] = f'inline; filename="{business_file.original_name}"'
        return response

    def create(self, request):
        serializer = OutsourcingOrderWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        get_object_or_404(outsourcing_source_schedules(request, craft_id=serializer.validated_data["craft_id"]), pk=serializer.validated_data["schedule_id"])
        order, created = create_order(
            validated_data=dict(serializer.validated_data),
            actor_employee=request.employee,
            request=request,
        )
        order = self.get_queryset().get(pk=order.pk)
        response = Response(
            {"data": OutsourcingOrderDetailSerializer(order, context={"request": request}).data},
            status=201 if created else 200,
        )
        response["ETag"] = etag_for_instance(order)
        return response

    def destroy(self, request, pk=None):
        current = get_object_or_404(self.get_queryset(), pk=pk)
        delete_order(
            order_id=current.pk,
            actor_employee=request.employee,
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        get_object_or_404(self.get_queryset(), pk=pk)
        serializer = OutsourcingOrderCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = cancel_order(
            order_id=pk,
            reason=serializer.validated_data["reason"],
            actor_employee=request.employee,
            request=request,
        )
        order = self.get_queryset().get(pk=order.pk)
        response = Response({"data": OutsourcingOrderDetailSerializer(order, context={"request": request}).data})
        response["ETag"] = etag_for_instance(order)
        return response

    @action(detail=True, methods=["post"], url_path="revoke-dispatched")
    def revoke_dispatched(self, request, pk=None):
        if not request.user.has_perm("outsourcing.return_raw_outsourcingorder"):
            raise PermissionDenied("撤销已发料外发单还需要外发原料退回权限。")
        current = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = OutsourcingOrderRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from ..reconciliation_services import revoke_dispatched_order

        order = revoke_dispatched_order(
            order_id=current.pk,
            request_id=serializer.validated_data["request_id"],
            reason=serializer.validated_data["reason"],
            actor_employee=request.employee,
            request=request,
        )
        order = self.get_queryset().get(pk=order.pk)
        response = Response({"data": OutsourcingOrderDetailSerializer(order, context={"request": request}).data})
        response["ETag"] = etag_for_instance(order)
        return response

    @action(detail=True, methods=["post"], url_path="confirm-dispatch")
    def confirm_dispatch(self, request, pk=None):
        current = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = OutsourcingDispatchConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = confirm_dispatch(
            order_id=current.pk,
            request_id=serializer.validated_data["request_id"],
            line_inputs=serializer.validated_data["lines"],
            remark=serializer.validated_data["remark"],
            actor_employee=request.employee,
            request=request,
        )
        order = self.get_queryset().get(pk=order.pk)
        response = Response({"data": OutsourcingOrderDetailSerializer(order, context={"request": request}).data})
        response["ETag"] = etag_for_instance(order)
        return response

    @action(detail=True, methods=["get"], url_path="dispatch-context")
    def dispatch_context(self, request, pk=None):
        order = get_object_or_404(self.get_queryset(), pk=pk)
        from apps.material_issues.p4_services import assert_legacy_original_route
        assert_legacy_original_route(order)
        if order.status != OutsourcingOrderStatus.PENDING_DISPATCH:
            raise ValidationError({"order": "只有待外发单据可以准备仓库发料。"})
        return Response({"data": dispatch_context(order=order)})

    @action(detail=True, methods=["post"], url_path="confirm-return")
    def confirm_return(self, request, pk=None):
        current = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = OutsourcingReturnConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = confirm_return(
            order_id=current.pk,
            request_id=serializer.validated_data["request_id"],
            factory_id=serializer.validated_data["factory_id"],
            good_zone_id=serializer.validated_data["good_zone_id"],
            defective_zone_id=serializer.validated_data["defective_zone_id"],
            received_by_employee_id=serializer.validated_data["received_by_employee_id"],
            return_date=serializer.validated_data["return_date"],
            delivery_note_number=serializer.validated_data["delivery_note_number"],
            line_inputs=serializer.validated_data["lines"],
            raw_inputs=serializer.validated_data["raw_inputs"],
            remark=serializer.validated_data["remark"],
            actor_employee=request.employee,
            request=request,
        )
        order = self.get_queryset().get(pk=order.pk)
        response = Response({"data": OutsourcingOrderDetailSerializer(order, context={"request": request}).data})
        response["ETag"] = etag_for_instance(order)
        return response

    @action(detail=True, methods=["get"])
    def reconciliation(self, request, pk=None):
        from ..reconciliation_services import reconciliation
        order = get_object_or_404(self.get_queryset(), pk=pk)
        response = Response({"data": reconciliation(order)})
        response["ETag"] = etag_for_instance(order)
        return response

    def _flow_response(self, order, request):
        order = self.get_queryset().get(pk=order.pk)
        response = Response({"data": OutsourcingOrderDetailSerializer(order, context={"request": request}).data})
        response["ETag"] = etag_for_instance(order)
        return response

    @action(detail=True, methods=["post"], url_path="confirm-raw-return")
    def confirm_raw_return(self, request, pk=None):
        from ..reconciliation_services import confirm_raw_return
        current = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = RawReturnWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = confirm_raw_return(order_id=current.pk, actor_employee=request.employee, request=request, **serializer.validated_data)
        return self._flow_response(order, request)

    @action(detail=True, methods=["post"], url_path="confirm-reconciliation")
    def confirm_reconciliation(self, request, pk=None):
        from ..reconciliation_services import confirm_reconciliation
        current = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = ReconciliationWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = confirm_reconciliation(order_id=current.pk, actor_employee=request.employee, request=request, **serializer.validated_data)
        return self._flow_response(order, request)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        from ..reconciliation_services import complete_order
        current = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = CompleteWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = complete_order(order_id=current.pk, actor_employee=request.employee, request=request, **serializer.validated_data)
        return self._flow_response(order, request)

    @action(detail=False, methods=["get"])
    def options(self, request):
        crafts = Craft.objects.filter(
            craft_type=CraftType.EXTERNAL,
            status=RecordStatus.ACTIVE,
            outsourcing_code__in=SUPPORTED_OUTSOURCING_CRAFT_CODES,
        ).order_by("name", "id")
        crafts = filter_crafts(crafts, request, "outsourcing.view_outsourcingorder", "pk")
        factories = factories_with_context(OutsourcingFactory.objects.filter(status=FactoryStatus.ACTIVE)).order_by("name", "id")
        if enabled():
            factories = factories.filter(craft_links__craft__in=crafts).distinct()
        visible_craft_ids = set(crafts.values_list("pk", flat=True))
        semi_finished_zones = WarehouseZone.objects.filter(
            status=InventoryRecordStatus.ACTIVE,
            warehouse__status=InventoryRecordStatus.ACTIVE,
            warehouse__warehouse_type=WarehouseType.SEMI_FINISHED,
        ).select_related("warehouse").order_by("warehouse__warehouse_name", "zone_name", "id")
        defective_zones = WarehouseZone.objects.filter(
            status=InventoryRecordStatus.ACTIVE,
            warehouse__status=InventoryRecordStatus.ACTIVE,
            warehouse__warehouse_type=WarehouseType.DEFECTIVE,
        ).select_related("warehouse").order_by("warehouse__warehouse_name", "zone_name", "id")
        receivers = active_department_employees("DEPT_WAREHOUSE").order_by("employee_code", "id")
        return Response({"data": {
            "crafts": [
                {"id": str(item.pk), "name": item.name, "outsourcing_code": item.outsourcing_code}
                for item in crafts
            ],
            "factories": [
                {
                    "id": str(factory.pk),
                    "name": factory.name,
                    "crafts": [
                        {"id": str(link.craft_id), "name": link.craft_name_snapshot}
                        for link in factory.prefetched_craft_links if not enabled() or link.craft_id in visible_craft_ids
                    ],
                }
                for factory in factories
            ],
            "statuses": [{"value": value, "label": label} for value, label in OutsourcingOrderStatus.choices],
            "semi_finished_zones": [
                {
                    "id": str(item.pk),
                    "name": f"{item.warehouse.warehouse_name} / {item.zone_name}",
                }
                for item in semi_finished_zones
            ],
            "defective_zones": [
                {"id": str(item.pk), "name": f"{item.warehouse.warehouse_name} / {item.zone_name}"}
                for item in defective_zones
            ],
            "receivers": [
                {"id": str(item.pk), "name": item.display_name, "employee_code": item.employee_code}
                for item in receivers
            ],
            "bom_confirmation_rule": "LATEST_VERIFIED",
            "material_overage_rule": "SHARED_CONFIRMED_ALLOWANCE",
        }})

    @action(detail=False, methods=["get"], url_path="source-plans")
    def source_plans(self, request):
        craft_id = _uuid(request.query_params.get("craft_id", "").strip(), "craft_id")
        if not craft_id:
            raise ValidationError({"craft_id": "请先选择厂外工艺。"})
        craft = get_object_or_404(
            Craft.objects.filter(
                craft_type=CraftType.EXTERNAL,
                status=RecordStatus.ACTIVE,
                outsourcing_code__in=SUPPORTED_OUTSOURCING_CRAFT_CODES,
            ),
            pk=craft_id,
        )
        require_craft(request, "outsourcing.view_outsourcingorder", craft.pk)
        matched_links = ProductionScheduleProductCraft.objects.filter(
            craft=craft, craft_type_snapshot=CraftType.EXTERNAL, removed_at__isnull=True,
        )
        requested_product_id = _uuid(
            request.query_params.get("schedule_product_id", "").strip(), "schedule_product_id"
        )
        if requested_product_id:
            matched_links = matched_links.filter(schedule_product_id=requested_product_id)
        matched_schedule_ids = matched_links.values("schedule_product__schedule_id")
        matched_product_ids = matched_links.values("schedule_product_id")
        schedules = schedules_with_context(
            outsourcing_source_schedules(request, craft_id=craft_id).filter(
                record_status=ScheduleStatus.ACTIVE, id__in=matched_schedule_ids,
            )
        )
        keyword = request.query_params.get("search", "").strip()
        if len(keyword) > 200:
            raise ValidationError({"search": "搜索内容不能超过 200 个字符。"})
        if keyword:
            matched_product_search = Q(products__id__in=matched_product_ids, products__removed_at__isnull=True) & (
                Q(products__product_snapshot__product_number__icontains=keyword)
                | Q(products__product_snapshot__item_number__icontains=keyword)
                | Q(products__product_snapshot__product_name__icontains=keyword)
            )
            schedules = schedules.filter(
                Q(schedule_number__icontains=keyword)
                | Q(production_task__task_number__icontains=keyword)
                | matched_product_search
            ).distinct()
        schedules = schedules.order_by("-created_at", "-id")
        page = self.paginate_queryset(schedules)
        data = []
        for schedule in page:
            products = []
            for product in schedule.active_products:
                if any(link.craft_id == craft.pk and link.craft_type_snapshot == CraftType.EXTERNAL for link in product.active_crafts):
                    snapshot = product.product_snapshot or {}
                    products.append({
                        "id": str(product.pk),
                        "product_line_id": str(product.product_line_id),
                        "product_number": snapshot.get("product_number", ""),
                        "item_number": snapshot.get("item_number", ""),
                        "product_name": snapshot.get("product_name", ""),
                        "specification": snapshot.get("specification", ""),
                        "color_name": snapshot.get("color_name", ""),
                        "planned_quantity": product.planned_quantity,
                        "source_quantity": product.source_quantity_snapshot,
                        "unit_name": product.unit_name_snapshot,
                        "image_file_id": str(product.image_file_id) if product.image_file_id else None,
                        "craft_name": craft.name,
                    })
            source = schedule.source_snapshot or {}
            data.append({
                "id": str(schedule.pk),
                "schedule_number": schedule.schedule_number,
                "production_task_id": str(schedule.production_task_id),
                "production_task_number": schedule.production_task.task_number,
                "production_task_status": schedule.production_task.status,
                "production_task_status_display": schedule.production_task.get_status_display(),
                "planned_start_date": source.get("planned_start_date"),
                "planned_end_date": source.get("planned_end_date"),
                "delivery_date": source.get("delivery_date"),
                "schedule_date": schedule.created_at.date().isoformat(),
                "matching_product_count": len(products),
                "products": products,
            })
        return self.get_paginated_response(data)

    @action(
        detail=False,
        methods=["get"],
        url_path=r"source-products/(?P<schedule_product_id>[^/.]+)/bom",
    )
    def source_product_bom(self, request, schedule_product_id=None):
        craft_id = _uuid(request.query_params.get("craft_id", "").strip(), "craft_id")
        if not craft_id:
            raise ValidationError({"craft_id": "请先选择厂外工艺。"})
        craft = get_object_or_404(
            Craft.objects.filter(
                craft_type=CraftType.EXTERNAL,
                status=RecordStatus.ACTIVE,
                outsourcing_code__in=SUPPORTED_OUTSOURCING_CRAFT_CODES,
            ),
            pk=craft_id,
        )
        require_craft(request, "outsourcing.view_outsourcingorder", craft.pk)
        product_id = _uuid(schedule_product_id, "schedule_product_id")
        schedule_ids = outsourcing_source_schedules(request, craft_id=craft_id).filter(
            record_status=ScheduleStatus.ACTIVE,
        ).values("id")
        schedule_product = get_object_or_404(
            ProductionScheduleProduct.objects.select_related(
                "schedule", "product_line", "unit", "image_file",
            ).filter(
                pk=product_id,
                schedule_id__in=schedule_ids,
                removed_at__isnull=True,
            )
        )
        if not ProductionScheduleProductCraft.objects.filter(
            schedule_product=schedule_product,
            craft=craft,
            craft_type_snapshot=CraftType.EXTERNAL,
            removed_at__isnull=True,
        ).exists():
            raise ValidationError({"schedule_product_id": "该排产产品不包含所选厂外工艺。"})

        line_images = BomLineImage.objects.select_related("business_file")
        lines = BomLine.objects.prefetch_related(
            Prefetch("images", queryset=line_images),
        )
        bom = (
            Bom.objects.filter(
                product_line=schedule_product.product_line,
                archived_at__isnull=True,
            )
            .prefetch_related(Prefetch("sections__lines", queryset=lines))
            .order_by("-version_number", "-updated_at", "-id")
            .first()
        )
        snapshot = schedule_product.product_snapshot or {}
        response_data = {
            "product": {
                "schedule_product_id": str(schedule_product.pk),
                "product_line_id": str(schedule_product.product_line_id),
                "product_number": snapshot.get("product_number", ""),
                "item_number": snapshot.get("item_number", ""),
                "product_name": snapshot.get("product_name", ""),
                "specification": snapshot.get("specification", ""),
                "color_name": snapshot.get("color_name", ""),
                "source_quantity": schedule_product.source_quantity_snapshot,
                "planned_quantity": schedule_product.planned_quantity,
                "unit_name": schedule_product.unit_name_snapshot,
                "image_file_id": str(schedule_product.image_file_id) if schedule_product.image_file_id else None,
            },
            "craft": {
                "id": str(craft.pk),
                "name": craft.name,
                "outsourcing_code": craft.outsourcing_code,
            },
            "bom": None,
            "processing_section_label": "管材类" if craft.outsourcing_code == OutsourcingCode.POWDER_COATING else "裁剪明细",
            "processing_items": [],
            "material_categories": [],
            "material_items": [],
        }
        if bom is None:
            return Response({"data": response_data})

        response_data["bom"] = {
            "id": str(bom.pk),
            "bom_number": bom.bom_number,
            "version_number": bom.version_number,
            "status": bom.status,
            "status_display": bom.get_status_display(),
        }
        processing_titles = {"管材类"} if craft.outsourcing_code == OutsourcingCode.POWDER_COATING else {"裁剪明细"}
        material_titles = {"管材类", "五金件"} if craft.outsourcing_code == OutsourcingCode.POWDER_COATING else {"面料类", "辅料类"}
        processing_lines = []
        material_lines = []
        for section in bom.sections.all():
            title = section.title.strip()
            if title in processing_titles:
                processing_lines.extend((title, line) for line in section.lines.all())
            if title in material_titles:
                material_lines.extend((title, line) for line in section.lines.all())

        outsourced_by_line = {
            str(item["bom_line_id"]): item["total"] or 0
            for item in OutsourcingProcessingItem.objects.filter(
                bom_line_id__in=[line.pk for _, line in processing_lines],
                order_product__order__craft=craft,
            ).exclude(
                order_product__order__status=OutsourcingOrderStatus.CANCELLED,
            ).values("bom_line_id").annotate(total=Sum("quantity"))
        }
        dispatched_by_line = {
            str(item["bom_line_id"]): item["total"] or 0
            for item in OutsourcingProcessingItem.objects.filter(
                bom_line_id__in=[line.pk for _, line in processing_lines],
                order_product__order__craft=craft,
                order_product__order__status__in=(
                    OutsourcingOrderStatus.PROCESSING,
                    OutsourcingOrderStatus.PARTIAL_RETURN,
                    OutsourcingOrderStatus.CLOSED,
                    OutsourcingOrderStatus.COMPLETED,
                ),
            ).values("bom_line_id").annotate(total=Sum("quantity"))
        }
        for section_title, line in processing_lines:
            line_data = BomLineSerializer(line, context={"request": request}).data
            required_quantity = processing_required_quantity(
                line,
                schedule_product.source_quantity_snapshot,
            )
            outsourced_quantity = outsourced_by_line.get(str(line.pk), Decimal("0"))
            dispatched_quantity = dispatched_by_line.get(str(line.pk), Decimal("0"))
            available_quantity = (
                max(required_quantity - outsourced_quantity, Decimal("0"))
                if required_quantity is not None
                else Decimal("0")
            )
            response_data["processing_items"].append({
                "id": str(line.pk),
                "section_title": section_title,
                "part_name": line.part_name or line.material or line.raw_material,
                "category": line_data.get("cutting_category") or line.category or section_title,
                "specification": line.specification,
                "material": line.material,
                "color": _line_color(line_data, section_title),
                "bom_attributes": bom_attribute_fields(line),
                "reference_usage": processing_reference_usage(line),
                "technical_reference": line.notes,
                "required_quantity": required_quantity,
                "outsourced_quantity": outsourced_quantity,
                "dispatched_quantity": dispatched_quantity,
                "available_quantity": available_quantity,
                "unit": line.unit.strip(),
                "inbound_quantity": required_quantity,
                "inbound_unit": line.unit.strip(),
                "quantity_error": (
                    "缺少有效的 BOM 单个用量"
                    if required_quantity is None
                    else ("缺少 BOM 单位" if not line.unit.strip() else "")
                ),
                "image_url": _line_image_url(line_data),
            })

        seen_categories = set()
        for section_title, line in material_lines:
            line_data = BomLineSerializer(line, context={"request": request}).data
            category, category_label = _material_category(section_title)
            if category not in seen_categories:
                response_data["material_categories"].append({"value": category, "label": category_label})
                seen_categories.add(category)
            required = material_required_quantity(
                line,
                bom,
                schedule_product.source_quantity_snapshot,
            )
            reference_quantity = required["quantity"]
            material_number = (
                line_data.get("hardware_material_number")
                or line_data.get("cutting_material_number")
                or line.source_serial
            )
            response_data["material_items"].append({
                "id": str(line.pk),
                "section_title": section_title,
                "category": category,
                "category_label": category_label,
                "material_number": material_number,
                "name": line.part_name or line.material or line.raw_material,
                "specification": line.specification,
                "color": _line_color(line_data, section_title),
                "bom_attributes": bom_attribute_fields(line),
                "unit_consumption": line.unit_consumption,
                "reference_required_quantity": reference_quantity,
                "unit": required["source_unit"] or line.unit,
                "default_issue_quantity": reference_quantity,
                "quantity_source_field": required["source_field"],
                "quantity_source_text": required["source_text"],
                "quantity_parse_status": required["parse_status"],
                "procurement_required_quantity": required["procurement_quantity"],
                "procurement_source_field": required["procurement_source_field"],
                "procurement_source_text": required["procurement_source_text"],
                "procurement_unit": required["procurement_source_unit"] or line.unit,
                "procurement_parse_status": required["procurement_parse_status"],
                "quantity_error": (
                    "缺少 BOM 单个用量，无法计算外发总需求"
                    if required["parse_status"] == "MISSING"
                    else (
                        "缺少有效的采购换算数量"
                        if required["procurement_quantity"] is None
                        else ""
                    )
                ),
                "notes": line.notes,
                "image_url": _line_image_url(line_data),
            })
        from ..material_flow import enrich_source_context
        enrich_source_context(response_data, processing_lines, material_lines, schedule_product)
        return Response({"data": response_data})
