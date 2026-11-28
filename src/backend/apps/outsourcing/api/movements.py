from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.views import APIView

from apps.core.api.pagination import StandardPageNumberPagination
from apps.core.api.permissions import HasActiveEmployee

from ..movements import TRACKED_CRAFTS, movement_rows


class OutsourcingMovementQuery(serializers.Serializer):
    task_number = serializers.CharField(max_length=50, allow_blank=True, default="")
    direction = serializers.ChoiceField(choices=("dispatch", "receipt"), default="dispatch")
    process = serializers.ChoiceField(choices=TRACKED_CRAFTS, allow_blank=True, default="")
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)


class OutsourcingMovementRow(serializers.Serializer):
    id = serializers.CharField()
    task_number = serializers.CharField()
    business_date = serializers.DateField()
    process = serializers.ChoiceField(choices=TRACKED_CRAFTS)
    factory_name = serializers.CharField()
    item_name = serializers.CharField()
    quantity = serializers.CharField()
    unit = serializers.CharField()
    voucher_number = serializers.CharField()
    direct_transfer = serializers.BooleanField()


class OutsourcingMovementPage(serializers.Serializer):
    data = OutsourcingMovementRow(many=True)
    meta = serializers.DictField(child=serializers.IntegerField())


class OutsourcingMovementsView(APIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(parameters=[OutsourcingMovementQuery], responses=OutsourcingMovementPage)
    def get(self, request):
        query = OutsourcingMovementQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        rows = movement_rows(request, task_number=filters["task_number"],
                             direction=filters["direction"], process=filters["process"])
        paginator = StandardPageNumberPagination()
        page = paginator.paginate_queryset(rows, request)
        return paginator.get_paginated_response(OutsourcingMovementRow(page, many=True).data)
