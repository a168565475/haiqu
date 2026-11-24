from decimal import Decimal

from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.boms.api.serializers import BomCatalogSelectionSerializer
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee

from ..material_transfers import create_material_transfer, serialize_material_transfer
from ..models import MaterialTransfer
from ..selectors import require_inventory_overview


class MaterialTransferLineInputSerializer(serializers.Serializer):
    material_catalog_id = serializers.UUIDField()
    material_selection = BomCatalogSelectionSerializer()
    zone_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"), required=False)
    raw_bar_count = serializers.IntegerField(min_value=1, max_value=99999999999999, required=False)
    raw_bar_length_m = serializers.DecimalField(max_digits=19, decimal_places=3, min_value=Decimal("0.01"), required=False)
    # 保留旧请求的字段，重试已成功的历史单据时仍能匹配原始提交内容。
    weight_quantity = serializers.DecimalField(max_digits=22, decimal_places=4, min_value=Decimal("0.0001"), required=False,
                                              write_only=True, help_text="仅兼容已提交的历史收发单重试。")


class MaterialTransferInputSerializer(serializers.Serializer):
    client_request_id = serializers.UUIDField()
    direction = serializers.ChoiceField(choices=["IN", "OUT"])
    transfer_date = serializers.DateField()
    remark = serializers.CharField(max_length=3000, allow_blank=False, trim_whitespace=True)
    items = MaterialTransferLineInputSerializer(many=True, allow_empty=False, max_length=100)


class MaterialTransferViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = MaterialTransferInputSerializer
    action_permission_map = {
        "list": "inventory.view_material_receipt",
        "create": "inventory.receive_material",
    }

    def list(self, request):
        require_inventory_overview(request, "inventory.view_material_receipt")
        direction = request.query_params.get("direction", "").strip().upper()
        if direction and direction not in {"IN", "OUT"}:
            raise serializers.ValidationError({"direction": "收发方向无效。"})
        queryset = MaterialTransfer.objects.select_related("operated_by_employee").prefetch_related("lines__zone__warehouse")
        if direction:
            queryset = queryset.filter(direction=direction)
        rows = list(queryset[:500])
        return Response({"data": [serialize_material_transfer(row) for row in rows]})

    def create(self, request):
        serializer = MaterialTransferInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer = create_material_transfer(
            **serializer.validated_data,
            actor_employee=request.employee,
            request=request,
        )
        transfer = MaterialTransfer.objects.select_related("operated_by_employee").prefetch_related("lines__zone__warehouse").get(pk=transfer.pk)
        return Response({"data": serialize_material_transfer(transfer)}, status=status.HTTP_201_CREATED)
