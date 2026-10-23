from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.permissions import HasActiveEmployee
from ..employee_batch_services import adjust_employees
from ..permissions import CanReadAccessDirectory
from .serializers import StrictSerializer


class EmployeeBatchItemSerializer(StrictSerializer):
    id = serializers.UUIDField()
    etag = serializers.CharField(max_length=100)


class EmployeeBatchAdjustmentSerializer(StrictSerializer):
    items = EmployeeBatchItemSerializer(many=True, allow_empty=False, max_length=500)
    department_ids = serializers.ListField(child=serializers.UUIDField(), max_length=100,
                                          help_text="完整替换当前部门，空列表清空全部部门。")
    role_ids = serializers.ListField(child=serializers.UUIDField(), max_length=100,
                                    help_text="完整替换当前角色，空列表清空全部角色；角色必须属于本次所选部门。")

    def validate(self, attrs):
        ids = [item["id"] for item in attrs["items"]]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError({"items": "员工不可重复。"})
        departments = attrs.get("department_ids", [])
        if len(departments) != len(set(departments)):
            raise serializers.ValidationError({"department_ids": "部门不可重复。"})
        roles = attrs.get("role_ids", [])
        if len(roles) != len(set(roles)):
            raise serializers.ValidationError({"role_ids": "角色不可重复。"})
        return attrs


class EmployeeBatchAdjustmentResponseSerializer(serializers.Serializer):
    updated_count = serializers.IntegerField()


class EmployeeBatchActions:
    @extend_schema(request=EmployeeBatchAdjustmentSerializer, responses=EmployeeBatchAdjustmentResponseSerializer)
    @action(detail=False, methods=["post"], url_path="adjust-selected",
            permission_classes=[IsAuthenticated, HasActiveEmployee, CanReadAccessDirectory])
    def adjust_selected(self, request):
        serializer = EmployeeBatchAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(adjust_employees(request, serializer.validated_data))
