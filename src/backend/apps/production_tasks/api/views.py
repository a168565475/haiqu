import csv
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.db.models import Count, DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.customers.selectors import accessible_customers
from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
from apps.organizations.selectors import active_department_employees, employee_filter_choices
from apps.organizations.models import Employee, EmployeeStatus
from apps.products.models import ProductInformation, ProductStatus
from apps.reference_data.models import Currency, ProductCategory, ProductColor, ProductItemType, ProductionUnit, ReferenceStatus
from apps.sales_orders.selectors import sales_orders_with_context
from apps.samples.sampling_detail_config import load_sampling_detail_template

from ..models import (
    DeliveryMethod,
    OrderSource,
    ProductionDeliveryBatch,
    ProductionTaskProduct,
    ProductionTaskFollower,
    ProductionTaskStatus,
)
from ..selectors import accessible_production_tasks, production_sales_order_sources, production_tasks_with_context
from ..services import (
    close_production_task,
    complete_production_order,
    create_production_order_from_sales_order,
    create_production_task,
    decide_production_order_by_pmc,
    delete_production_task,
    reserve_contract_number,
    start_production_order,
    submit_production_task,
    transition_production_task,
    update_production_task,
)
from .serializers import (
    ProductionTaskCompleteSerializer,
    ProductionTaskCreateFromSalesOrderSerializer,
    ProductionTaskListSerializer,
    ProductionTaskPatchSerializer,
    ProductionTaskReadSerializer,
    ProductionTaskReasonSerializer,
    ProductionTaskPmcDecisionSerializer,
    ProductionTaskStartSerializer,
    ProductionTaskWriteSerializer,
    ProductionSalesSourceSerializer,
    ProductionSalesSourceSummarySerializer,
)


class ProductionTaskViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "task_number", "contract_number", "order_number", "customer_account__account_code",
        "customer_account__account_name", "products__product_name_snapshot", "products__item_number_snapshot",
    ]
    ordering_fields = ["created_at", "updated_at", "delivery_date", "task_number"]
    ordering = ["-created_at", "-id"]
    action_permission_map = {
        "list": "production_tasks.view_productiontask",
        "retrieve": "production_tasks.view_productiontask",
        "business_file": "production_tasks.view_productiontask",
        "create": "production_tasks.add_productiontask",
        "create_from_sales_order": "production_tasks.add_productiontask",
        "sales_order_sources": "production_tasks.add_productiontask",
        "sales_order_source_image": "production_tasks.add_productiontask",
        "reserve_contract_number": "production_tasks.add_productiontask",
        "partial_update": "production_tasks.change_productiontask",
        "destroy": "production_tasks.delete_productiontask",
        "options": "production_tasks.view_productiontask",
        "stats": "production_tasks.view_productiontask",
        "export": "production_tasks.view_productiontask",
        "submit": "production_tasks.submit_productiontask",
        "confirm": "production_tasks.confirm_productiontask",
        "pmc_decision": "production_tasks.confirm_productiontask",
        "start": "production_tasks.start_productiontask",
        "cancel": "production_tasks.change_productiontask",
        "finish": "production_tasks.change_productiontask",
    }

    def _filtered_queryset(self, *, include_status=True):
        queryset = accessible_production_tasks(self.request).filter(archived_at__isnull=True)
        requested_status = self.request.query_params.get("status", "").strip().upper()
        if requested_status:
            if requested_status not in ProductionTaskStatus.values:
                raise ValidationError({"status": "任务单状态参数不正确。"})
            if include_status:
                queryset = queryset.filter(status=requested_status)
        source = self.request.query_params.get("order_source", "").strip().upper()
        if source:
            if source not in OrderSource.values:
                raise ValidationError({"order_source": "订单来源参数不正确。"})
            queryset = queryset.filter(order_source=source)
        delivery = self.request.query_params.get("delivery_method", "").strip().upper()
        if delivery:
            if delivery not in DeliveryMethod.values:
                raise ValidationError({"delivery_method": "交货方式参数不正确。"})
            queryset = queryset.filter(delivery_method=delivery)

        contract_number = self.request.query_params.get("contract_number", "").strip()
        if contract_number:
            queryset = queryset.filter(contract_number__icontains=contract_number)

        uuid_filters = {
            "customer_id": "customer_account_id",
            "product_id": "products__product_id",
            "salesperson_id": "salesperson_id",
            "follower_id": "followers__id",
        }
        for query_name, model_field in uuid_filters.items():
            raw_value = self.request.query_params.get(query_name, "").strip()
            if not raw_value:
                continue
            try:
                UUID(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValidationError({query_name: f"{query_name} 参数不正确。"}) from exc
            queryset = queryset.filter(**{model_field: raw_value})

        delivery_from = self._date_param("delivery_from")
        delivery_to = self._date_param("delivery_to")
        if delivery_from and delivery_to and delivery_from > delivery_to:
            raise ValidationError({"delivery_to": "交期结束日期不能早于开始日期。"})
        if delivery_from:
            queryset = queryset.filter(delivery_date__gte=delivery_from)
        if delivery_to:
            queryset = queryset.filter(delivery_date__lte=delivery_to)

        due_within_days = self.request.query_params.get("due_within_days", "").strip()
        if due_within_days:
            try:
                days = int(due_within_days)
            except ValueError as exc:
                raise ValidationError({"due_within_days": "近期待交天数必须是整数。"}) from exc
            if not 1 <= days <= 365:
                raise ValidationError({"due_within_days": "近期待交天数必须在 1 到 365 之间。"})
            today = timezone.localdate()
            queryset = queryset.filter(delivery_date__range=(today, today + timedelta(days=days)))

        quantity_pending = self.request.query_params.get("quantity_pending", "").strip().lower()
        if quantity_pending:
            if quantity_pending not in {"1", "true"}:
                raise ValidationError({"quantity_pending": "数量待确认参数不正确。"})
            decimal_field = DecimalField(max_digits=22, decimal_places=4)
            product_total = ProductionTaskProduct.objects.filter(
                production_task_id=OuterRef("pk")
            ).values("production_task_id").annotate(total=Sum("quantity")).values("total")[:1]
            batch_total = ProductionDeliveryBatch.objects.filter(
                production_task_id=OuterRef("pk")
            ).values("production_task_id").annotate(total=Sum("quantity")).values("total")[:1]
            queryset = queryset.annotate(
                _product_quantity=Coalesce(Subquery(product_total, output_field=decimal_field), Value(0), output_field=decimal_field),
                _batch_quantity=Coalesce(Subquery(batch_total, output_field=decimal_field), Value(0), output_field=decimal_field),
            ).filter(delivery_batches__isnull=False).exclude(_product_quantity=F("_batch_quantity"))
        search_text = self.request.query_params.get("search", "").strip()
        if len(search_text) > 200:
            raise ValidationError({"search": "搜索内容不能超过 200 个字符。"})
        if search_text:
            queryset = queryset.filter(
                Q(task_number__icontains=search_text)
                | Q(contract_number__icontains=search_text)
                | Q(order_number__icontains=search_text)
                | Q(customer_account__account_code__icontains=search_text)
                | Q(customer_account__account_name__icontains=search_text)
                | Q(products__product_name_snapshot__icontains=search_text)
                | Q(products__item_number_snapshot__icontains=search_text)
            )
        return queryset.distinct()

    def get_queryset(self):
        return production_tasks_with_context(
            self._filtered_queryset(),
            include_progress=self.action in {"list", "retrieve"},
            list_mode=self.action == "list",
        )

    def _date_param(self, name):
        raw_value = self.request.query_params.get(name, "").strip()
        if not raw_value:
            return None
        parsed = parse_date(raw_value)
        if parsed is None:
            raise ValidationError({name: f"{name} 日期格式不正确。"})
        return parsed

    def get_serializer_class(self):
        if self.action == "list":
            return ProductionTaskListSerializer
        if self.action in {"create", "partial_update"}:
            return ProductionTaskWriteSerializer
        return ProductionTaskReadSerializer

    def _payload(self):
        if self.request.content_type and self.request.content_type.startswith("multipart/form-data"):
            raw = self.request.data.get("payload")
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError as exc:
                raise ValidationError({"payload": "payload 不是合法 JSON。"}) from exc
            if not isinstance(payload, dict):
                raise ValidationError({"payload": "multipart 请求必须包含 JSON 对象 payload。"})
            return payload
        return self.request.data

    def _customer_references(self):
        from apps.access_control import module_policy
        from apps.customers.models import CustomerAccount
        if module_policy.enabled() and module_policy.has_module_grant(self.request, 'production_tasks'):
            return CustomerAccount.objects.filter(archived_at__isnull=True)
        return accessible_customers(self.request)

    def _serializer_context(self):
        context = self.get_serializer_context()
        context["accessible_customer_ids"] = set(self._customer_references().values_list("id", flat=True))
        return context

    def _validate_file_fields(self, payload):
        expected = set()
        for product in payload.get("products", []):
            product_key = product.get("client_key")
            if product_key:
                expected.add(f"product_image_{product_key}")
            for detail in product.get("details", []):
                detail_key = detail.get("client_key")
                if detail_key:
                    expected.add(f"detail_image_{detail_key}")
        unexpected = set(self.request.FILES) - expected
        if unexpected:
            raise ValidationError({"files": f"存在未匹配表单的文件字段：{', '.join(sorted(unexpected))}。"})

    def create(self, request, *args, **kwargs):
        payload = self._payload()
        self._validate_file_fields(payload)
        serializer_context = self._serializer_context()
        serializer_context["require_contract_number_token"] = True
        serializer = ProductionTaskWriteSerializer(data=payload, context=serializer_context)
        serializer.is_valid(raise_exception=True)
        task = create_production_task(
            validated_data=serializer.validated_data,
            files=request.FILES,
            actor_employee=request.employee,
            request=request,
        )
        task = production_tasks_with_context().get(pk=task.pk)
        response = Response({"data": ProductionTaskReadSerializer(task).data}, status=status.HTTP_201_CREATED)
        response["ETag"] = etag_for_instance(task)
        return response

    @action(detail=False, methods=["post"], url_path="create-from-sales-order")
    def create_from_sales_order(self, request):
        context = self.get_serializer_context()
        sources = production_sales_order_sources(request)
        context['accessible_sales_order_ids'] = set(sources.values_list('id', flat=True))
        serializer = ProductionTaskCreateFromSalesOrderSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        task = create_production_order_from_sales_order(
            validated_data=serializer.validated_data,
            actor_employee=request.employee,
            request=request,
        )
        task = production_tasks_with_context().get(pk=task.pk)
        response = Response({"data": ProductionTaskReadSerializer(task).data}, status=status.HTTP_201_CREATED)
        response["ETag"] = etag_for_instance(task)
        return response

    @extend_schema(
        parameters=[OpenApiParameter("q", str), OpenApiParameter("sales_order_id", OpenApiTypes.UUID)],
        responses={200: OpenApiTypes.OBJECT},
        description="生产建单来源白名单。默认 data 为最多 100 条可继续分配的订单摘要；传 sales_order_id 时 data 为单个订单的生产必要字段，不包含客户资料。",
    )
    @action(detail=False, methods=["get"], url_path="sales-order-sources")
    def sales_order_sources(self, request):
        queryset = sales_orders_with_context(production_sales_order_sources(request))
        order_id = request.query_params.get("sales_order_id")
        if order_id:
            try:
                order_id = UUID(order_id)
            except (TypeError, ValueError) as exc:
                raise ValidationError({"sales_order_id": "销售订单编号格式不正确。"}) from exc
            order = get_object_or_404(queryset, pk=order_id)
            return Response({"data": ProductionSalesSourceSerializer(order).data})
        search = request.query_params.get("q", "").strip()
        if search:
            queryset = queryset.filter(order_number__icontains=search)
        result = []
        serializer = ProductionSalesSourceSummarySerializer()
        for order in queryset.order_by("-order_date", "-created_at", "-id").iterator(chunk_size=100):
            if serializer.get_has_remaining_production_capacity(order):
                result.append(ProductionSalesSourceSummarySerializer(order).data)
                if len(result) >= 100:
                    break
        return Response({"data": result})

    @extend_schema(
        parameters=[OpenApiParameter("sales_order_id", OpenApiTypes.UUID, required=True), OpenApiParameter("line_id", OpenApiTypes.UUID, required=True)],
        responses={200: OpenApiTypes.BINARY},
    )
    @action(detail=False, methods=["get"], url_path="sales-order-source-image")
    def sales_order_source_image(self, request):
        try:
            order_id = UUID(request.query_params.get("sales_order_id", ""))
            line_id = UUID(request.query_params.get("line_id", ""))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"line_id": "销售订单或产品明细编号格式不正确。"}) from exc
        order = get_object_or_404(production_sales_order_sources(request), pk=order_id)
        line = get_object_or_404(order.lines.select_related("product_image"), pk=line_id)
        image = line.product_image
        if image is None or image.archived_at is not None:
            raise Http404("产品图片不存在。")
        if image.scan_status not in USABLE_FILE_SCAN_STATUSES:
            raise ValidationError({"image": "产品图片尚未通过安全扫描。"})
        media_root = Path(settings.MEDIA_ROOT).resolve()
        storage_path = (media_root / image.storage_key).resolve()
        try:
            storage_path.relative_to(media_root)
        except ValueError as exc:
            raise Http404("图片路径无效。") from exc
        if not storage_path.is_file():
            raise Http404("图片文件不存在。")
        return FileResponse(storage_path.open("rb"), content_type=image.content_type)

    @action(detail=False, methods=["post"], url_path="reserve-contract-number")
    def reserve_contract_number(self, request):
        order_date = request.data.get("order_date")
        date_field = ProductionTaskWriteSerializer().fields["order_date"]
        try:
            parsed_date = date_field.run_validation(order_date)
        except ValidationError as exc:
            raise ValidationError({"order_date": "下单日期格式不正确。"}) from exc
        contract_number, token = reserve_contract_number(
            order_date=parsed_date,
            actor_employee=request.employee,
        )
        return Response({"data": {"contract_number": contract_number, "token": token}})

    def retrieve(self, request, *args, **kwargs):
        task = self.get_object()
        response = Response({"data": ProductionTaskReadSerializer(task).data})
        response["ETag"] = etag_for_instance(task)
        return response

    @action(
        detail=True,
        methods=["get"],
        url_path=r"business-files/(?P<file_id>[^/.]+)",
    )
    def business_file(self, request, pk=None, file_id=None):
        task = self.get_object()
        business_file = get_object_or_404(
            BusinessFile.objects.filter(
                Q(production_task_product_images__product_line__production_task=task)
                | Q(production_task_products__production_task=task)
                | Q(production_task_details__product_line__production_task=task),
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
        return FileResponse(
            storage_path.open("rb"),
            content_type=business_file.content_type,
            as_attachment=request.query_params.get("download") == "1",
            filename=business_file.original_name,
        )

    @extend_schema(responses={204: None}, description="物理删除已取消、无下游且未实际生产的任务；必须提供 If-Match。")
    def destroy(self, request, *args, **kwargs):
        task = self.get_object()
        require_matching_etag(request, task)
        delete_production_task(task=task, actor_employee=request.employee, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def partial_update(self, request, *args, **kwargs):
        current = self.get_object()
        require_matching_etag(request, current)
        payload = self._payload()
        self._validate_file_fields(payload)
        serializer_context = self._serializer_context()
        serializer_context["current_task_id"] = current.pk
        serializer_context["current_task"] = current
        serializer = ProductionTaskPatchSerializer(
            data=payload,
            context=serializer_context,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        task = update_production_task(
            task=current,
            validated_data=serializer.validated_data,
            files=request.FILES,
            actor_employee=request.employee,
            request=request,
        )
        task = production_tasks_with_context().get(pk=task.pk)
        response = Response({"data": ProductionTaskReadSerializer(task).data})
        response["ETag"] = etag_for_instance(task)
        return response

    @extend_schema(parameters=[OpenApiParameter("scope", str, enum=["full", "filters"], description="默认返回完整编辑选项；filters 仅返回列表筛选选项。")])
    @action(detail=False, methods=["get"])
    def options(self, request):
        scope = request.query_params.get("scope", "full")
        if scope not in {"full", "filters"}:
            raise ValidationError({"scope": "选项范围必须是 full 或 filters。"})
        customers = self._customer_references().filter(archived_at__isnull=True).order_by("account_name", "account_code")[:500]
        employees = active_department_employees("DEPT_PRODUCTION").order_by("employee_code")
        salespeople = active_department_employees("DEPT_BUSINESS").order_by("employee_code")
        if scope == "filters":
            visible = self.get_queryset()
            employees = employee_filter_choices(employees, visible.values("followers__pk"))
            salespeople = employee_filter_choices(salespeople, visible.values("salesperson_id"))
        products = ProductInformation.objects.filter(status=ProductStatus.ACTIVE, archived_at__isnull=True).select_related(
            "unit", "product_item"
        ).filter(category__item_type=ProductItemType.FINISHED, category__status=ReferenceStatus.ACTIVE,
                 category__archived_at__isnull=True).order_by("product_number")[:1000]
        currencies = Currency.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True).order_by("sort_order", "code")
        units = ProductionUnit.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True).order_by("sort_order", "unit_code")
        colors = ProductColor.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True).order_by("sort_order", "color_card", "color_code")
        data = {
            "order_sources": [{"value": value, "label": label} for value, label in OrderSource.choices],
            "delivery_methods": [{"value": value, "label": label} for value, label in DeliveryMethod.choices],
            "statuses": [{"value": value, "label": label} for value, label in ProductionTaskStatus.choices],
            "customers": [{"id": str(item.pk), "account_code": item.account_code, "account_name": item.account_name} for item in customers],
            "employees": [{"id": str(item.pk), "employee_code": item.employee_code, "display_name": item.display_name} for item in employees],
            "salespeople": [{"id": str(item.pk), "employee_code": item.employee_code, "display_name": item.display_name} for item in salespeople],
            "products": [{
                "id": str(item.pk), "product_number": item.product_number, "product_code": item.product_code,
                "item_number": item.product_item.item_number, "product_name": item.product_name,
                "specification": item.specification, "default_unit_id": str(item.unit_id),
                "category_id": str(item.category_id), "unit_code": item.unit.unit_code, "unit_name": item.unit.unit_name,
            } for item in products],
        }
        if scope == "filters":
            return Response({"data": data})
        data.update({
            "categories": [{"id": str(item.pk), "category_name": item.category_name} for item in
                ProductCategory.objects.filter(item_type=ProductItemType.FINISHED, status=ReferenceStatus.ACTIVE,
                    archived_at__isnull=True).order_by("sort_order", "category_name", "id")],
            "recent_task_numbers": sorted(
                accessible_production_tasks(request).filter(archived_at__isnull=True)
                .order_by("-created_at", "-id").values_list("task_number", flat=True)[:5]
            ),
            "boolean_options": [{"value": True, "label": "是"}, {"value": False, "label": "否"}],
            "currencies": [{"id": str(item.pk), "code": item.code, "name": item.chinese_name, "symbol": item.symbol} for item in currencies],
            "units": [{"id": str(item.pk), "unit_code": item.unit_code, "unit_name": item.unit_name} for item in units],
            "colors": [{"id": str(item.pk), "color_card": item.color_card, "color_code": item.color_code, "color_name": item.color_name} for item in colors],
            "detail_template": list(load_sampling_detail_template()),
        })
        return Response({"data": data})

    @action(detail=False, methods=["get"])
    def stats(self, request):
        queryset = self._filtered_queryset(include_status=False)
        # 筛选或权限关联可能产生重复行，所有计数仍按任务主键去重。
        totals = queryset.aggregate(
            all=Count("pk", distinct=True),
            draft=Count("pk", filter=Q(status=ProductionTaskStatus.DRAFT), distinct=True),
            pending_validation=Count("pk", filter=Q(status=ProductionTaskStatus.PENDING_VALIDATION), distinct=True),
            ready=Count("pk", filter=Q(status=ProductionTaskStatus.READY), distinct=True),
            in_production=Count("pk", filter=Q(status=ProductionTaskStatus.IN_PRODUCTION), distinct=True),
            completed=Count("pk", filter=Q(status=ProductionTaskStatus.COMPLETED), distinct=True),
            paused=Count("pk", filter=Q(status=ProductionTaskStatus.PAUSED), distinct=True),
            cancelled=Count("pk", filter=Q(status=ProductionTaskStatus.CANCELLED), distinct=True),
            split_delivery=Count("pk", filter=Q(delivery_method=DeliveryMethod.SPLIT), distinct=True),
        )
        return Response({"data": totals})

    @staticmethod
    def _csv_cell(value):
        text = str(value or "")
        if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")):
            return f"'{text}"
        return text

    def _export_queryset(self):
        queryset = self._filtered_queryset()
        raw_ids = self.request.data.get("ids", []) if self.request.method == "POST" else []
        if raw_ids:
            if not isinstance(raw_ids, list):
                raise ValidationError({"ids": "勾选记录编号必须是数组。"})
            values = [str(value).strip() for value in raw_ids if str(value).strip()]
            if len(values) > 500:
                raise ValidationError({"ids": "单次最多导出 500 条勾选记录。"})
            try:
                identifiers = [UUID(value) for value in values]
            except (TypeError, ValueError) as exc:
                raise ValidationError({"ids": "勾选记录编号参数不正确。"}) from exc
            queryset = queryset.filter(pk__in=identifiers)
        if queryset.count() > 10000:
            raise ValidationError({"export": "当前筛选超过 10000 条，请缩小筛选范围后导出。"})
        return queryset.order_by(*self.ordering)

    @action(detail=False, methods=["get", "post"])
    def export(self, request):
        rows = list(self._export_queryset().values(
            "id",
            "task_number",
            "order_number",
            "sales_order__order_number",
            "delivery_date",
            "order_date",
            "salesperson__display_name",
            "status",
        ))
        task_ids = [row["id"] for row in rows]
        product_names = {}
        total_quantities = {}
        follower_names = {}
        for link in ProductionTaskFollower.objects.filter(production_task_id__in=task_ids).order_by(
            "production_task_id", "employee__employee_code"
        ).values("production_task_id", "employee__display_name"):
            follower_names.setdefault(link["production_task_id"], []).append(link["employee__display_name"])
        for product in ProductionTaskProduct.objects.filter(production_task_id__in=task_ids).order_by(
            "production_task_id", "line_number", "id"
        ).values("production_task_id", "product_name_snapshot", "quantity"):
            task_id = product["production_task_id"]
            product_names.setdefault(task_id, []).append(product["product_name_snapshot"])
            total_quantities[task_id] = total_quantities.get(task_id, 0) + product["quantity"]
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(["生产任务编号", "销售订单", "产品", "数量", "下单日期", "交期", "业务员", "跟单员", "状态"])
        for row in rows:
            product_text = "；".join(filter(None, product_names.get(row["id"], [])))
            writer.writerow([
                self._csv_cell(row["task_number"]),
                self._csv_cell(row["sales_order__order_number"] or ""),
                self._csv_cell(product_text),
                total_quantities.get(row["id"], 0),
                row["order_date"],
                row["delivery_date"],
                self._csv_cell(row["salesperson__display_name"]),
                self._csv_cell("；".join(follower_names.get(row["id"], []))),
                self._csv_cell(ProductionTaskStatus(row["status"]).label),
            ])
        response["Content-Disposition"] = 'attachment; filename="production_tasks.csv"'
        response["X-Export-Count"] = str(len(rows))
        return response

    @action(detail=True, methods=["post"])
    def submit(self, request, *args, **kwargs):
        current = self.get_object()
        require_matching_etag(request, current)
        task = submit_production_task(task=current, actor_employee=request.employee, request=request)
        task = production_tasks_with_context().get(pk=task.pk)
        response = Response({"data": ProductionTaskReadSerializer(task).data})
        response["ETag"] = etag_for_instance(task)
        return response

    def _transition(self, request, target_status):
        current = self.get_object()
        require_matching_etag(request, current)
        task = transition_production_task(
            task=current, target_status=target_status, actor_employee=request.employee, request=request,
        )
        task = production_tasks_with_context().get(pk=task.pk)
        response = Response({"data": ProductionTaskReadSerializer(task).data})
        response["ETag"] = etag_for_instance(task)
        return response

    @action(detail=True, methods=["post"])
    def confirm(self, request, *args, **kwargs):
        current = self.get_object()
        payload = dict(request.data)
        payload["decision"] = "CONFIRM"
        serializer = ProductionTaskPmcDecisionSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        task = decide_production_order_by_pmc(
            task=current,
            validated_data=serializer.validated_data,
            actor_employee=request.employee,
            request=request,
        )
        task = production_tasks_with_context().get(pk=task.pk)
        response = Response({"data": ProductionTaskReadSerializer(task).data})
        response["ETag"] = etag_for_instance(task)
        return response

    @action(detail=True, methods=["post"], url_path="pmc-decision")
    def pmc_decision(self, request, *args, **kwargs):
        serializer = ProductionTaskPmcDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = decide_production_order_by_pmc(
            task=self.get_object(),
            validated_data=serializer.validated_data,
            actor_employee=request.employee,
            request=request,
        )
        task = production_tasks_with_context().get(pk=task.pk)
        response = Response({"data": ProductionTaskReadSerializer(task).data})
        response["ETag"] = etag_for_instance(task)
        return response

    @action(detail=True, methods=["post"])
    def start(self, request, *args, **kwargs):
        current = self.get_object()
        if current.sales_order_id:
            serializer = ProductionTaskStartSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            task = start_production_order(
                task=current,
                waiver_reason=serializer.validated_data.get("start_waiver_reason", ""),
                actor_employee=request.employee,
                request=request,
            )
            task = production_tasks_with_context().get(pk=task.pk)
            response = Response({"data": ProductionTaskReadSerializer(task).data})
            response["ETag"] = etag_for_instance(task)
            return response
        return self._transition(request, ProductionTaskStatus.IN_PRODUCTION)

    def _close(self, request, target_status):
        current = self.get_object()
        require_matching_etag(request, current)
        serializer = ProductionTaskReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = close_production_task(
            task=current,
            target_status=target_status,
            reason=serializer.validated_data["reason"],
            actor_employee=request.employee,
            request=request,
        )
        task = production_tasks_with_context().get(pk=task.pk)
        response = Response({"data": ProductionTaskReadSerializer(task).data})
        response["ETag"] = etag_for_instance(task)
        return response

    @action(detail=True, methods=["post"])
    def cancel(self, request, *args, **kwargs):
        return self._close(request, ProductionTaskStatus.CANCELLED)

    @action(detail=True, methods=["post"])
    def finish(self, request, *args, **kwargs):
        current = self.get_object()
        if current.sales_order_id:
            serializer = ProductionTaskCompleteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            task = complete_production_order(
                task=current,
                validated_data=serializer.validated_data,
                actor_employee=request.employee,
                request=request,
            )
            task = production_tasks_with_context().get(pk=task.pk)
            response = Response({"data": ProductionTaskReadSerializer(task).data})
            response["ETag"] = etag_for_instance(task)
            return response
        return self._close(request, ProductionTaskStatus.COMPLETED)
