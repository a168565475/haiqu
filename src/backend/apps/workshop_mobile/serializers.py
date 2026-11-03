from rest_framework import serializers

from apps.inventory.api.serializers import WarehouseLocationSerializer
from apps.production_tasks.models import ProductionTaskStatus
from apps.workshop_config.models import PlanCategory


class MobileWorkshopOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MobileWorkshopFilterSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    options = MobileWorkshopOptionSerializer(many=True)
    default_id = serializers.UUIDField(allow_null=True)


class MobileContextSerializer(serializers.Serializer):
    workshop_filter = MobileWorkshopFilterSerializer()


class MobileContextResponseSerializer(serializers.Serializer):
    data = MobileContextSerializer()


class MobilePlanQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, max_length=200)
    plan_category = serializers.ChoiceField(choices=PlanCategory.choices, required=False)
    workshop_id = serializers.UUIDField(required=False)
    production_task_id = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=["ALL", *ProductionTaskStatus.values], required=False, default="ALL")
    production_date = serializers.DateField(required=False)
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)


class MobilePlanDetailQuerySerializer(MobilePlanQuerySerializer):
    plan_category = serializers.ChoiceField(choices=PlanCategory.choices)
    workshop_id = serializers.UUIDField()


class MobileFinishedReceiptQuerySerializer(serializers.Serializer):
    schedule_product_id = serializers.UUIDField()


class MobileFinishedReceiptLocationSerializer(WarehouseLocationSerializer):
    class Meta(WarehouseLocationSerializer.Meta):
        fields = ['id', 'zone', 'warehouse_id', 'location_number', 'status', 'remaining_box_slots']


class MobileFinishedReceiptWarehouseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    warehouse_number = serializers.CharField()
    warehouse_name = serializers.CharField()
    warehouse_type = serializers.CharField()
    status = serializers.CharField()


class MobileFinishedReceiptZoneSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    warehouse = serializers.UUIDField()
    zone_name = serializers.CharField()
    status = serializers.CharField()


class MobileFinishedReceiptOptionsSerializer(serializers.Serializer):
    warehouses = MobileFinishedReceiptWarehouseSerializer(many=True)
    zones = MobileFinishedReceiptZoneSerializer(many=True)
    locations = MobileFinishedReceiptLocationSerializer(many=True)


class MobileFinishedReceiptOptionsResponseSerializer(serializers.Serializer):
    data = MobileFinishedReceiptOptionsSerializer()
