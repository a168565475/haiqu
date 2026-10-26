from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from ..cost_models import ProductionTaskExpense
from ..cost_services import create_task_expense, update_task_expense, void_task_expense
from .cost_serializers import (
    ProductionTaskExpenseListResponseSerializer,
    ProductionTaskExpensePatchSerializer,
    ProductionTaskExpenseReadSerializer,
    ProductionTaskExpenseResponseSerializer,
    ProductionTaskExpenseWriteSerializer,
)


class ProductionTaskCostMixin:
    @extend_schema(responses={200: dict})
    @action(detail=True, methods=['get'], url_path='cost-summary')
    def cost_summary(self, request, *args, **kwargs):
        from ..cost_selectors import task_cost_summary
        return Response({'data': task_cost_summary(task=self.get_object())})

    @extend_schema(methods=['GET'], responses={200: ProductionTaskExpenseListResponseSerializer})
    @extend_schema(methods=['POST'], request=ProductionTaskExpenseWriteSerializer,
                   responses={200: ProductionTaskExpenseResponseSerializer, 201: ProductionTaskExpenseResponseSerializer})
    @action(detail=True, methods=['get', 'post'], url_path='cost-expenses')
    def cost_expenses(self, request, *args, **kwargs):
        task = self.get_object()
        if request.method == 'GET':
            rows = ProductionTaskExpense.objects.filter(production_task=task, voided_at__isnull=True)
            return Response({'data': ProductionTaskExpenseReadSerializer(rows, many=True).data})
        serializer = ProductionTaskExpenseWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expense, created = create_task_expense(task=task, validated_data=serializer.validated_data, actor_employee=request.employee, request=request)
        return Response({'data': ProductionTaskExpenseReadSerializer(expense).data}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @extend_schema(methods=['PATCH'], request=ProductionTaskExpensePatchSerializer,
                   responses={200: ProductionTaskExpenseResponseSerializer})
    @extend_schema(methods=['DELETE'], request=None, responses={204: None})
    @action(detail=True, methods=['patch', 'delete'], url_path=r'cost-expenses/(?P<expense_id>[^/.]+)')
    def cost_expense(self, request, *args, expense_id=None, **kwargs):
        task = self.get_object()
        try:
            expense_id = UUID(str(expense_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError({'expense_id': '费用编号必须是有效 UUID。'}) from exc
        arguments = dict(task=task, expense_id=expense_id, actor_employee=request.employee, request=request)
        if request.method == 'DELETE':
            void_task_expense(**arguments)
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = ProductionTaskExpensePatchSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        expense = update_task_expense(**arguments, validated_data=serializer.validated_data)
        return Response({'data': ProductionTaskExpenseReadSerializer(expense).data})
