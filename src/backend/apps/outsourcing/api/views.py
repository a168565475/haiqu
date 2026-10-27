from apps.organizations.selectors import active_department_employees
from apps.access_control.resource_scopes import filter_crafts, enabled
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
from apps.inventory.models import RecordStatus as InventoryRecordStatus, WarehouseType, WarehouseZone
from apps.organizations.models import Employee, EmployeeStatus
from apps.production_scheduling.selectors import accessible_production_schedules
from apps.workshop_config.models import Craft, CraftType, OutsourcingCode, RecordStatus

from ..models import (
    FactoryStatus,
    OutsourcingFactory,
    OutsourcingOrderStatus,
)
from ..selectors import accessible_outsourcing_orders, factories_with_context, orders_with_context
from ..services import (
    SUPPORTED_OUTSOURCING_CRAFT_CODES,
    cancel_order,
    confirm_dispatch,
    confirm_return,
    create_factory,
    delete_order,
    disable_factory,
    dispatch_context,
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
)


def _uuid(value, field):
    if not value:
        return None
    try:
        return UUID(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field: f"{field} 参数不是有效 UUID。"}) from exc


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
    lookup_value_regex = '[0-9a-fA-F-]{36}'
    from ..warehouse_access import WarehouseActionReadPermission
    permission_classes = [HasActiveEmployee, WarehouseActionReadPermission]
    warehouse_read_actions = {'retrieve', 'options', 'reconciliation', 'product_file'}
    warehouse_read_permissions = ('outsourcing.confirm_dispatch_outsourcingorder',
                                 'outsourcing.confirm_return_outsourcingorder',
                                 'outsourcing.return_raw_outsourcingorder')
    action_permission_map = {
        "list": "outsourcing.view_outsourcingorder",
        "retrieve": "outsourcing.view_outsourcingorder",
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
    }

    def get_queryset(self):
        include_detail_records = self.action in {
            "retrieve", "cancel", "revoke_dispatched", "confirm_dispatch", "confirm_return",
        }
        from ..warehouse_access import warehouse_regular_orders, warehouse_stage
        queryset = (warehouse_regular_orders(self.request)
                    if self.action in self.warehouse_read_actions and warehouse_stage(self.request)
                    else accessible_outsourcing_orders(self.request))
        return orders_with_context(
            queryset,
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
        from ..warehouse_access import warehouse_regular_orders, warehouse_stage
        orders = warehouse_regular_orders(request) if warehouse_stage(request) else accessible_outsourcing_orders(request)
        order = get_object_or_404(orders.only("pk"), pk=pk)
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
        from ..warehouse_access import warehouse_crafts, warehouse_stage
        warehouse = warehouse_stage(request)
        crafts = Craft.objects.filter(
            craft_type=CraftType.EXTERNAL,
            status=RecordStatus.ACTIVE,
            outsourcing_code__in=SUPPORTED_OUTSOURCING_CRAFT_CODES,
        ).order_by("name", "id")
        crafts = (warehouse_crafts(request, crafts) if warehouse
                  else filter_crafts(crafts, request, "outsourcing.view_outsourcingorder", "pk"))
        factories = factories_with_context(OutsourcingFactory.objects.filter(status=FactoryStatus.ACTIVE)).order_by("name", "id")
        if warehouse or enabled():
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
                        for link in factory.prefetched_craft_links if not (warehouse or enabled()) or link.craft_id in visible_craft_ids
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
