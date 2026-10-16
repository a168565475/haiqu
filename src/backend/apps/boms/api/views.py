import csv
from datetime import datetime, time, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.products.models import ProductInformation, ProductStatus, RawMaterialInformation
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from apps.production_tasks.services import replace_unbound_product_line
from apps.production_tasks.selectors import accessible_production_tasks, production_tasks_with_context
from apps.reference_data.models import (
    AccessoryColor,
    AccessoryMaterial,
    AccessoryProductName,
    AccessorySpecification,
    FabricMaterial,
    FabricSpecification,
    FabricWidth,
    ProductCategory,
    ProductColor,
    ProductItemType,
    ProductionUnit,
    ReferenceStatus,
    Currency,
)
from apps.reference_data.pinyin_search import build_pinyin_search
from apps.samples.sampling_detail_config import load_sampling_detail_template

from ..maintenance import CONFIGURED_FIELD_LABELS
from ..models import Bom, BomCreationMethod, BomStatus
from ..material_flow_calculations import MaterialFlowValueError, decimal_quantity, pipe_plan, positive_integer
from ..selectors import accessible_boms, boms_with_context, pipe_material_matches, search_boms
from ..services import (
    confirm_bom_product,
    create_bom,
    preview_imported_bom,
    sync_latest_boms_from_order,
    update_bom_lines,
    verify_bom,
)
from .serializers import (
    BomCreateInputSerializer,
    BomMaterialFlowPreviewInputSerializer,
    BomMaterialFlowPreviewResponseSerializer,
    BomDetailSerializer,
    BomAccessoryMaterialOptionSerializer,
    BomAuxiliaryProductOptionSerializer,
    BomAuxiliaryCreateInputSerializer,
    BomEditorReferenceOptionsResponseSerializer,
    BomFabricMaterialOptionSerializer,
    BomFabricSpecificationOptionSerializer,
    BomFabricWidthOptionSerializer,
    BomHardwareMaterialSerializer,
    BomPipeMaterialMatchQuerySerializer,
    BomPipeMaterialMatchResponseSerializer,
    BomPipeMaterialMatchResultSerializer,
    BomListSerializer,
    BomPreviewInputSerializer,
    BomProductConfirmationSerializer,
    BomProductColorOptionSerializer,
    BomRawMaterialGroupSerializer,
    BomRawMaterialGroupsResponseSerializer,
    BomUpdateInputSerializer,
    BomVerifyInputSerializer,
)


RAW_MATERIAL_LIST_PARAMETERS = [
    OpenApiParameter(
        name="q",
        type=str,
        required=False,
        description="按品号、品名、材质、颜色或规格模糊搜索，最长 100 个字符。",
    ),
    OpenApiParameter(
        name="material_name",
        type=str,
        required=False,
        description="按品名分组的完整名称精确筛选，最长 200 个字符。",
    ),
]


class BomViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    ordering = ["-updated_at", "-id"]
    action_permission_map = {
        "list": "boms.view_bom",
        "retrieve": "boms.view_bom",
        "stats": "boms.view_bom",
        "export": "boms.view_bom",
        "options": "boms.view_bom",
        "hardware_materials": "boms.change_bom",
        "pipe_materials": "boms.change_bom",
        "pipe_material_matches": "boms.change_bom",
        "material_flow_preview": "boms.change_bom",
        "fabric_materials": "boms.change_bom",
        "hardware_material_groups": "boms.change_bom",
        "plastic_materials": "boms.change_bom",
        "plastic_material_groups": "boms.change_bom",
        "packaging_materials": "boms.change_bom",
        "packaging_material_groups": "boms.change_bom",
        "semi_finished_materials": "boms.change_bom",
        "semi_finished_material_groups": "boms.change_bom",
        "editor_reference_options": "boms.change_bom",
        "create_auxiliary_reference": "boms.change_bom",
        "create": "boms.add_bom",
        "preview_import": "boms.add_bom",
        "partial_update": "boms.change_bom",
        "sync_order_quantity": "boms.change_bom",
        "verify": "boms.verify_bom",
        "confirm_product": "boms.change_bom",
        "archive": "boms.delete_bom",
    }

    def _filtered_queryset(self, *, include_status=True):
        queryset = accessible_boms(self.request)
        status_value = self.request.query_params.get("status", "").strip().upper()
        if status_value:
            if status_value not in BomStatus.values:
                raise ValidationError({"status": "BOM 状态参数不正确。"})
            if include_status:
                queryset = queryset.filter(status=status_value)

        category_id = self.request.query_params.get("product_category_id", "").strip()
        if category_id:
            try:
                UUID(category_id)
            except (TypeError, ValueError) as exc:
                raise ValidationError({"product_category_id": "产品类别参数不正确。"}) from exc
            queryset = queryset.filter(
                Q(product_category_id=category_id)
                | Q(product_category__isnull=True, product_line__product__category_id=category_id)
            )

        updated_after = self._date_param("updated_after")
        updated_before = self._date_param("updated_before")
        if updated_after and updated_before and updated_after > updated_before:
            raise ValidationError({"updated_before": "更新结束日期不能早于开始日期。"})
        if updated_after:
            queryset = queryset.filter(
                updated_at__gte=timezone.make_aware(datetime.combine(updated_after, time.min))
            )
        if updated_before:
            exclusive_end = updated_before + timedelta(days=1)
            queryset = queryset.filter(
                updated_at__lt=timezone.make_aware(datetime.combine(exclusive_end, time.min))
            )

        search_text = self.request.query_params.get("q", "").strip()
        if len(search_text) > 200:
            raise ValidationError({"q": "搜索内容不能超过 200 个字符。"})
        queryset = search_boms(queryset, search_text)
        return queryset.distinct()

    def get_queryset(self):
        queryset = self._filtered_queryset()
        return boms_with_context(
            queryset.order_by(*self.ordering),
            include_lines=self.action == "retrieve",
            read_optimized=self.action in {"list", "retrieve"},
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
        return BomDetailSerializer if self.action == "retrieve" else BomListSerializer

    @staticmethod
    def _detail_response(bom, response_status=status.HTTP_200_OK):
        response = Response({"data": BomDetailSerializer(bom).data}, status=response_status)
        response["ETag"] = etag_for_instance(bom)
        return response

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
        return boms_with_context(queryset.order_by(*self.ordering))

    @action(detail=False, methods=["get", "post"])
    def export(self, request):
        rows = BomListSerializer(self._export_queryset(), many=True).data
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(["BOM编号", "订单号", "产品编号", "产品名称", "产品规格", "订单数量", "用料分区", "校验状态", "更新人", "更新时间"])
        for row in rows:
            sections = "；".join(
                f"{item['label']} {item['count']}项" for item in row["section_summary"]
            )
            writer.writerow([
                self._csv_cell(row["bom_number"]),
                self._csv_cell(row.get("source_sales_order_number") or "历史未关联"),
                self._csv_cell(row["product_code_snapshot"]),
                self._csv_cell(row["product_name_snapshot"]),
                self._csv_cell(row["specification_snapshot"]),
                row["order_quantity"],
                self._csv_cell(sections),
                self._csv_cell(row["status_display"]),
                self._csv_cell(row["updated_by_name"]),
                row["updated_at"],
            ])
        response["Content-Disposition"] = 'attachment; filename="boms.csv"'
        response["X-Export-Count"] = str(len(rows))
        return response

    def _require_production_task_access(self):
        if not self.request.user.has_perm("production_tasks.view_productiontask"):
            raise PermissionDenied("当前账号没有查看生产任务单的权限。")

    def _product_line(self, product_line_id):
        self._require_production_task_access()
        accessible_task_ids = accessible_production_tasks(self.request).values("id")
        try:
            return ProductionTaskProduct.objects.select_related(
                "production_task",
                "product",
                "product__category",
                "unit",
            ).prefetch_related("production_task__delivery_batches", "production_task__products").get(
                pk=product_line_id,
                production_task_id__in=accessible_task_ids,
                production_task__archived_at__isnull=True,
            )
        except ProductionTaskProduct.DoesNotExist as exc:
            raise NotFound("未找到可访问的生产任务产品。") from exc

    def create(self, request):
        serializer = BomCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product_line = self._product_line(serializer.validated_data["production_task_product_id"])
        product_update = serializer.validated_data.get("production_task_product_update")
        if product_update:
            if product_line.sales_order_delivery_batch_line_id:
                raise Conflict("该颜色明细来源于销售订单，产品、颜色和数量必须保持锁定。")
            if not request.user.has_perm("production_tasks.change_productiontask"):
                raise PermissionDenied("当前账号没有修改生产任务单的权限。")
            if str(product_update["client_key"]) != str(product_line.pk):
                raise ValidationError({"production_task_product_update": "颜色明细编号与当前生产任务不一致。"})
            if product_update["currency"].pk != product_line.production_task.currency_id:
                raise ValidationError({"production_task_product_update": "币种必须与生产任务基础信息一致。"})
        source_bom = None
        source_bom_id = serializer.validated_data.get("source_bom_id")
        if source_bom_id:
            try:
                source_bom = boms_with_context(accessible_boms(request), include_lines=True).get(pk=source_bom_id)
            except Bom.DoesNotExist as exc:
                raise NotFound("未找到可复制的历史 BOM。") from exc
        with transaction.atomic():
            locked_task = ProductionTask.objects.select_for_update().get(pk=product_line.production_task_id)
            if locked_task.status not in {
                ProductionTaskStatus.READY,
                ProductionTaskStatus.IN_PRODUCTION,
            }:
                raise Conflict("生产任务单必须经 PMC 确认后，才能创建 BOM。")
            locked_line = ProductionTaskProduct.objects.select_for_update().select_related(
                "production_task", "unit", "currency"
            ).get(pk=product_line.pk)
            if product_update:
                require_matching_etag(request, locked_task)
                locked_line = replace_unbound_product_line(
                    task=locked_task,
                    product_line=locked_line,
                    product_data=product_update,
                    files=request.FILES,
                    actor_employee=getattr(request, "employee", None),
                    request=request,
                )
            if source_bom and source_bom.product_line.product_id != locked_line.product_id:
                raise ValidationError({"source_bom_id": "历史 BOM 必须与更换后的产品一致。"})
            bom = create_bom(
                product_line=locked_line,
                creation_method=serializer.validated_data["creation_method"],
                actor_employee=getattr(request, "employee", None),
                uploaded_file=serializer.validated_data.get("workbook"),
                source_bom=source_bom,
                quantity_difference_reason=serializer.validated_data.get("quantity_difference_reason", ""),
                request=request,
            )
        return self._detail_response(
            boms_with_context(include_lines=True).get(pk=bom.pk),
            status.HTTP_201_CREATED,
        )

    def retrieve(self, request, *args, **kwargs):
        return self._detail_response(self.get_object())

    @extend_schema(request=BomProductConfirmationSerializer, responses=BomDetailSerializer)
    @action(detail=True, methods=["post"], url_path="confirm-product")
    def confirm_product(self, request, pk=None):
        bom = self.get_object()
        require_matching_etag(request, bom)
        serializer = BomProductConfirmationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        confirmed = confirm_bom_product(
            bom=bom,
            product=serializer.validated_data.get("product"),
            new_product=serializer.validated_data.get("new_product"),
            product_color=serializer.validated_data["product_color"],
            color_code=serializer.validated_data.get("color_code", ""),
            material=serializer.validated_data.get("material"),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        return self._detail_response(boms_with_context(include_lines=True).get(pk=confirmed.pk))

    @extend_schema(request=None, responses=None)
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        bom = self.get_object()
        require_matching_etag(request, bom)
        bom.archived_at = timezone.now()
        bom.archived_by_employee = getattr(request, "employee", None)
        bom.archive_reason = "BOM 列表删除"
        bom.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])
        write_audit_log(
            object_type="BOM",
            object_id=bom.pk,
            context_type="PRODUCTION_TASK",
            context_id=bom.production_task_id,
            action="ARCHIVE",
            actor_employee=getattr(request, "employee", None),
            before_data={"archived_at": None, "bom_number": bom.bom_number},
            after_data={"archived_at": bom.archived_at.isoformat(), "bom_number": bom.bom_number},
            request=request,
        )
        return Response({"data": {"id": str(bom.pk), "archived": True}})

    @extend_schema(request=BomUpdateInputSerializer, responses=BomDetailSerializer)
    def partial_update(self, request, *args, **kwargs):
        bom = self.get_object()
        require_matching_etag(request, bom)
        serializer = BomUpdateInputSerializer(data=request.data, context={"bom": bom})
        serializer.is_valid(raise_exception=True)
        updated = update_bom_lines(
            bom=bom,
            sections=serializer.validated_data["sections"],
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        return self._detail_response(updated)

    @extend_schema(request=None, responses=BomDetailSerializer)
    @action(detail=True, methods=["post"], url_path="sync-order-quantity")
    @transaction.atomic
    def sync_order_quantity(self, request, pk=None):
        bom = self.get_object()
        ProductionTask.objects.select_for_update().get(pk=bom.production_task_id)
        bom = boms_with_context().select_for_update(of=("self",)).get(pk=bom.pk)
        require_matching_etag(request, bom)
        if bom.latest_active_bom_id != bom.pk:
            raise ValidationError({"bom": "只能同步该产品最新版本的 BOM。"})
        product_line = bom.product_line
        product_is_current = all(
            [
                bom.product_number_snapshot == product_line.product_number_snapshot,
                bom.product_code_snapshot == product_line.product_code_snapshot,
                bom.product_name_snapshot == product_line.product_name_snapshot,
                bom.specification_snapshot == product_line.specification_snapshot,
            ]
        )
        if bom.product_line.quantity == bom.order_quantity and product_is_current:
            refreshed = boms_with_context(include_lines=True).get(pk=bom.pk)
            return self._detail_response(refreshed)

        synced = sync_latest_boms_from_order(
            product_line_ids=[bom.product_line_id],
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        if not synced:
            raise ValidationError({"bom": "未找到可同步的 BOM。"})
        refreshed = boms_with_context(include_lines=True).get(pk=synced[0].pk)
        return self._detail_response(refreshed)

    @extend_schema(request=BomVerifyInputSerializer, responses=BomDetailSerializer)
    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        bom = self.get_object()
        require_matching_etag(request, bom)
        serializer = BomVerifyInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        verified = verify_bom(
            bom=bom,
            quantity_confirmation_reason=serializer.validated_data.get("quantity_confirmation_reason", ""),
            actor_employee=getattr(request, "employee", None),
            request=request,
        )
        return self._detail_response(boms_with_context(include_lines=True).get(pk=verified.pk))

    @action(detail=False, methods=["post"], url_path="preview-import")
    def preview_import(self, request):
        serializer = BomPreviewInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product_line = self._product_line(serializer.validated_data["production_task_product_id"])
        product_update = serializer.validated_data.get("production_task_product_update")
        if product_update:
            if product_line.sales_order_delivery_batch_line_id:
                raise Conflict("该颜色明细来源于销售订单，产品、颜色和数量必须保持锁定。")
            if not request.user.has_perm("production_tasks.change_productiontask"):
                raise PermissionDenied("当前账号没有修改生产任务单的权限。")
            if str(product_update["client_key"]) != str(product_line.pk):
                raise ValidationError({"production_task_product_update": "颜色明细编号与当前生产任务不一致。"})
            if product_update["currency"].pk != product_line.production_task.currency_id:
                raise ValidationError({"production_task_product_update": "币种必须与生产任务基础信息一致。"})
            if product_line.boms.exists():
                raise Conflict("该颜色明细已经生成 BOM，不能更换产品。")
            product_line.product = product_update["product"]
            product_line.product_number_snapshot = product_update["product"].product_number
            product_line.product_code_snapshot = product_update["product"].product_code
            product_line.product_name_snapshot = product_update["product"].product_name
            product_line.specification_snapshot = product_update["product"].specification
            product_line.quantity = product_update["quantity"]
        preview = preview_imported_bom(
            serializer.validated_data["workbook"],
            getattr(request, "employee", None),
            product_line,
        )
        return Response({"data": preview})

    @staticmethod
    def _active_raw_materials(*, item_type, category_name=None):
        queryset = RawMaterialInformation.objects.filter(
            item_type=item_type,
            category__item_type=item_type,
            category__status=ReferenceStatus.ACTIVE,
            category__archived_at__isnull=True,
            archived_at__isnull=True,
        )
        if category_name:
            queryset = queryset.filter(category__category_name=category_name)
        return queryset

    def _raw_material_list_response(self, request, *, item_type, category_name=None, label, unit_name=None):
        keyword = request.query_params.get("q", "").strip()
        if len(keyword) > 100:
            raise ValidationError({"q": f"{label}数据搜索内容不能超过 100 个字符。"})

        material_name = request.query_params.get("material_name", "").strip()
        if len(material_name) > 200:
            raise ValidationError({"material_name": f"{label}品名不能超过 200 个字符。"})

        queryset = self._active_raw_materials(
            item_type=item_type,
            category_name=category_name,
        ).select_related("category", "unit", "color")
        if unit_name:
            queryset = queryset.filter(unit__unit_name=unit_name, unit__status=ReferenceStatus.ACTIVE)
        if material_name:
            queryset = queryset.filter(material_name=material_name)
        if keyword:
            queryset = queryset.filter(
                Q(material_number__icontains=keyword)
                | Q(material_name__icontains=keyword)
                | Q(material__icontains=keyword)
                | Q(color__color_name__icontains=keyword)
                | Q(color_snapshot__icontains=keyword)
                | Q(specification__icontains=keyword)
            )
        queryset = queryset.order_by("material_number", "id")
        page = self.paginate_queryset(queryset)
        serializer = BomHardwareMaterialSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def _raw_material_groups_response(self, *, item_type, category_name=None):
        groups = (
            self._active_raw_materials(
                item_type=item_type,
                category_name=category_name,
            )
            .values("material_name")
            .annotate(count=Count("id"))
            .order_by("material_name")
        )
        data = [
            {
                **group,
                "pinyin_search": build_pinyin_search(group["material_name"]),
            }
            for group in groups
        ]
        return Response({"data": BomRawMaterialGroupSerializer(data, many=True).data})

    @extend_schema(request=BomMaterialFlowPreviewInputSerializer, responses=BomMaterialFlowPreviewResponseSerializer)
    @action(detail=False, methods=["post"], url_path="material-flow-preview")
    def material_flow_preview(self, request):
        serializer = BomMaterialFlowPreviewInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            if values['kind'] == 'PIPE':
                result = pipe_plan(**{key: values.get(key) for key in ('cutting_length_mm', 'pieces_per_product', 'pieces_per_bar', 'order_quantity')})
            else:
                quantity = positive_integer(values['order_quantity'], 'order_quantity')
                consumption = decimal_quantity(values.get('unit_consumption'), 'unit_consumption')
                with localcontext() as context:
                    context.prec = 64
                    meters = decimal_quantity(quantity * consumption, 'suggested_purchase_meters')
                result = {'schema_version': 2, 'order_quantity': quantity, 'suggested_purchase_meters': format(meters, '.4f'), 'unit': '米'}
        except MaterialFlowValueError as error:
            raise ValidationError({error.field: str(error)}) from error
        return Response({'data': result})

    @extend_schema(parameters=RAW_MATERIAL_LIST_PARAMETERS, responses=BomHardwareMaterialSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="pipe-materials")
    def pipe_materials(self, request):
        return self._raw_material_list_response(request, item_type=ProductItemType.MATERIAL,
                                               category_name="管材", unit_name="根", label="管材")

    @extend_schema(parameters=[BomPipeMaterialMatchQuerySerializer], responses=BomPipeMaterialMatchResponseSerializer)
    @action(detail=False, methods=["get"], url_path="pipe-material-matches")
    def pipe_material_matches(self, request):
        serializer = BomPipeMaterialMatchQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        result = pipe_material_matches(**serializer.validated_data)
        return Response({"data": BomPipeMaterialMatchResultSerializer(result).data})

    @extend_schema(parameters=RAW_MATERIAL_LIST_PARAMETERS, responses=BomHardwareMaterialSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="fabric-materials")
    def fabric_materials(self, request):
        return self._raw_material_list_response(request, item_type=ProductItemType.MATERIAL,
                                               category_name="面料", unit_name="米", label="面料")

    @extend_schema(parameters=RAW_MATERIAL_LIST_PARAMETERS, responses=BomHardwareMaterialSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="hardware-materials")
    def hardware_materials(self, request):
        return self._raw_material_list_response(
            request,
            item_type=ProductItemType.MATERIAL,
            category_name="五金",
            label="五金",
        )

    @extend_schema(responses=BomRawMaterialGroupsResponseSerializer)
    @action(detail=False, methods=["get"], url_path="hardware-material-groups")
    def hardware_material_groups(self, request):
        return self._raw_material_groups_response(
            item_type=ProductItemType.MATERIAL,
            category_name="五金",
        )

    @extend_schema(parameters=RAW_MATERIAL_LIST_PARAMETERS, responses=BomHardwareMaterialSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="plastic-materials")
    def plastic_materials(self, request):
        return self._raw_material_list_response(
            request,
            item_type=ProductItemType.MATERIAL,
            category_name="塑料件",
            label="塑料件",
        )

    @extend_schema(responses=BomRawMaterialGroupsResponseSerializer)
    @action(detail=False, methods=["get"], url_path="plastic-material-groups")
    def plastic_material_groups(self, request):
        return self._raw_material_groups_response(
            item_type=ProductItemType.MATERIAL,
            category_name="塑料件",
        )

    @extend_schema(parameters=RAW_MATERIAL_LIST_PARAMETERS, responses=BomHardwareMaterialSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="packaging-materials")
    def packaging_materials(self, request):
        return self._raw_material_list_response(
            request,
            item_type=ProductItemType.MATERIAL,
            category_name="包材",
            label="包材",
        )

    @extend_schema(responses=BomRawMaterialGroupsResponseSerializer)
    @action(detail=False, methods=["get"], url_path="packaging-material-groups")
    def packaging_material_groups(self, request):
        return self._raw_material_groups_response(
            item_type=ProductItemType.MATERIAL,
            category_name="包材",
        )

    @extend_schema(parameters=RAW_MATERIAL_LIST_PARAMETERS, responses=BomHardwareMaterialSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="semi-finished-materials")
    def semi_finished_materials(self, request):
        return self._raw_material_list_response(
            request,
            item_type=ProductItemType.SEMI_FINISHED,
            label="半成品",
        )

    @extend_schema(responses=BomRawMaterialGroupsResponseSerializer)
    @action(detail=False, methods=["get"], url_path="semi-finished-material-groups")
    def semi_finished_material_groups(self, request):
        return self._raw_material_groups_response(item_type=ProductItemType.SEMI_FINISHED)

    @extend_schema(responses=BomEditorReferenceOptionsResponseSerializer)
    @action(detail=False, methods=["get"], url_path="editor-reference-options")
    def editor_reference_options(self, request):
        active_filter = {
            "status": ReferenceStatus.ACTIVE,
            "archived_at__isnull": True,
        }
        auxiliary_products = AccessoryProductName.objects.filter(**active_filter).prefetch_related(
            Prefetch(
                "specifications",
                queryset=AccessorySpecification.objects.filter(**active_filter),
                to_attr="active_specifications",
            ),
            Prefetch(
                "colors",
                queryset=AccessoryColor.objects.filter(**active_filter),
                to_attr="active_colors",
            ),
        )
        data = {
            "auxiliary_products": BomAuxiliaryProductOptionSerializer(auxiliary_products, many=True).data,
            "accessory_materials": BomAccessoryMaterialOptionSerializer(
                AccessoryMaterial.objects.filter(**active_filter), many=True
            ).data,
            "fabric_materials": BomFabricMaterialOptionSerializer(
                FabricMaterial.objects.filter(**active_filter), many=True
            ).data,
            "fabric_specifications": BomFabricSpecificationOptionSerializer(
                FabricSpecification.objects.filter(**active_filter), many=True
            ).data,
            "fabric_widths": BomFabricWidthOptionSerializer(
                FabricWidth.objects.filter(**active_filter), many=True
            ).data,
            "product_colors": BomProductColorOptionSerializer(
                ProductColor.objects.filter(**active_filter), many=True
            ).data,
        }
        return Response({"data": data})

    @extend_schema(request=BomAuxiliaryCreateInputSerializer, responses=BomAuxiliaryProductOptionSerializer)
    @action(detail=False, methods=["post"], url_path="create-auxiliary-reference")
    def create_auxiliary_reference(self, request):
        required_permissions = (
            "reference_data.add_accessoryproductname",
            "reference_data.add_accessoryspecification",
            "reference_data.add_accessorycolor",
            "reference_data.add_accessorymaterial",
        )
        if not request.user.is_superuser and not all(request.user.has_perm(code) for code in required_permissions):
            raise PermissionDenied("需要辅料品名、规格、颜色和材质的新增权限。")
        serializer = BomAuxiliaryCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if AccessoryProductName.objects.filter(product_name=values["product_name"]).exists():
            raise ValidationError({"product_name": "辅料品名已存在，请直接在选择页查询。"})

        with transaction.atomic():
            product = AccessoryProductName.objects.create(
                product_name=values["product_name"],
                unit_name=values["unit_name"],
                status=ReferenceStatus.ACTIVE,
            )
            specification = AccessorySpecification.objects.create(
                product_name=product,
                specification_value=values["specification"],
                status=ReferenceStatus.ACTIVE,
            )
            color = AccessoryColor.objects.create(
                product_name=product,
                color_name=values["color"],
                status=ReferenceStatus.ACTIVE,
            )
            material_name = values.get("material", "")
            if material_name:
                existing_material = AccessoryMaterial.objects.filter(material_name=material_name).first()
                if existing_material and (
                    existing_material.status != ReferenceStatus.ACTIVE or existing_material.archived_at is not None
                ):
                    raise ValidationError({"material": "同名辅料材质已停用或归档，请先在生产维护中处理。"})
                if existing_material is None:
                    AccessoryMaterial.objects.create(
                        material_name=material_name,
                        status=ReferenceStatus.ACTIVE,
                    )
            product.active_specifications = [specification]
            product.active_colors = [color]
        return Response({"data": BomAuxiliaryProductOptionSerializer(product).data}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        queryset = self._filtered_queryset(include_status=False)
        counts = queryset.aggregate(
            total=Count("pk"),
            pending_confirmation=Count("pk", filter=Q(status=BomStatus.PENDING_CONFIRMATION)),
            verified=Count("pk", filter=Q(status=BomStatus.VERIFIED)),
            maintenance_reference_count=Sum("maintenance_match_count", default=0),
        )
        return Response({"data": counts})

    @extend_schema(parameters=[OpenApiParameter(
        name="scope", type=str, enum=["full", "filters"],
        description="默认 full 返回新建与编辑所需选项；filters 仅返回列表产品类别。",
    )])
    @action(detail=False, methods=["get"])
    def options(self, request):
        scope = request.query_params.get("scope", "full")
        if scope not in {"full", "filters"}:
            raise ValidationError({"scope": "选项范围必须为 full 或 filters。"})
        categories = ProductCategory.objects.filter(
            item_type=ProductItemType.FINISHED,
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).values("id", "category_name")
        if scope == "filters":
            return Response({"data": {"product_categories": list(categories)}})
        tasks = []
        if request.user.has_perm("production_tasks.view_productiontask"):
            task_query = request.query_params.get("task_q", "").strip()
            if len(task_query) > 100:
                raise ValidationError({"task_q": "生产任务搜索内容不能超过 100 个字符。"})
            task_queryset = (
                accessible_production_tasks(request)
                .filter(
                    archived_at__isnull=True,
                    status__in=[ProductionTaskStatus.READY, ProductionTaskStatus.IN_PRODUCTION],
                )
                .order_by("-updated_at")
            )
            if task_query:
                task_queryset = task_queryset.filter(
                    Q(task_number__icontains=task_query)
                    | Q(order_number__icontains=task_query)
                    | Q(products__product_number_snapshot__icontains=task_query)
                    | Q(products__product_code_snapshot__icontains=task_query)
                    | Q(products__product_name_snapshot__icontains=task_query)
                ).distinct()
            tasks = production_tasks_with_context(task_queryset)[:100]
        product_lines = []
        for task in tasks:
            batches = list(task.delivery_batches.all())
            batch_quantity = sum((Decimal(batch.quantity) for batch in batches), Decimal("0"))
            existing_counts = {
                item["product_line_id"]: item["count"]
                for item in Bom.objects.filter(product_line__production_task=task)
                .values("product_line_id")
                .annotate(count=Count("id"))
            }
            for product in task.products.all():
                if existing_counts.get(product.id, 0) > 0:
                    continue
                product_lines.append(
                    {
                        "id": product.id,
                        "production_task_id": task.id,
                        "task_etag": etag_for_instance(task),
                        "task_number": task.task_number,
                        "order_number": task.order_number,
                        "customer_name": task.customer_account.account_name if task.customer_account_id else "",
                        "task_currency_id": task.currency_id,
                        "task_currency_code": task.currency.code,
                        "task_status": task.status,
                        "task_status_display": task.get_status_display(),
                        "product_number": product.product_number_snapshot,
                        "product_id": product.product_id,
                        "product_code": product.product_code_snapshot,
                        "product_name": product.product_name_snapshot,
                        "specification": product.specification_snapshot,
                        "order_quantity": product.quantity,
                        "source_delivery_batch_line_id": product.sales_order_delivery_batch_line_id,
                        "batch_quantity": batch_quantity if batches else None,
                        "delivery_date": task.delivery_date,
                        "planned_start_date": task.planned_start_date,
                        "planned_end_date": task.planned_end_date,
                        "existing_bom_count": 0,
                    }
                )

        history = BomListSerializer(
            boms_with_context(accessible_boms(request).order_by("-updated_at")[:100]),
            many=True,
        ).data
        products = ProductInformation.objects.filter(
            status=ProductStatus.ACTIVE,
            archived_at__isnull=True,
        ).select_related("unit", "product_item").order_by("product_number")[:1000]
        currencies = Currency.objects.filter(
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).order_by("sort_order", "code")
        units = ProductionUnit.objects.filter(
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).order_by("sort_order", "unit_code")
        colors = ProductColor.objects.filter(
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).order_by("sort_order", "color_card", "color_code")
        return Response(
            {
                "data": {
                    "production_task_products": product_lines,
                    "products": [{
                        "id": str(item.pk),
                        "product_number": item.product_number,
                        "product_code": item.product_code,
                        "item_number": item.product_item.item_number,
                        "product_name": item.product_name,
                        "specification": item.specification,
                        "default_unit_id": str(item.unit_id),
                    } for item in products],
                    "currencies": [{
                        "id": str(item.pk), "code": item.code, "name": item.chinese_name, "symbol": item.symbol,
                    } for item in currencies],
                    "units": [{
                        "id": str(item.pk), "unit_code": item.unit_code, "unit_name": item.unit_name,
                    } for item in units],
                    "colors": [{
                        "id": str(item.pk), "color_card": item.color_card,
                        "color_code": item.color_code, "color_name": item.color_name,
                    } for item in colors],
                    "detail_template": list(load_sampling_detail_template()),
                    "history_boms": history,
                    "product_categories": list(categories),
                    "creation_methods": [
                        {"value": value, "label": label} for value, label in BomCreationMethod.choices
                    ],
                    "configured_field_labels": CONFIGURED_FIELD_LABELS,
                    "updated_date_presets": [
                        {"value": "", "label": "全部日期"},
                        {"value": (timezone.localdate() - timedelta(days=30)).isoformat(), "label": "最近 30 天"},
                        {"value": (timezone.localdate() - timedelta(days=90)).isoformat(), "label": "最近 90 天"},
                    ],
                }
            }
        )
