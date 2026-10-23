from django.db import transaction
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.generics import get_object_or_404

from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.production_tasks.models import ProductionTask
from .source_selectors import occupied_products, product_option, require_source_task, salesperson_changes, salesperson_data, source_products, source_revision, source_tasks
from .statement_models import ReceivableStatement
from .statement_serializers import SourceQuerySerializer

SOURCE_PERMISSIONS = [f"finance.{action}_receivablestatement" for action in ("view", "add", "change")] + ["finance.add_receipt"]


def source_task_data(task):
    return {"id": str(task.pk), "task_number": task.task_number, "source_order_date": task.order_date,
            "status": task.status, "salesperson": salesperson_data(task)}


class SourceTaskSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    task_number = serializers.CharField()
    source_order_date = serializers.DateField(source="order_date")
    status = serializers.CharField()
    salesperson = serializers.SerializerMethodField()

    def get_salesperson(self, obj) -> dict:
        return salesperson_data(obj)


class FinanceSourceTaskViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = SourceTaskSerializer
    queryset = ProductionTask.objects.none()
    http_method_names = ["get", "head", "options"]
    action_permission_map = {"list": SOURCE_PERMISSIONS, "products": SOURCE_PERMISSIONS}

    @extend_schema(parameters=[SourceQuerySerializer])
    def list(self, request):
        query = SourceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page = self.paginate_queryset(source_tasks(query.validated_data))
        return self.get_paginated_response(SourceTaskSerializer(page, many=True).data)

    @extend_schema(parameters=[SourceQuerySerializer], responses=inline_serializer(
        name="FinanceSourceProductPage", fields={
            "data": inline_serializer(name="FinanceSourceProductOption", many=True, fields={
                "id": serializers.UUIDField(), "quantity": serializers.CharField(),
                **{name: serializers.CharField() for name in ("item_number_snapshot", "product_number_snapshot",
                    "product_code_snapshot", "product_name_snapshot", "specification_snapshot", "unit_code", "unit_name")},
                "reference_unit_price_cny": serializers.CharField(allow_null=True), "selectable": serializers.BooleanField(),
                **{name: serializers.CharField(allow_null=True) for name in ("reason", "error_code", "occupied_statement_number")},
            }),
            "meta": inline_serializer(name="FinanceSourcePageMeta", fields={
                name: serializers.IntegerField() for name in ("page", "page_size", "total", "total_pages")}),
            "source_revision": serializers.CharField(), "task": SourceTaskSerializer(),
            "salesperson_changes": serializers.ListField(child=serializers.DictField()),
        }))
    @action(detail=True, methods=["get"], url_path="products")
    @transaction.atomic
    def products(self, request, pk=None):
        query = SourceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        # 与生产编辑同锁，在一次响应内给出一致的任务、产品与摘要。
        task = get_object_or_404(ProductionTask.objects.select_for_update(of=("self",)).select_related("salesperson"), pk=pk)
        require_source_task(task)
        editing_id = query.validated_data.get("editing_statement_id")
        if editing_id:
            get_object_or_404(ReceivableStatement, pk=editing_id)
        products = list(source_products(task.pk).select_for_update(of=("self",)))
        revision = source_revision(task, products)
        page = self.paginate_queryset(sorted(products, key=lambda product: (product.line_number, str(product.pk))))
        occupied = occupied_products([product.pk for product in page])
        response = self.get_paginated_response([product_option(product, occupied.get(product.pk), editing_id) for product in page])
        response.data.update(source_revision=revision, task=source_task_data(task), salesperson_changes=salesperson_changes(task, editing_id))
        return response
