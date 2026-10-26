import re
from copy import copy
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from django.conf import settings
from django.db import IntegrityError, connection
from django.db.models import Count, Exists, OuterRef, Prefetch, Q, Sum
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.files.models import USABLE_FILE_SCAN_STATUSES
from apps.boms.models import Bom, BomStatus
from apps.production_tasks.models import ProductionTask
from apps.production_tasks.models import ProductionTaskProduct
from apps.production_tasks.selectors import accessible_production_tasks
from apps.reference_data.models import Currency, ReferenceStatus
from apps.sales_orders.presentation import specification_display

from ..source_access import purchase_order_access
from ..sample_purchase_services import sample_procurement_sources, sample_source
from ..models import (
    PurchaseContractTemplate,
    PurchaseContractTemplateStatus,
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseReturnStatus,
    Supplier,
    SupplierCategory,
    SupplierPaymentCycle,
    SupplierPurchaseSheet,
    SupplierPurchaseSheetStatus,
    SupplierType,
)
from ..selectors import (
    active_purchase_orders,
    filter_purchase_return_status,
    active_suppliers,
    production_tasks_with_purchase_sources,
    purchase_orders_by_product,
    purchase_orders_with_product_ids,
    purchase_orders_with_context,
    search_purchase_orders,
    search_suppliers,
    suppliers_with_context,
)
from ..services import (
    create_purchase_order,
    create_supplier,
    delete_purchase_order,
    evaluate_purchase_source,
    public_purchase_source,
    confirm_purchase_order,
    update_purchase_order,
    update_supplier,
)
from ..completion_services import complete_purchase_order
from ..purchase_sheet_xlsx import build_supplier_purchase_sheet_xlsx
from ..purchase_sheet_preview import build_purchase_sheet_preview
from ..fabric_purchase_sheet_template import FabricPurchaseSheetTemplateError
from ..purchase_sheet_services import (
    create_purchase_contract_template,
    create_supplier_purchase_sheet_version,
    generate_supplier_purchase_sheets,
    publish_supplier_purchase_sheets,
    publish_supplier_purchase_sheet,
    remove_supplier_purchase_sheet_line_image,
    remove_supplier_purchase_sheet_seal_image,
    replace_supplier_purchase_sheet_line_image,
    replace_supplier_purchase_sheet_seal_image,
    update_purchase_contract_template,
    update_supplier_purchase_sheet,
    normalize_sheet_content,
)
from .serializers import (
    PurchaseContractTemplateInputSerializer,
    PurchaseContractTemplateSerializer,
    PurchaseOrderCreateSerializer,
    PurchaseOrderCompletionSerializer,
    PurchaseOrderDetailSerializer,
    PurchaseOrderListSerializer,
    PurchaseOrderUpdateSerializer,
    PurchaseSheetGenerateSerializer,
    SupplierPurchaseSheetSerializer,
    SupplierPurchaseSheetUpdateSerializer,
    SupplierDetailSerializer,
    SupplierInputSerializer,
    SupplierListSerializer,
)


SUPPLIER_NUMBER_PATTERN = re.compile(r"^GYS([0-9]{5})$")
SUPPLIER_NUMBER_START = 266


def next_supplier_number_preview():
    candidates = [SUPPLIER_NUMBER_START]
    latest = Supplier.objects.order_by("-supplier_number").values_list("supplier_number", flat=True).first()
    if latest:
        matched = SUPPLIER_NUMBER_PATTERN.fullmatch(latest)
        if matched:
            candidates.append(int(matched.group(1)) + 1)
    with connection.cursor() as cursor:
        cursor.execute("SELECT last_value, is_called FROM haiqu_supplier_number_seq")
        last_value, is_called = cursor.fetchone()
    candidates.append(last_value + 1 if is_called else last_value)
    return f"GYS{max(candidates):05d}"


class SupplierViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "list": "procurement.view_supplier",
        "retrieve": "procurement.view_supplier",
        "stats": "procurement.view_supplier",
        "options": "procurement.view_supplier",
        "create": "procurement.add_supplier",
        "update": "procurement.change_supplier",
        "partial_update": "procurement.change_supplier",
    }

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return SupplierInputSerializer
        if self.action == "retrieve":
            return SupplierDetailSerializer
        return SupplierListSerializer

    def get_queryset(self):
        queryset = active_suppliers()
        supplier_type = self.request.query_params.get("supplier_type", "").strip().upper()
        if supplier_type:
            if supplier_type not in SupplierType.values:
                raise ValidationError({"supplier_type": "供应商类型参数不正确。"})
            queryset = queryset.filter(supplier_type=supplier_type)

        category = self.request.query_params.get("category", "").strip().upper()
        if category:
            if category not in SupplierCategory.values:
                raise ValidationError({"category": "供应商类别参数不正确。"})
            queryset = queryset.filter(supplier_categories__contains=[category])

        payment_cycle = self.request.query_params.get("payment_cycle", "").strip().upper()
        if payment_cycle:
            if payment_cycle not in SupplierPaymentCycle.values:
                raise ValidationError({"payment_cycle": "付款周期参数不正确。"})
            queryset = queryset.filter(payment_cycle=payment_cycle)

        disabled_value = self.request.query_params.get("is_disabled", "").strip().lower()
        if disabled_value:
            if disabled_value not in {"true", "false", "1", "0"}:
                raise ValidationError({"is_disabled": "是否禁用参数必须为 true 或 false。"})
            queryset = queryset.filter(is_disabled=disabled_value in {"true", "1"})

        queryset = search_suppliers(queryset, self.request.query_params.get("q", "").strip())
        ordering = self.request.query_params.get("ordering", "-supplier_number").strip()
        allowed_ordering = {
            "supplier_number",
            "-supplier_number",
            "supplier_name",
            "-supplier_name",
            "updated_at",
            "-updated_at",
        }
        if ordering not in allowed_ordering:
            raise ValidationError({"ordering": "排序参数不正确。"})
        return suppliers_with_context(queryset.order_by(ordering, "id"))

    def actor_employee(self):
        return getattr(self.request, "employee", None)

    def response_with_etag(self, instance, response_status=status.HTTP_200_OK):
        response = Response(
            {"data": SupplierDetailSerializer(instance).data},
            status=response_status,
        )
        response["ETag"] = etag_for_instance(instance)
        return response

    def retrieve(self, request, *args, **kwargs):
        return self.response_with_etag(self.get_object())

    def create(self, request, *args, **kwargs):
        serializer = SupplierInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            supplier = create_supplier(
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except IntegrityError as exc:
            raise ValidationError({"detail": "供应商编号生成冲突，请重试。"}) from exc
        supplier = suppliers_with_context().get(pk=supplier.pk)
        return self.response_with_etag(supplier, status.HTTP_201_CREATED)

    def _update(self, request, *, partial):
        current = self.get_object()
        serializer = SupplierInputSerializer(current, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            supplier = update_supplier(
                supplier_id=current.pk,
                validated_data=serializer.validated_data,
                actor_employee=self.actor_employee(),
                request=request,
            )
        except Supplier.DoesNotExist as exc:
            raise NotFound("供应商不存在或已归档。") from exc
        supplier = suppliers_with_context().get(pk=supplier.pk)
        return self.response_with_etag(supplier)

    def update(self, request, *args, **kwargs):
        return self._update(request, partial=kwargs.pop("partial", False))

    def partial_update(self, request, *args, **kwargs):
        return self._update(request, partial=True)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        counts = active_suppliers().aggregate(
            total=Count("id"),
            material=Count("id", filter=Q(supplier_type=SupplierType.MATERIAL)),
            finished=Count("id", filter=Q(supplier_type=SupplierType.FINISHED)),
            disabled=Count("id", filter=Q(is_disabled=True)),
        )
        return Response({"data": counts})

    @action(detail=False, methods=["get"])
    def options(self, request):
        return Response(
            {
                "data": {
                    "supplier_types": [
                        {"value": value, "label": label} for value, label in SupplierType.choices
                    ],
                    "supplier_categories": [
                        {"value": value, "label": label} for value, label in SupplierCategory.choices
                    ],
                    "payment_cycles": [
                        {"value": value, "label": label} for value, label in SupplierPaymentCycle.choices
                    ],
                    "next_supplier_number": next_supplier_number_preview(),
                }
            }
        )


class PurchaseOrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "list": "procurement.view_purchaseorder",
        "retrieve": "procurement.view_purchaseorder",
        "stats": "procurement.view_purchaseorder",
        "details": ("procurement.view_purchaseorder", "inventory.receive_material", "inventory.quality_confirm_material"),
        "filter_options": "procurement.view_purchaseorder",
        "options": "procurement.add_purchaseorder",
        "source": "procurement.add_purchaseorder",
        "create": "procurement.add_purchaseorder",
        "update": "procurement.add_purchaseorder",
        "partial_update": "procurement.add_purchaseorder",
        "destroy": "procurement.delete_purchaseorder",
        "confirm": "procurement.submit_purchaseorder",
        "submit": "procurement.submit_purchaseorder",
        "complete": "procurement.submit_purchaseorder",
        "sheet_options": "procurement.view_purchaseorder",
        "generate_sheets": "procurement.add_purchaseorder",
    }

    def get_serializer_class(self):
        if self.action == "create":
            return PurchaseOrderCreateSerializer
        if self.action == "details":
            from .read_details import PurchaseOrderReadDetailSerializer
            return PurchaseOrderReadDetailSerializer
        if self.action in {"update", "partial_update"}:
            return PurchaseOrderUpdateSerializer
        if self.action == "retrieve":
            return PurchaseOrderDetailSerializer
        return PurchaseOrderListSerializer

    def get_queryset(self):
        queryset = active_purchase_orders().filter(
            purchase_order_access(self._accessible_task_ids(), self.request)
        )
        return_status = self.request.query_params.get("return_status", "").strip()
        if return_status:
            if return_status not in ["NONE", "MISSING", *PurchaseReturnStatus.values]:
                raise ValidationError({"return_status": "退货状态参数不正确。"})
            queryset = filter_purchase_return_status(queryset, return_status)
        status_value = self.request.query_params.get("status", "").strip().upper()
        if status_value:
            if status_value not in PurchaseOrderStatus.values:
                raise ValidationError({"status": "采购订单状态参数不正确。"})
            queryset = queryset.filter(status=status_value)

        production_task_id = self.request.query_params.get("production_task_id", "").strip()
        if production_task_id:
            self._uuid_value(production_task_id, "production_task_id")
            queryset = queryset.filter(production_task_id=production_task_id)

        currency_id = self.request.query_params.get("currency_id", "").strip()
        if currency_id:
            self._uuid_value(currency_id, "currency_id")
            queryset = queryset.filter(currency_id=currency_id)

        supplier_id = self.request.query_params.get("supplier_id", "").strip()
        if supplier_id:
            self._uuid_value(supplier_id, "supplier_id")
            queryset = queryset.filter(lines__supplier_id=supplier_id)

        created_after = self.request.query_params.get("created_after", "").strip()
        if created_after:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", created_after):
                raise ValidationError({"created_after": "创建日期参数必须为 YYYY-MM-DD。"})
            try:
                parsed_date = parse_date(created_after)
            except ValueError as exc:
                raise ValidationError({"created_after": "创建日期不是有效日期。"}) from exc
            if parsed_date is None:
                raise ValidationError({"created_after": "创建日期不是有效日期。"})
            queryset = queryset.filter(created_at__date__gte=parsed_date)

        mailed_value = self.request.query_params.get("is_mailed", "").strip().lower()
        if mailed_value:
            if mailed_value in {"1", "true"}:
                queryset = queryset.filter(is_mailed=True)
            elif mailed_value in {"0", "false"}:
                queryset = queryset.filter(is_mailed=False)
            elif mailed_value in {"null", "pending"}:
                queryset = queryset.filter(is_mailed__isnull=True)
            else:
                raise ValidationError({"is_mailed": "是否邮寄参数必须为 true、false 或 null。"})

        queryset = search_purchase_orders(queryset, self.request.query_params.get("q", "").strip())
        ordering = self.request.query_params.get("ordering", "-created_at").strip()
        allowed_ordering = {
            "created_at",
            "-created_at",
            "updated_at",
            "-updated_at",
            "order_number",
            "-order_number",
            "total_amount",
            "-total_amount",
        }
        if ordering not in allowed_ordering:
            raise ValidationError({"ordering": "排序参数不正确。"})
        queryset = purchase_orders_with_context(
            queryset.distinct().order_by(ordering, "-id"),
            read_optimized=self.action in {"list", "retrieve", "details"},
        )
        if self.action == "details":
            from .read_details import with_read_detail_records
            from apps.access_control import module_policy, sales_policy
            if module_policy.enabled():
                can_read_purchase = module_policy.has_permission(self.request, "procurement.view_purchaseorder")
            elif sales_policy.enabled():
                can_read_purchase = sales_policy.has_permission(self.request, "procurement.view_purchaseorder")
            else:
                can_read_purchase = self.request.user.has_perm("procurement.view_purchaseorder")
            # 仓库入口沿用原有范围，不因新增详情暴露尚未进入采购执行的草稿。
            if not can_read_purchase:
                queryset = queryset.filter(status__in=[PurchaseOrderStatus.PURCHASING, PurchaseOrderStatus.COMPLETED])
            queryset = with_read_detail_records(queryset)
        return queryset

    def _accessible_tasks(self):
        return accessible_production_tasks(self.request).filter(archived_at__isnull=True)

    @action(detail=True, methods=["get"])
    def details(self, request, pk=None):
        from .read_details import PurchaseOrderReadDetailSerializer
        return Response({"data": PurchaseOrderReadDetailSerializer(self.get_object()).data})

    def _accessible_task_ids(self):
        return self._accessible_tasks().order_by().values_list("id", flat=True)

    @staticmethod
    def _uuid_value(value, field_name):
        try:
            return UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise ValidationError({field_name: f"{field_name} 参数不正确。"}) from exc

    @staticmethod
    def _default_currency():
        return Currency.objects.filter(
            code="CNY",
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).first()

    @staticmethod
    def _task_payload(task, *, include_products=False):
        payload = {
            "id": str(task.pk),
            "task_number": task.task_number,
            "order_number": task.order_number,
            "customer_name": task.customer_account.account_name if task.customer_account_id else "",
            "status": task.status,
            "status_display": task.get_status_display(),
            "delivery_date": task.delivery_date,
        }
        if not include_products:
            return payload
        products = getattr(task, "purchase_source_products", None)
        if products is None:
            products = task.products.select_related("unit").order_by("line_number", "id")
        payload["products"] = [
            {
                "id": str(product.pk),
                "line_number": product.line_number,
                "product_number": product.product_number_snapshot,
                "product_code": product.product_code_snapshot,
                "item_number": product.item_number_snapshot,
                "product_name": product.product_name_snapshot,
                "specification": product.specification_snapshot,
                # 适配订单颜色快照，避免展示时查询可能已变更的颜色字典。
                "specification_display": specification_display(SimpleNamespace(
                    specification_snapshot=product.specification_snapshot,
                    customer_specification_snapshot=product.customer_specification_snapshot,
                    customer_color_snapshot=product.customer_color_snapshot,
                    color_snapshot=product.color_name_snapshot,
                    material_snapshot=product.material_snapshot,
                )),
                "material": product.material_snapshot,
                "color_card": product.color_card_snapshot,
                "color_name": product.color_name_snapshot,
                "color_code": product.color_code_snapshot,
                "order_quantity": str(product.quantity),
                "unit_code": product.unit.unit_code,
                "unit_name": product.unit.unit_name,
            }
            for product in products
        ]
        return payload

    def create(self, request, *args, **kwargs):
        serializer = PurchaseOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = create_purchase_order(
            validated_data=serializer.validated_data,
            allowed_task_ids=self._accessible_task_ids(),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        response = Response(
            {"data": PurchaseOrderDetailSerializer(order).data},
            status=status.HTTP_201_CREATED,
        )
        response["ETag"] = etag_for_instance(order)
        return response

    def retrieve(self, request, *args, **kwargs):
        order = self.get_object()
        response = Response({"data": PurchaseOrderDetailSerializer(order).data})
        response["ETag"] = etag_for_instance(order)
        return response

    def _update(self, request, *, partial):
        current = self.get_object()
        serializer = PurchaseOrderUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        order = update_purchase_order(
            order_id=current.pk,
            validated_data=serializer.validated_data,
            allowed_task_ids=self._accessible_task_ids(),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        response = Response({"data": PurchaseOrderDetailSerializer(order).data})
        response["ETag"] = etag_for_instance(order)
        return response

    def update(self, request, *args, **kwargs):
        return self._update(request, partial=kwargs.pop("partial", False))

    def partial_update(self, request, *args, **kwargs):
        return self._update(request, partial=True)

    def destroy(self, request, *args, **kwargs):
        delete_purchase_order(
            order_id=self._uuid_value(kwargs.get("pk"), "id"),
            allowed_task_ids=self._accessible_task_ids(),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _confirm(self, request, pk):
        order = confirm_purchase_order(
            order_id=self._uuid_value(pk, "id"),
            allowed_task_ids=self._accessible_task_ids(),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        response = Response({"data": PurchaseOrderDetailSerializer(order).data})
        response["ETag"] = etag_for_instance(order)
        return response

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, pk=None):
        return self._confirm(request, pk)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        """兼容旧客户端；新界面统一调用 confirm。"""
        return self._confirm(request, pk)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        serializer = PurchaseOrderCompletionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = complete_purchase_order(
            order_id=self._uuid_value(pk, "id"), remark=serializer.validated_data["remark"],
            allowed_task_ids=self._accessible_task_ids(),
            actor_employee=request.employee, request=request,
        )
        response = Response({"data": PurchaseOrderDetailSerializer(order).data})
        response["ETag"] = etag_for_instance(order)
        return response

    @action(detail=True, methods=["get"], url_path="sheet-options")
    def sheet_options(self, request, pk=None):
        order = self.get_object()
        lines = list(order.lines.all())
        suppliers = []
        grouped = {}
        for line in lines:
            if line.supplier_id is None:
                continue
            grouped.setdefault(line.supplier_id, []).append(line)
        templates = list(
            PurchaseContractTemplate.objects.filter(
                archived_at__isnull=True,
                status=PurchaseContractTemplateStatus.ACTIVE,
            )
            .prefetch_related("versions")
            .order_by("template_code", "id")
        )
        template_rows = []
        for template in templates:
            versions = list(template.versions.all())
            current = next(
                (item for item in versions if item.version_number == template.current_version_number),
                versions[0] if versions else None,
            )
            if current is None:
                continue
            template_rows.append(
                {
                    "id": str(template.pk),
                    "template_code": template.template_code,
                    "template_name": template.template_name,
                    "supplier_categories": list(template.supplier_categories),
                    "version_id": str(current.pk),
                    "version_number": current.version_number,
                    "version_name": current.version_name,
                }
            )
        for supplier_id, supplier_lines in sorted(grouped.items(), key=lambda item: item[1][0].supplier_number_snapshot):
            categories = list(supplier_lines[0].supplier_categories_snapshot)
            recommended = next(
                (
                    item["version_id"]
                    for item in template_rows
                    if set(item["supplier_categories"]) & set(categories)
                ),
                None,
            )
            suppliers.append(
                {
                    "supplier_id": str(supplier_id),
                    "supplier_number": supplier_lines[0].supplier_number_snapshot,
                    "supplier_name": supplier_lines[0].supplier_name_snapshot,
                    "supplier_categories": categories,
                    "line_count": len(supplier_lines),
                    "total_amount": format(sum((line.amount or 0 for line in supplier_lines)), "f"),
                    "recommended_template_version_id": recommended,
                }
            )
        existing_sheets = SupplierPurchaseSheet.objects.filter(
            purchase_order=order,
            is_current=True,
            archived_at__isnull=True,
        ).count()
        return Response(
            {
                "data": {
                    "purchase_order": PurchaseOrderDetailSerializer(order).data,
                    "suppliers": suppliers,
                    "templates": template_rows,
                    "existing_sheet_count": existing_sheets,
                }
            }
        )

    @action(detail=True, methods=["post"], url_path="generate-sheets")
    def generate_sheets(self, request, pk=None):
        serializer = PurchaseSheetGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sheets = generate_supplier_purchase_sheets(
            order_id=self._uuid_value(pk, "id"),
            assignments=serializer.validated_data["assignments"],
            allowed_task_ids=self._accessible_task_ids(),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        queryset = SupplierPurchaseSheet.objects.filter(pk__in=[item.pk for item in sheets]).select_related(
            "purchase_order",
            "purchase_order__production_task__sales_order",
            "supplier",
            "template_version__template",
            "updated_by_employee",
            "created_by_employee",
        ).prefetch_related("line_images__image_file")
        return Response(
            {"data": SupplierPurchaseSheetSerializer(queryset, many=True).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["get"], url_path="filter-options")
    def filter_options(self, request):
        orders = active_purchase_orders().filter(purchase_order_access(self._accessible_task_ids(), request))
        suppliers = Supplier.objects.filter(purchase_order_lines__purchase_order__in=orders).distinct().order_by("supplier_number")
        return Response({"data": {
            "suppliers": list(suppliers.values("id", "supplier_number", "supplier_name")),
            "production_tasks": [
                {"id": order.production_task_id, "task_number": order.production_task_number_snapshot, "order_number": order.sales_order_number_snapshot}
                for order in orders.filter(production_task__isnull=False)
                .order_by("production_task_id", "-created_at", "-id").distinct("production_task_id")
            ],
            "statuses": [{"value": value, "label": label} for value, label in PurchaseOrderStatus.choices],
        }})

    @action(detail=False, methods=["get"])
    def stats(self, request):
        queryset = active_purchase_orders().filter(
            purchase_order_access(self._accessible_task_ids(), self.request)
        )
        counts = queryset.aggregate(
            total=Count("id"),
            draft=Count("id", filter=Q(status=PurchaseOrderStatus.DRAFT)),
            submitted=Count("id", filter=Q(status=PurchaseOrderStatus.SUBMITTED)),
            purchasing=Count("id", filter=Q(status=PurchaseOrderStatus.PURCHASING)),
            completed=Count("id", filter=Q(status=PurchaseOrderStatus.COMPLETED)),
            mailed=Count("id", filter=Q(is_mailed=True)),
            unmailed=Count("id", filter=Q(is_mailed=False)),
            mailing_pending=Count("id", filter=Q(is_mailed__isnull=True)),
            incomplete_amount=Count("id", filter=Q(total_amount__isnull=True)),
        )
        amounts = []
        grouped = (
            queryset.filter(total_amount__isnull=False, currency__isnull=False)
            .values("currency_id", "currency_code_snapshot", "currency_symbol_snapshot")
            .annotate(order_count=Count("id"), total_amount=Sum("total_amount"))
            .order_by("currency_code_snapshot")
        )
        for item in grouped:
            amounts.append(
                {
                    "currency_id": str(item["currency_id"]),
                    "currency_code": item["currency_code_snapshot"],
                    "currency_symbol": item["currency_symbol_snapshot"],
                    "order_count": item["order_count"],
                    "total_amount": format(item["total_amount"], "f"),
                }
            )
        return Response({"data": {**counts, "amounts": amounts}})

    @extend_schema(parameters=[OpenApiParameter(
        name="scope", type=str, enum=["full", "suppliers", "sources", "detail"],
        description="默认 full 返回完整创建选项；sources 返回采购来源首步的轻量列表；detail 返回采购明细页所需的供应商和币种；suppliers 仅返回启用供应商。",
    )])
    @action(detail=False, methods=["get"])
    def options(self, request):
        scope = request.query_params.get("scope", "full")
        if scope not in {"full", "suppliers", "sources", "detail"}:
            raise ValidationError({"scope": "选项范围必须为 full、suppliers、sources 或 detail。"})

        if scope == "sources":
            bom_options = Bom.objects.filter(
                archived_at__isnull=True,
            ).only(
                "id", "product_line_id", "version_number", "status", "order_quantity", "line_count",
            ).order_by("-version_number", "-id")
            product_options = ProductionTaskProduct.objects.only(
                "id", "production_task_id", "quantity",
            ).prefetch_related(
                Prefetch("boms", queryset=bom_options, to_attr="purchase_source_boms"),
            ).order_by("line_number", "id")
            tasks = self._accessible_tasks().filter(Exists(Bom.objects.filter(
                production_task_id=OuterRef("pk"), archived_at__isnull=True,
            ))).select_related("customer_account").annotate(
                purchase_product_count=Count("products", distinct=True),
            ).prefetch_related(
                Prefetch("products", queryset=product_options, to_attr="purchase_source_products"),
                Prefetch("purchase_orders", queryset=purchase_orders_with_product_ids(), to_attr="purchase_source_orders"),
            ).order_by("-updated_at", "-id")
            task_rows = []
            for task in tasks:
                blockers = []
                existing_by_product = purchase_orders_by_product(task.purchase_source_orders)
                if task.status not in {"READY", "IN_PRODUCTION"}:
                    blockers.append({
                        "code": "TASK_NOT_READY",
                        "message": "生产任务单必须经 PMC 确认后，才能创建采购订单。",
                    })
                if None in existing_by_product:
                    blockers.append({
                        "code": "PURCHASE_PRODUCT_UNKNOWN",
                        "message": "已有采购单缺少可核实的产品明细，请先核实原单据。",
                    })
                if task.purchase_product_count == 0:
                    blockers.append({
                        "code": "BOM_MISSING",
                        "message": "生产订单没有产品明细，无法读取 BOM。",
                    })
                products = getattr(task, "purchase_source_products", [])
                verified_bom_count = 0
                pending_bom_count = 0
                missing_bom_count = 0
                stale_bom_count = 0
                empty_bom_count = 0
                purchased_product_count = 0
                for product in products:
                    if product.pk in existing_by_product:
                        purchased_product_count += 1
                        continue
                    latest_bom = (getattr(product, "purchase_source_boms", []) or [None])[0]
                    if latest_bom is None:
                        missing_bom_count += 1
                    elif latest_bom.status != BomStatus.VERIFIED:
                        pending_bom_count += 1
                    elif Decimal(latest_bom.order_quantity) != Decimal(product.quantity):
                        stale_bom_count += 1
                    elif latest_bom.line_count <= 0:
                        empty_bom_count += 1
                    else:
                        verified_bom_count += 1
                if task.purchase_product_count and verified_bom_count == 0:
                    if purchased_product_count == task.purchase_product_count:
                        blockers.append({
                            "code": "PURCHASE_ORDER_EXISTS",
                            "message": "该生产订单的所有产品均已建立采购订单。",
                        })
                    elif pending_bom_count:
                        blockers.append({
                            "code": "BOM_NOT_VERIFIED",
                            "message": "该订单最新 BOM 尚未确认，确认后才能采购。",
                        })
                    elif stale_bom_count:
                        blockers.append({
                            "code": "BOM_QUANTITY_STALE",
                            "message": "该订单最新 BOM 数量与订单数量不一致，请先更新并确认 BOM。",
                        })
                    elif empty_bom_count:
                        blockers.append({
                            "code": "BOM_EMPTY",
                            "message": "该订单最新 BOM 没有可采购明细。",
                        })
                    else:
                        blockers.append({
                            "code": "BOM_MISSING",
                            "message": "该订单没有已确认的有效 BOM。",
                        })
                if task.purchase_product_count and purchased_product_count == task.purchase_product_count:
                    source_status_display = "已建采购单"
                elif task.status not in {"READY", "IN_PRODUCTION"}:
                    source_status_display = task.get_status_display()
                elif verified_bom_count == 0:
                    source_status_display = "BOM待确认" if pending_bom_count else "未建立BOM"
                elif purchased_product_count:
                    source_status_display = "部分产品已建采购单"
                elif pending_bom_count or missing_bom_count or stale_bom_count or empty_bom_count:
                    source_status_display = "部分BOM待确认"
                else:
                    source_status_display = "可采购"
                task_rows.append({
                    **self._task_payload(task),
                    "product_count": task.purchase_product_count,
                    "remaining_product_count": task.purchase_product_count - purchased_product_count,
                    "can_create": not blockers,
                    "blockers": blockers,
                    "source_status_display": source_status_display,
                    "existing_purchase_order_id": None,
                    "existing_purchase_order_number": None,
                })

            procurement_sources = list(sample_procurement_sources(request))
            existing_sample_orders = {
                str(item["sample_procurement_request_id"]): item
                for item in PurchaseOrder.objects.filter(
                    sample_procurement_request_id__in=[item.pk for item in procurement_sources],
                    archived_at__isnull=True,
                ).values("sample_procurement_request_id", "id", "order_number")
            }
            sample_rows = []
            for procurement in procurement_sources:
                sample = procurement.material_request.sample_request
                existing = existing_sample_orders.get(str(procurement.pk))
                lines = procurement.lines if isinstance(procurement.lines, list) else []
                blockers = []
                if existing:
                    blockers.append({
                        "code": "PURCHASE_ORDER_EXISTS",
                        "message": "该打样单缺料已建立采购订单，请进入原采购单继续处理。",
                    })
                if not lines:
                    blockers.append({
                        "code": "SAMPLE_NO_SHORTAGE",
                        "message": "该打样单没有已确认的缺料采购需求。",
                    })
                sample_rows.append({
                    "id": str(procurement.pk),
                    "source_type": "SAMPLE",
                    "source_number": sample.request_number,
                    "customer_name": sample.customer_account.account_name,
                    "delivery_date": sample.sample_due_date,
                    "product_count": sample.items.count(),
                    "demand_count": len(lines),
                    "status": sample.status,
                    "status_display": "采购中" if existing else "待采购",
                    "can_create": not blockers,
                    "blockers": blockers,
                    "existing_purchase_order_id": str(existing["id"]) if existing else None,
                    "existing_purchase_order_number": existing["order_number"] if existing else "",
                })
            return Response({"data": {"production_tasks": task_rows, "sample_requests": sample_rows}})

        suppliers = list(Supplier.objects.filter(
            archived_at__isnull=True, is_disabled=False,
        ).order_by("supplier_number", "id").values(
            "id", "supplier_number", "supplier_name", "supplier_type", "supplier_categories",
        ))
        for supplier in suppliers:
            supplier["id"] = str(supplier["id"])
        if scope == "suppliers":
            return Response({"data": {"suppliers": suppliers}})
        if scope == "detail":
            currencies = Currency.objects.filter(
                archived_at__isnull=True,
                status=ReferenceStatus.ACTIVE,
            ).order_by("sort_order", "code")
            default_currency = self._default_currency()
            return Response({
                "data": {
                    "suppliers": suppliers,
                    "currencies": [
                        {
                            "id": str(item.pk),
                            "code": item.code,
                            "name": item.chinese_name,
                            "symbol": item.symbol,
                        }
                        for item in currencies
                    ],
                    "default_currency_id": str(default_currency.pk) if default_currency else None,
                }
            })
        task_rows = []
        tasks = production_tasks_with_purchase_sources(
            self._accessible_tasks().order_by("-updated_at", "-id")
        )
        for task in tasks:
            source = evaluate_purchase_source(task)
            task_rows.append(
                {
                    **self._task_payload(task),
                    "product_count": source["product_count"],
                    "remaining_product_count": source["remaining_product_count"],
                    "can_create": source["has_creatable_bom"],
                    "blockers": source["blockers"],
                    "existing_purchase_order_id": source["existing_purchase_order_id"],
                    "existing_purchase_order_number": source["existing_purchase_order_number"],
                }
            )

        currencies = Currency.objects.filter(
            archived_at__isnull=True,
            status=ReferenceStatus.ACTIVE,
        ).order_by("sort_order", "code")
        default_currency = self._default_currency()
        today = timezone.localdate()
        return Response(
            {
                "data": {
                    "statuses": [
                        {"value": value, "label": label}
                        for value, label in PurchaseOrderStatus.choices
                    ],
                    "created_date_presets": [
                        {"value": "", "label": "全部日期"},
                        {"value": (today - timedelta(days=30)).isoformat(), "label": "最近30天"},
                        {"value": (today - timedelta(days=90)).isoformat(), "label": "最近90天"},
                    ],
                    "production_tasks": task_rows,
                    "sample_requests": [sample_source(item)["sample_request"] for item in sample_procurement_sources(request).order_by("-created_at", "-id")],
                    "suppliers": suppliers,
                    "currencies": [
                        {
                            "id": str(item.pk),
                            "code": item.code,
                            "name": item.chinese_name,
                            "symbol": item.symbol,
                        }
                        for item in currencies
                    ],
                    "default_currency_id": str(default_currency.pk) if default_currency else None,
                }
            }
        )

    @action(detail=False, methods=["get"])
    def source(self, request):
        raw_sample_id = request.query_params.get("sample_procurement_request_id", "").strip()
        if raw_sample_id:
            if request.query_params.get("production_task_id") or request.query_params.get("bom_id"):
                raise ValidationError("不能同时指定生产订单和打样采购来源。")
            sample_id = self._uuid_value(raw_sample_id, "sample_procurement_request_id")
            procurement = sample_procurement_sources(request).filter(pk=sample_id).first()
            if procurement is None:
                raise NotFound("打样采购需求不存在、当前不可采购或不在账号数据范围内。")
            currency = self._default_currency()
            return Response({"data": {**sample_source(procurement), "default_currency_id": str(currency.pk) if currency else None}})
        raw_task_id = request.query_params.get("production_task_id", "").strip()
        if not raw_task_id:
            raise ValidationError({"production_task_id": "请选择生产订单。"})
        task_id = self._uuid_value(raw_task_id, "production_task_id")
        try:
            task = production_tasks_with_purchase_sources(
                self._accessible_tasks().filter(pk=task_id)
            ).get()
        except ProductionTask.DoesNotExist as exc:
            raise NotFound("生产订单不存在、已归档或不在当前账号的数据范围内。") from exc
        raw_bom_id = request.query_params.get("bom_id", "").strip()
        bom_id = self._uuid_value(raw_bom_id, "bom_id") if raw_bom_id else None
        source = public_purchase_source(task, bom_id=bom_id)
        default_currency = self._default_currency()
        return Response(
            {
                "data": {
                    "production_task": self._task_payload(task, include_products=True),
                    **source,
                    "default_currency_id": str(default_currency.pk) if default_currency else None,
                }
            }
        )


class PurchaseContractTemplateViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    # 所有具备采购查看权限的采购人员都可以共同维护模板；编辑时可覆盖当前版或另存新版本。
    action_permission_map = {
        "list": "procurement.view_purchaseorder",
        "retrieve": "procurement.view_purchaseorder",
        "create": "procurement.view_purchaseorder",
        "update": "procurement.view_purchaseorder",
        "partial_update": "procurement.view_purchaseorder",
    }

    def get_queryset(self):
        queryset = PurchaseContractTemplate.objects.filter(
            archived_at__isnull=True,
        ).select_related(
            "created_by_employee",
            "updated_by_employee",
        ).prefetch_related("versions__created_by_employee")
        status_value = self.request.query_params.get("status", "").strip().upper()
        if status_value:
            if status_value not in PurchaseContractTemplateStatus.values:
                raise ValidationError({"status": "模板状态参数不正确。"})
            queryset = queryset.filter(status=status_value)
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(template_name__icontains=keyword)
        return queryset.order_by("template_name", "id")

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return PurchaseContractTemplateInputSerializer
        return PurchaseContractTemplateSerializer

    @staticmethod
    def _response(instance, response_status=status.HTTP_200_OK):
        response = Response(
            {"data": PurchaseContractTemplateSerializer(instance).data},
            status=response_status,
        )
        response["ETag"] = etag_for_instance(instance)
        return response

    def retrieve(self, request, *args, **kwargs):
        return self._response(self.get_object())

    def create(self, request, *args, **kwargs):
        serializer = PurchaseContractTemplateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template = create_purchase_contract_template(
            validated_data=serializer.validated_data,
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        template = self.get_queryset().get(pk=template.pk)
        return self._response(template, status.HTTP_201_CREATED)

    def _update(self, request, *, partial):
        current = self.get_object()
        serializer = PurchaseContractTemplateInputSerializer(
            current,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        template = update_purchase_contract_template(
            template_id=current.pk,
            validated_data=serializer.validated_data,
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        return self._response(self.get_queryset().get(pk=template.pk))

    def update(self, request, *args, **kwargs):
        return self._update(request, partial=kwargs.pop("partial", False))

    def partial_update(self, request, *args, **kwargs):
        return self._update(request, partial=True)


class SupplierPurchaseSheetViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "list": "procurement.view_purchaseorder",
        "options": "procurement.view_purchaseorder",
        "retrieve": "procurement.view_purchaseorder",
        "partial_update": "procurement.add_purchaseorder",
        "update": "procurement.add_purchaseorder",
        "publish": "procurement.submit_purchaseorder",
        "download_xlsx": "procurement.view_purchaseorder",
        "preview.GET": "procurement.view_purchaseorder",
        "preview.POST": "procurement.add_purchaseorder",
        "new_version": "procurement.add_purchaseorder",
        "batch_download": "procurement.view_purchaseorder",
        "batch_publish": "procurement.submit_purchaseorder",
        "line_image.GET": "procurement.view_purchaseorder",
        "line_image.POST": "procurement.add_purchaseorder",
        "line_image.DELETE": "procurement.add_purchaseorder",
        "seal_image.GET": "procurement.view_purchaseorder",
        "seal_image.POST": "procurement.add_purchaseorder",
        "seal_image.DELETE": "procurement.add_purchaseorder",
    }

    def _accessible_task_ids(self):
        return accessible_production_tasks(self.request).filter(
            archived_at__isnull=True,
        ).order_by().values_list("id", flat=True)

    def get_queryset(self):
        task_ids = self._accessible_task_ids()
        queryset = SupplierPurchaseSheet.objects.filter(
            purchase_order_access(task_ids, self.request, "purchase_order__")
            | Q(purchase_request__production_task_id__in=task_ids),
            archived_at__isnull=True,
        ).select_related(
            "purchase_order",
            "purchase_order__production_task__sales_order",
            "purchase_request__production_task__sales_order",
            "supplier",
            "template_version__template",
            "pdf_file",
            "created_by_employee",
            "updated_by_employee",
            "published_by_employee",
            "seal_image__image_file",
        ).prefetch_related("line_images__image_file")
        default_current = "true" if self.action == "list" else ""
        current_value = self.request.query_params.get("is_current", default_current).strip().lower()
        if current_value not in {"", "true", "false", "1", "0"}:
            raise ValidationError({"is_current": "is_current 参数必须为 true 或 false。"})
        if current_value:
            queryset = queryset.filter(is_current=current_value in {"true", "1"})
        purchase_order_id = self.request.query_params.get("purchase_order_id", "").strip()
        if purchase_order_id:
            queryset = queryset.filter(purchase_order_id=PurchaseOrderViewSet._uuid_value(purchase_order_id, "purchase_order_id"))
        purchase_request_id = self.request.query_params.get("purchase_request_id", "").strip()
        if purchase_request_id:
            queryset = queryset.filter(
                purchase_request_id=PurchaseOrderViewSet._uuid_value(purchase_request_id, "purchase_request_id")
            )
        status_value = self.request.query_params.get("status", "").strip().upper()
        if status_value:
            if status_value not in SupplierPurchaseSheetStatus.values:
                raise ValidationError({"status": "采购表状态参数不正确。"})
            queryset = queryset.filter(status=status_value)
        supplier_id = self.request.query_params.get("supplier_id", "").strip()
        if supplier_id:
            queryset = queryset.filter(
                supplier_id=PurchaseOrderViewSet._uuid_value(supplier_id, "supplier_id")
            )
        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(sheet_number__icontains=keyword)
                | Q(supplier_number_snapshot__icontains=keyword)
                | Q(supplier_name_snapshot__icontains=keyword)
                | Q(purchase_order__sales_order_number_snapshot__icontains=keyword)
                | Q(purchase_request__request_number__icontains=keyword)
                | Q(purchase_request__production_task__task_number__icontains=keyword)
                | Q(purchase_request__production_task__sales_order__order_number__icontains=keyword)
            )
        return queryset.order_by(
            "-purchase_order__created_at",
            "purchase_order__order_number",
            "supplier_number_snapshot",
            "supplier_name_snapshot",
            "-version_number",
            "-id",
        )

    def get_serializer_class(self):
        if self.action in {"update", "partial_update"}:
            return SupplierPurchaseSheetUpdateSerializer
        return SupplierPurchaseSheetSerializer

    @staticmethod
    def _response(instance, response_status=status.HTTP_200_OK):
        response = Response(
            {"data": SupplierPurchaseSheetSerializer(instance).data},
            status=response_status,
        )
        response["ETag"] = etag_for_instance(instance)
        return response

    def retrieve(self, request, *args, **kwargs):
        return self._response(self.get_object())

    @action(detail=False, methods=["get"])
    def options(self, request):
        suppliers = list(
            self.get_queryset()
            .filter(is_current=True)
            .order_by()
            .values("supplier_id", "supplier_number_snapshot", "supplier_name_snapshot")
            .distinct()
            .order_by("supplier_number_snapshot", "supplier_name_snapshot")
        )
        return Response(
            {
                "data": {
                    "suppliers": [
                        {
                            "id": str(item["supplier_id"]),
                            "supplier_number": item["supplier_number_snapshot"],
                            "supplier_name": item["supplier_name_snapshot"],
                        }
                        for item in suppliers
                    ]
                }
            }
        )

    def _update(self, request, *, partial):
        current = self.get_object()
        serializer = SupplierPurchaseSheetUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        sheet = update_supplier_purchase_sheet(
            sheet_id=current.pk,
            content=serializer.validated_data["content"],
            allowed_task_ids=self._accessible_task_ids(),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        return self._response(self.get_queryset().get(pk=sheet.pk))

    def update(self, request, *args, **kwargs):
        return self._update(request, partial=kwargs.pop("partial", False))

    def partial_update(self, request, *args, **kwargs):
        return self._update(request, partial=True)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        sheet = publish_supplier_purchase_sheet(
            sheet_id=PurchaseOrderViewSet._uuid_value(pk, "id"),
            allowed_task_ids=self._accessible_task_ids(),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        return self._response(self.get_queryset().get(pk=sheet.pk))

    @extend_schema(request=SupplierPurchaseSheetUpdateSerializer, responses=OpenApiTypes.OBJECT)
    @action(detail=True, methods=["get", "post"])
    def preview(self, request, pk=None):
        sheet = self.get_object()
        if request.method == "POST":
            if sheet.status != SupplierPurchaseSheetStatus.DRAFT:
                raise ValidationError({"detail": "已发布合同只能预览正式内容。"})
            serializer = SupplierPurchaseSheetUpdateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            # 与保存共用校验；仅复制内存对象，预览不会写入业务数据库。
            normalized, _ = normalize_sheet_content(sheet, serializer.validated_data["content"])
            sheet = copy(sheet)
            sheet.content_snapshot = normalized
        try:
            return Response({"data": build_purchase_sheet_preview(sheet)})
        except FabricPurchaseSheetTemplateError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

    @action(detail=True, methods=["get"], url_path="download-xlsx")
    def download_xlsx(self, request, pk=None):
        sheet = self.get_object()
        try:
            content = build_supplier_purchase_sheet_xlsx(sheet)
        except FabricPurchaseSheetTemplateError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="{sheet.sheet_number}_V{sheet.version_number}.xlsx"'
        )
        return response

    @action(
        detail=True,
        methods=["get", "post", "delete"],
        url_path=r"line-images/(?P<line_id>[0-9a-fA-F-]+)",
        parser_classes=[MultiPartParser, FormParser],
    )
    def line_image(self, request, pk=None, line_id=None):
        source_line_id = PurchaseOrderViewSet._uuid_value(line_id, "line_id")
        if request.method == "GET":
            sheet = self.get_object()
            image = sheet.line_images.select_related("image_file").filter(
                source_purchase_order_line_id=source_line_id,
            ).first()
            if image is None:
                raise NotFound("该采购明细没有图片。")
            if image.image_file.scan_status not in USABLE_FILE_SCAN_STATUSES:
                raise NotFound("采购表图片尚未通过安全扫描。")
            media_root = Path(settings.MEDIA_ROOT).resolve()
            file_path = (media_root / image.image_file.storage_key).resolve()
            if media_root not in file_path.parents or not file_path.is_file():
                raise NotFound("采购表图片文件不存在。")
            return FileResponse(
                file_path.open("rb"),
                content_type=image.image_file.content_type,
                filename=image.image_file.original_name,
            )
        if request.method == "POST":
            uploaded_file = request.FILES.get("file")
            if uploaded_file is None:
                raise ValidationError({"file": "请选择需要上传的采购表图片。"})
            sheet = replace_supplier_purchase_sheet_line_image(
                sheet_id=PurchaseOrderViewSet._uuid_value(pk, "id"),
                source_line_id=source_line_id,
                uploaded_file=uploaded_file,
                allowed_task_ids=self._accessible_task_ids(),
                actor_employee=getattr(request, "employee", None),
                request=request,
            )
            return self._response(self.get_queryset().get(pk=sheet.pk))
        sheet = remove_supplier_purchase_sheet_line_image(
            sheet_id=PurchaseOrderViewSet._uuid_value(pk, "id"),
            source_line_id=source_line_id,
            allowed_task_ids=self._accessible_task_ids(),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        return self._response(self.get_queryset().get(pk=sheet.pk))

    @action(
        detail=True,
        methods=["get", "post", "delete"],
        url_path="seal-image",
        parser_classes=[MultiPartParser, FormParser],
    )
    def seal_image(self, request, pk=None):
        if request.method == "GET":
            sheet = self.get_object()
            seal = getattr(sheet, "seal_image", None)
            if seal is None:
                raise NotFound("当前采购表没有盖章图片。")
            if seal.image_file.scan_status not in USABLE_FILE_SCAN_STATUSES:
                raise NotFound("采购表盖章图片尚未通过安全扫描。")
            media_root = Path(settings.MEDIA_ROOT).resolve()
            file_path = (media_root / seal.image_file.storage_key).resolve()
            if media_root not in file_path.parents or not file_path.is_file():
                raise NotFound("采购表盖章图片文件不存在。")
            return FileResponse(
                file_path.open("rb"),
                content_type=seal.image_file.content_type,
                filename=seal.image_file.original_name,
            )
        if request.method == "POST":
            uploaded_file = request.FILES.get("file")
            if uploaded_file is None:
                raise ValidationError({"file": "请选择需要上传的盖章图片。"})
            sheet = replace_supplier_purchase_sheet_seal_image(
                sheet_id=PurchaseOrderViewSet._uuid_value(pk, "id"),
                uploaded_file=uploaded_file,
                allowed_task_ids=self._accessible_task_ids(),
                actor_employee=getattr(request, "employee", None),
                request=request,
            )
            return self._response(self.get_queryset().get(pk=sheet.pk))
        sheet = remove_supplier_purchase_sheet_seal_image(
            sheet_id=PurchaseOrderViewSet._uuid_value(pk, "id"),
            allowed_task_ids=self._accessible_task_ids(),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        return self._response(self.get_queryset().get(pk=sheet.pk))

    @action(detail=True, methods=["post"], url_path="new-version")
    def new_version(self, request, pk=None):
        sheet = create_supplier_purchase_sheet_version(
            sheet_id=PurchaseOrderViewSet._uuid_value(pk, "id"),
            allowed_task_ids=self._accessible_task_ids(),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        return self._response(self.get_queryset().get(pk=sheet.pk), status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="batch-download")
    def batch_download(self, request):
        raw_ids = request.data.get("ids")
        if not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > 100:
            raise ValidationError({"ids": "请选择 1 至 100 张已发布采购表。"})
        ids = [PurchaseOrderViewSet._uuid_value(value, "ids") for value in raw_ids]
        if len(ids) != len(set(ids)):
            raise ValidationError({"ids": "采购表不能重复选择。"})
        sheets = list(self.get_queryset().filter(
            pk__in=ids,
            status=SupplierPurchaseSheetStatus.PUBLISHED,
        ))
        if len(sheets) != len(ids):
            raise ValidationError({"ids": "选择中包含不存在、无权限或尚未发布的采购表。"})
        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            for sheet in sheets:
                try:
                    content = build_supplier_purchase_sheet_xlsx(sheet)
                except FabricPurchaseSheetTemplateError as exc:
                    raise ValidationError({"ids": f"{sheet.sheet_number} 无法导出：{exc}"}) from exc
                archive.writestr(f"{sheet.sheet_number}_V{sheet.version_number}.xlsx", content)
        response = HttpResponse(output.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="supplier_purchase_sheets.zip"'
        return response

    @action(detail=False, methods=["post"], url_path="batch-publish")
    def batch_publish(self, request):
        raw_ids = request.data.get("ids")
        if not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > 100:
            raise ValidationError({"ids": "请选择 1 至 100 张草稿采购表。"})
        ids = [PurchaseOrderViewSet._uuid_value(value, "ids") for value in raw_ids]
        if len(ids) != len(set(ids)):
            raise ValidationError({"ids": "采购表不能重复选择。"})
        sheets = publish_supplier_purchase_sheets(
            sheet_ids=ids,
            allowed_task_ids=self._accessible_task_ids(),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        refreshed = {
            item.pk: item
            for item in self.get_queryset().filter(pk__in=[sheet.pk for sheet in sheets])
        }
        ordered = [refreshed[sheet.pk] for sheet in sheets]
        return Response({"data": SupplierPurchaseSheetSerializer(ordered, many=True).data})
