from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from django.conf import settings
from django.db.models import Exists, OuterRef, Q, Subquery
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.customers.selectors import accessible_customers
from apps.boms.models import Bom, BomStatus
from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
from apps.procurement.models import PurchaseOrderStatus
from apps.production_tasks.models import ProductionTaskProduct, ProductionTaskStatus
from apps.production_tasks.selectors import accessible_production_tasks, production_tasks_with_context
from apps.sales_orders.presentation import specification_display
from apps.workshop_config.models import Craft, PlanCategory, RecordStatus

from ..models import ProductionSchedule, ScheduleStatus
from ..selectors import (
    accessible_production_schedules, schedule_items_for_category, schedule_product_image, schedule_source_image_ids,
    schedules_with_context,
)
from ..services import create_schedule, create_schedule_batch, source_revision, update_schedule, void_schedule
from .serializers import (
    ScheduleBatchCreateSerializer, ScheduleCreateSerializer, ScheduleItemReadSerializer, ScheduleReadSerializer,
    ScheduleUpdateSerializer, ScheduleVoidSerializer,
)


def _uuid(value, field):
    if not value:
        return None
    try:
        return UUID(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field: f"{field} 参数不是有效 UUID。"}) from exc


def _date(value, field):
    if not value:
        return None
    try:
        parsed = parse_date(value)
    except ValueError as exc:
        raise ValidationError({field: f"{field} 日期格式不正确。"}) from exc
    if parsed is None:
        raise ValidationError({field: f"{field} 日期格式不正确。"})
    return parsed


def _task_product_display_fields(line):
    image = schedule_product_image(line)
    return {
        "specification_display": specification_display(SimpleNamespace(
            specification_snapshot=line.specification_snapshot,
            customer_specification_snapshot=line.customer_specification_snapshot,
            customer_color_snapshot=line.customer_color_snapshot,
            color_snapshot=line.color_name_snapshot,
            material_snapshot=line.material_snapshot,
        )),
        "material": line.material_snapshot,
        "image_file_id": str(image.pk) if image else None,
    }


class ProductionScheduleViewSet(viewsets.GenericViewSet):
    serializer_class = ScheduleReadSerializer
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {
        "list": "production_scheduling.view_productionschedule",
        "retrieve": "production_scheduling.view_productionschedule",
        "task_candidates": "production_scheduling.view_productionschedule",
        "task_candidate_detail": "production_scheduling.view_productionschedule",
        "task_file": "production_scheduling.view_productionschedule",
        "options": "production_scheduling.view_productionschedule",
        "create": "production_scheduling.add_productionschedule",
        "batch_create": "production_scheduling.add_productionschedule",
        "partial_update": "production_scheduling.change_productionschedule",
        "void": "production_scheduling.void_productionschedule",
    }

    def get_queryset(self):
        return schedules_with_context(accessible_production_schedules(self.request))

    def _filtered(self):
        queryset = self.get_queryset()
        status_value = self.request.query_params.get("record_status", "").strip().upper()
        if status_value:
            if status_value not in ScheduleStatus.values:
                raise ValidationError({"record_status": "排产状态参数不正确。"})
            queryset = queryset.filter(record_status=status_value)
        customer_id = _uuid(self.request.query_params.get("customer_id", "").strip(), "customer_id")
        if customer_id:
            queryset = queryset.filter(production_task__customer_account_id=customer_id)
        created_from = _date(self.request.query_params.get("created_from", "").strip(), "created_from")
        created_to = _date(self.request.query_params.get("created_to", "").strip(), "created_to")
        if created_from and created_to and created_from > created_to:
            raise ValidationError({"created_to": "结束日期不能早于开始日期。"})
        if created_from:
            queryset = queryset.filter(created_at__date__gte=created_from)
        if created_to:
            queryset = queryset.filter(created_at__date__lte=created_to)
        keyword = self.request.query_params.get("search", "").strip()
        if len(keyword) > 200:
            raise ValidationError({"search": "搜索内容不能超过 200 个字符。"})
        if keyword:
            queryset = queryset.filter(
                Q(schedule_number__icontains=keyword)
                | Q(production_task__task_number__icontains=keyword)
                | Q(production_task__order_number__icontains=keyword)
                | Q(production_task__customer_account__account_name__icontains=keyword)
                | Q(products__product_snapshot__product_name__icontains=keyword)
                | Q(products__product_snapshot__item_number__icontains=keyword)
            ).distinct()
        return queryset.order_by("-created_at", "-id")

    def list(self, request):
        page = self.paginate_queryset(self._filtered())
        return self.get_paginated_response(
            ScheduleReadSerializer(page, many=True, context={"include_audit": False}).data
        )

    def retrieve(self, request, pk=None):
        schedule = get_object_or_404(self.get_queryset(), pk=pk)
        response = Response({"data": ScheduleReadSerializer(schedule).data})
        response["ETag"] = etag_for_instance(schedule)
        return response

    def create(self, request):
        serializer = ScheduleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allowed_ids = set(accessible_production_tasks(request).filter(pk=serializer.validated_data["production_task_id"]).values_list("id", flat=True))
        if serializer.validated_data["production_task_id"] not in allowed_ids:
            raise ValidationError({"production_task_id": "生产任务单不存在或不可访问。"})
        schedule = create_schedule(validated_data=serializer.validated_data, actor_employee=request.employee, request=request)
        schedule = schedules_with_context().get(pk=schedule.pk)
        response = Response({"data": ScheduleReadSerializer(schedule).data}, status=status.HTTP_201_CREATED)
        response["ETag"] = etag_for_instance(schedule)
        return response

    @action(detail=False, methods=["post"], url_path="batch")
    def batch_create(self, request):
        serializer = ScheduleBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task_ids = {item["production_task_id"] for item in serializer.validated_data["schedules"]}
        allowed_ids = set(
            accessible_production_tasks(request).filter(pk__in=task_ids).values_list("id", flat=True)
        )
        if allowed_ids != task_ids:
            raise ValidationError({"schedules": "存在不可访问的生产任务单。"})
        schedules = create_schedule_batch(
            validated_data=serializer.validated_data,
            actor_employee=request.employee,
            request=request,
        )
        schedule_ids = [item.pk for item in schedules]
        schedule_map = {item.pk: item for item in schedules_with_context().filter(pk__in=schedule_ids)}
        data = [ScheduleReadSerializer(schedule_map[item_id]).data for item_id in schedule_ids]
        return Response({"data": data}, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        current = get_object_or_404(accessible_production_schedules(request), pk=pk)
        serializer = ScheduleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = update_schedule(
            schedule_id=current.pk, validated_data=serializer.validated_data,
            actor_employee=request.employee, request=request,
        )
        schedule = schedules_with_context().get(pk=schedule.pk)
        response = Response({"data": ScheduleReadSerializer(schedule).data})
        response["ETag"] = etag_for_instance(schedule)
        return response

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        current = get_object_or_404(accessible_production_schedules(request), pk=pk)
        serializer = ScheduleVoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = void_schedule(
            schedule_id=current.pk, reason=serializer.validated_data["reason"],
            actor_employee=request.employee, request=request,
        )
        schedule = schedules_with_context().get(pk=schedule.pk)
        response = Response({"data": ScheduleReadSerializer(schedule).data})
        response["ETag"] = etag_for_instance(schedule)
        return response

    @action(detail=False, methods=["get"], url_path="task-candidates")
    def task_candidates(self, request):
        latest_bom_status = Bom.objects.filter(
            production_task_id=OuterRef("production_task_id"),
            product_line_id=OuterRef("pk"),
            archived_at__isnull=True,
        ).order_by("-version_number", "-created_at", "-id").values("status")[:1]
        unready_product_lines = ProductionTaskProduct.objects.filter(
            production_task_id=OuterRef("pk"),
        ).annotate(
            latest_bom_status=Subquery(latest_bom_status),
        ).exclude(latest_bom_status=BomStatus.VERIFIED)
        queryset = production_tasks_with_context(
            accessible_production_tasks(request).filter(status=ProductionTaskStatus.READY, archived_at__isnull=True)
        ).prefetch_related("products__sales_order_delivery_batch_line__sales_order_line__product_image").exclude(
            production_schedules__record_status=ScheduleStatus.ACTIVE
        ).annotate(
            has_unready_product=Exists(unready_product_lines),
        ).filter(
            has_unready_product=False,
            purchase_order__status=PurchaseOrderStatus.COMPLETED,
            purchase_order__archived_at__isnull=True,
        ).distinct().order_by("-created_at", "-id")
        keyword = request.query_params.get("search", "").strip()
        if len(keyword) > 200:
            raise ValidationError({"search": "搜索内容不能超过 200 个字符。"})
        if keyword:
            queryset = queryset.filter(
                Q(task_number__icontains=keyword) | Q(order_number__icontains=keyword)
                | Q(customer_account__account_name__icontains=keyword)
                | Q(products__product_name_snapshot__icontains=keyword)
                | Q(products__item_number_snapshot__icontains=keyword)
            ).distinct()
        customer_id = _uuid(request.query_params.get("customer_id", "").strip(), "customer_id")
        if customer_id:
            queryset = queryset.filter(customer_account_id=customer_id)
        product_keyword = request.query_params.get("product_search", "").strip()
        if len(product_keyword) > 200:
            raise ValidationError({"product_search": "产品搜索内容不能超过 200 个字符。"})
        if product_keyword:
            queryset = queryset.filter(
                Q(products__product_name_snapshot__icontains=product_keyword)
                | Q(products__item_number_snapshot__icontains=product_keyword)
                | Q(products__product_number_snapshot__icontains=product_keyword)
            ).distinct()
        delivery_from = _date(request.query_params.get("delivery_from", "").strip(), "delivery_from")
        delivery_to = _date(request.query_params.get("delivery_to", "").strip(), "delivery_to")
        if delivery_from and delivery_to and delivery_from > delivery_to:
            raise ValidationError({"delivery_to": "结束日期不能早于开始日期。"})
        if delivery_from:
            queryset = queryset.filter(delivery_date__gte=delivery_from)
        if delivery_to:
            queryset = queryset.filter(delivery_date__lte=delivery_to)
        page = self.paginate_queryset(queryset)
        data = [self._task_payload(task, None, include_products=False) for task in page]
        return self.get_paginated_response(data)

    @action(detail=False, methods=["get"], url_path=r"task-candidates/(?P<task_id>[^/.]+)")
    def task_candidate_detail(self, request, task_id=None):
        task = get_object_or_404(
            production_tasks_with_context(
                accessible_production_tasks(request), include_progress=True
            ).prefetch_related(
                "purchase_order__lines", "products__sales_order_delivery_batch_line__sales_order_line__product_image",
            ).filter(
                status=ProductionTaskStatus.READY, archived_at__isnull=True
            ), pk=task_id,
        )
        existing = ProductionSchedule.objects.filter(production_task=task, record_status=ScheduleStatus.ACTIVE).first()
        return Response({"data": self._task_payload(task, existing.pk if existing else None, include_products=True)})

    @action(
        detail=False,
        methods=["get"],
        url_path=r"task-files/(?P<task_id>[^/.]+)/(?P<file_id>[^/.]+)",
    )
    def task_file(self, request, task_id=None, file_id=None):
        task = get_object_or_404(accessible_production_tasks(request), pk=task_id)
        business_file = get_object_or_404(
            BusinessFile.objects.filter(
                Q(production_task_product_images__product_line__production_task=task)
                | Q(production_task_products__production_task=task)
                | Q(production_task_details__product_line__production_task=task)
                | Q(pk__in=schedule_source_image_ids(task)),
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
            filename=business_file.original_name,
        )

    @staticmethod
    def _task_payload(task, existing_schedule_id, include_products):
        products = list(task.products.all())
        latest_bom_by_product = {}
        purchase_order = None
        purchase_order_product_ids = set()
        purchase_order_bom_ids = set()
        purchase_request_by_bom = {}
        if include_products:
            for bom in getattr(task, "_active_boms_for_status", []):
                latest_bom_by_product.setdefault(bom.product_line_id, bom)
            purchase_order = getattr(task, "purchase_order", None)
            if purchase_order is not None and purchase_order.archived_at is None:
                for purchase_line in purchase_order.lines.all():
                    if purchase_line.product_line_id_snapshot:
                        purchase_order_product_ids.add(purchase_line.product_line_id_snapshot)
                    if purchase_line.bom_id:
                        purchase_order_bom_ids.add(purchase_line.bom_id)
            purchase_request_by_bom = {
                item.bom_id: item
                for item in getattr(task, "_active_purchase_requests_for_status", [])
            }

        all_boms_verified = bool(products) and all(
            latest_bom_by_product.get(line.pk) is not None
            and latest_bom_by_product[line.pk].status == "VERIFIED"
            for line in products
        )
        purchase_completed = (
            purchase_order is not None
            and purchase_order.archived_at is None
            and purchase_order.status == PurchaseOrderStatus.COMPLETED
        )
        scheduling_blockers = []
        if include_products and not all_boms_verified:
            scheduling_blockers.append("生产任务单内所有产品的 BOM 必须已确认")
        if include_products and not purchase_completed:
            scheduling_blockers.append("采购订单必须为“已完成采购”")
        selectable = existing_schedule_id is None and (not include_products or not scheduling_blockers)
        unselectable_reason = ""
        if existing_schedule_id:
            unselectable_reason = "已有有效排产计划"
        elif scheduling_blockers:
            unselectable_reason = "；".join(scheduling_blockers)

        def product_progress(line):
            bom = latest_bom_by_product.get(line.pk)
            if bom is None:
                bom_status = "NOT_CREATED"
                bom_status_display = "未建立"
            elif bom.status == "VERIFIED":
                bom_status = "VERIFIED"
                bom_status_display = "已确认"
            else:
                bom_status = "PENDING_CONFIRMATION"
                bom_status_display = "待确认"

            if (
                purchase_order is not None
                and purchase_order.archived_at is None
                and (
                    purchase_order.status == PurchaseOrderStatus.COMPLETED
                    or line.pk in purchase_order_product_ids
                    or (bom is not None and bom.pk in purchase_order_bom_ids)
                )
            ):
                purchase_status = f"ORDER_{purchase_order.status}"
                purchase_status_display = purchase_order.get_status_display()
            elif bom is not None and bom.pk in purchase_request_by_bom:
                purchase_request = purchase_request_by_bom[bom.pk]
                purchase_status = f"REQUEST_{purchase_request.status}"
                purchase_status_display = {
                    "DRAFT": "采购申请草稿",
                    "SUBMITTED": "采购申请已提交",
                    "ALLOCATING": "供应商分配中",
                    "FULLY_ALLOCATED": "采购申请已分配",
                    "CANCELLED": "采购申请已取消",
                }.get(purchase_request.status, purchase_request.get_status_display())
            else:
                purchase_status = "NOT_STARTED"
                purchase_status_display = "未发起"
            return {
                "bom_status": bom_status,
                "bom_status_display": bom_status_display,
                "purchase_status": purchase_status,
                "purchase_status_display": purchase_status_display,
            }

        payload = {
            "id": str(task.pk), "task_number": task.task_number, "order_number": task.order_number,
            "sales_order_number": task.sales_order.order_number if task.sales_order_id else None,
            "customer_id": str(task.customer_account_id) if task.customer_account_id else None,
            "customer_name": task.customer_account.account_name if task.customer_account_id else "",
            "order_date": task.order_date, "delivery_date": task.delivery_date,
            "salesperson_name": task.salesperson.display_name,
            "follower_names": [employee.display_name for employee in task.followers.all()],
            "planned_start_date": task.planned_start_date,
            "planned_end_date": task.planned_end_date,
            "status": task.status, "status_display": task.get_status_display(),
            "product_count": len(products), "selectable": selectable,
            "unselectable_reason": unselectable_reason,
            "existing_schedule_id": str(existing_schedule_id) if existing_schedule_id else None,
            "source_revision_hash": source_revision(task, products),
            "product_summaries": [
                {
                    "id": str(line.pk), "item_number": line.item_number_snapshot,
                    "product_name": line.product_name_snapshot, "specification": line.specification_snapshot,
                    "color_name": line.color_name_snapshot,
                    "quantity": line.quantity, "unit_name": line.unit.unit_name,
                    **_task_product_display_fields(line),
                }
                for line in products
            ],
        }
        if include_products:
            payload["scheduling_ready"] = not scheduling_blockers
            payload["scheduling_blockers"] = scheduling_blockers
            payload["products"] = [
                {
                    "id": str(line.pk), "product_id": str(line.product_id), "line_number": line.line_number,
                    "product_number": line.product_number_snapshot, "product_code": line.product_code_snapshot,
                    "item_number": line.item_number_snapshot, "product_name": line.product_name_snapshot,
                    "specification": line.specification_snapshot, "color_name": line.color_name_snapshot,
                    "color_code": line.color_code_snapshot, "quantity": line.quantity,
                    "unit_id": str(line.unit_id), "unit_name": line.unit.unit_name,
                    "dimensions": {"expanded": None, "folded": None, "source": None},
                    **_task_product_display_fields(line),
                    **product_progress(line),
                }
                for line in products
            ]
        return payload

    @action(detail=False, methods=["get"])
    def options(self, request):
        crafts = Craft.objects.filter(status=RecordStatus.ACTIVE).select_related("workshop").order_by("craft_type", "name", "id")
        return Response({"data": {
            "crafts": [
                {"id": str(item.pk), "name": item.name, "craft_type": item.craft_type,
                 "craft_type_display": item.get_craft_type_display(), "plan_category": item.plan_category,
                 "workshop_name": item.workshop.name if item.workshop_id else None}
                for item in crafts
            ],
            "plan_categories": [{"value": value, "label": label} for value, label in PlanCategory.choices],
            "customers": [
                {"id": str(item.pk), "name": item.account_name, "code": item.account_code}
                for item in accessible_customers(request).filter(archived_at__isnull=True).order_by("account_name", "id")[:500]
            ],
        }})


class ProductionScheduleItemViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = ScheduleItemReadSerializer
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {"list": "production_scheduling.view_productionschedule"}

    def list(self, request):
        category = request.query_params.get("category", "").strip().upper()
        if category not in PlanCategory.values:
            raise ValidationError({"category": "category 必须为 METAL、CUTTING、SEWING 或 ASSEMBLY。"})
        queryset = schedule_items_for_category(request, category)
        keyword = request.query_params.get("search", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(schedule__schedule_number__icontains=keyword)
                | Q(schedule__production_task__task_number__icontains=keyword)
                | Q(product_snapshot__product_name__icontains=keyword)
                | Q(product_snapshot__item_number__icontains=keyword)
            )
        customer_id = _uuid(request.query_params.get("customer_id", "").strip(), "customer_id")
        if customer_id:
            queryset = queryset.filter(schedule__production_task__customer_account_id=customer_id)
        schedule_id = _uuid(request.query_params.get("schedule_id", "").strip(), "schedule_id")
        if schedule_id:
            queryset = queryset.filter(schedule_id=schedule_id)
        schedule_product_id = _uuid(request.query_params.get("schedule_product_id", "").strip(), "schedule_product_id")
        if schedule_product_id:
            queryset = queryset.filter(pk=schedule_product_id)
        date_from = _date(request.query_params.get("date_from", "").strip(), "date_from")
        date_to = _date(request.query_params.get("date_to", "").strip(), "date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError({"date_to": "结束日期不能早于开始日期。"})
        field = {"METAL": "metal_return_date", "CUTTING": "sewing_return_date", "SEWING": "sewing_return_date", "ASSEMBLY": "finished_inbound_date"}[category]
        if date_from:
            queryset = queryset.filter(**{f"{field}__gte": date_from})
        if date_to:
            queryset = queryset.filter(**{f"{field}__lte": date_to})
        queryset = queryset.order_by(field, "schedule__schedule_number", "line_number", "id")
        page = self.paginate_queryset(queryset)
        serializer = ScheduleItemReadSerializer(page, many=True, context={"category": category})
        return self.get_paginated_response(serializer.data)
