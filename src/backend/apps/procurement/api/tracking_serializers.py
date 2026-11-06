from rest_framework import serializers

from ..tracking_rules import RISK_DEFINITIONS


class TrackingFilterSerializer(serializers.Serializer):
    production_task_id = serializers.UUIDField(required=False)
    risk = serializers.ChoiceField(choices=list(RISK_DEFINITIONS), required=False)
    include_history = serializers.BooleanField(default=False)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)
    row_key = serializers.CharField(max_length=200, required=False, allow_blank=False)

    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: '不支持的筛选参数。' for key in sorted(unknown)})
        if hasattr(data, 'getlist'):
            repeated = [key for key in data if len(data.getlist(key)) > 1]
            if repeated:
                raise serializers.ValidationError({key: '筛选参数不能重复。' for key in repeated})
        return super().to_internal_value(data)


class TrackingRiskSerializer(serializers.Serializer):
    code = serializers.ChoiceField(choices=list(RISK_DEFINITIONS))
    label = serializers.CharField()
    level = serializers.ChoiceField(choices=['danger', 'warning', 'info', 'success'])
    rank = serializers.IntegerField()


class TrackingActionSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['view_order', 'view_return', 'create_group', 'create_batch', 'view_group', 'view_bom'])
    label = serializers.CharField()
    path = serializers.CharField()


class TrackingRowSerializer(serializers.Serializer):
    row_key = serializers.CharField()
    production_task_id = serializers.UUIDField()
    task_number = serializers.CharField()
    product_line_id = serializers.UUIDField(allow_null=True)
    product_name = serializers.CharField(allow_blank=True)
    material_name = serializers.CharField(allow_blank=True)
    specification = serializers.CharField(allow_blank=True)
    unit = serializers.CharField(allow_null=True)
    purchase_group_id = serializers.UUIDField(allow_null=True)
    source_bom_line_id = serializers.UUIDField(allow_null=True)
    source_reliable = serializers.BooleanField()
    verification_notes = serializers.ListField(child=serializers.CharField())
    is_history = serializers.BooleanField()
    risks = TrackingRiskSerializer(many=True)
    actions = TrackingActionSerializer(many=True)
    action_blocked_reason = serializers.CharField(allow_blank=True)
    evaluated_at = serializers.DateTimeField()


class ArrivalTrackingRowSerializer(TrackingRowSerializer):
    material_selection_snapshot = serializers.JSONField()
    material_attributes_snapshot = serializers.JSONField()
    part_name = serializers.CharField(allow_blank=True)
    material = serializers.CharField(allow_blank=True)
    raw_material = serializers.CharField(allow_blank=True)
    purchase_order_id = serializers.UUIDField()
    purchase_order_line_id = serializers.UUIDField()
    purchase_order_no = serializers.CharField()
    batch_number = serializers.IntegerField(allow_null=True)
    publication_status = serializers.CharField()
    supplier_name = serializers.CharField(allow_blank=True)
    ordered_quantity = serializers.CharField(allow_null=True)
    received_quantity = serializers.CharField(allow_null=True)
    accepted_quantity = serializers.CharField(allow_null=True)
    pending_quality_quantity = serializers.CharField(allow_null=True)
    unreceived_quantity = serializers.CharField(allow_null=True)
    return_quantity = serializers.CharField(allow_null=True)
    return_pending = serializers.BooleanField()
    delivery_date = serializers.DateField(allow_null=True)
    days_remaining = serializers.IntegerField(allow_null=True)
    ordered_root_count = serializers.CharField(allow_null=True)
    received_root_count = serializers.CharField(allow_null=True)
    unreceived_root_count = serializers.CharField(allow_null=True)
    root_count_note = serializers.CharField(allow_blank=True)


class CoverageTrackingRowSerializer(TrackingRowSerializer):
    bom_created_at = serializers.DateTimeField(allow_null=True)
    bom_confirmed_at = serializers.DateTimeField(allow_null=True)
    bom_purchase_due_at = serializers.DateTimeField(allow_null=True)
    latest_purchase_date = serializers.DateField(allow_null=True)
    purchase_days_remaining = serializers.IntegerField(allow_null=True)
    material_category_key = serializers.CharField(allow_null=True)
    order_delivery_date = serializers.DateField(allow_null=True)
    material_selection_snapshot = serializers.JSONField()
    material_attributes_snapshot = serializers.JSONField()
    part_name = serializers.CharField(allow_blank=True)
    material = serializers.CharField(allow_blank=True)
    raw_material = serializers.CharField(allow_blank=True)
    required_quantity = serializers.CharField(allow_null=True)
    purchased_quantity = serializers.CharField(allow_null=True)
    remaining_quantity = serializers.CharField(allow_null=True)
    scheduled = serializers.BooleanField()
    material_inbound_date = serializers.DateField(allow_null=True)
    group_status = serializers.CharField()
    required_root_count = serializers.CharField(allow_null=True)
    purchased_root_count = serializers.CharField(allow_null=True)
    remaining_root_count = serializers.CharField(allow_null=True)
    root_count_note = serializers.CharField(allow_blank=True)


class TrackingPaginationSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    total_pages = serializers.IntegerField()


class ArrivalTrackingResponseSerializer(serializers.Serializer):
    data = ArrivalTrackingRowSerializer(many=True)
    meta = TrackingPaginationSerializer()


class CoverageTrackingResponseSerializer(serializers.Serializer):
    data = CoverageTrackingRowSerializer(many=True)
    meta = TrackingPaginationSerializer()
