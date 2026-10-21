from rest_framework import serializers


class InternalPlanSummarySerializer(serializers.Serializer):
    category = serializers.CharField()
    craft_id = serializers.UUIDField()
    craft_name = serializers.CharField()
    workshop_id = serializers.UUIDField(allow_null=True)
    workshop_name = serializers.CharField(allow_blank=True)
    plan_date = serializers.DateField(allow_null=True)
    milestone = serializers.CharField()
    planned_quantity = serializers.CharField()
    unit_name = serializers.CharField(allow_blank=True)
    estimated_wage = serializers.CharField(allow_null=True)
    reported_amount = serializers.CharField(allow_null=True)
    estimated_amount_status = serializers.CharField()
    reported_amount_status = serializers.CharField()
    progress_percent = serializers.FloatField(allow_null=True)
    plan_status = serializers.CharField(allow_null=True)
    plan_status_display = serializers.CharField(allow_blank=True)
    wage_status = serializers.CharField()
    reason = serializers.CharField(allow_blank=True)
    scheme_id = serializers.UUIDField(allow_null=True)
    can_view_wage = serializers.BooleanField()
    can_view_reports = serializers.BooleanField()


class OutsourcingSummaryRecordSerializer(serializers.Serializer):
    id = serializers.CharField()
    order_id = serializers.UUIDField()
    order_kind = serializers.CharField()
    order_number = serializers.CharField()
    craft_name = serializers.CharField()
    part_name = serializers.CharField(allow_blank=True)
    factory_name = serializers.CharField(allow_blank=True)
    planned_quantity = serializers.CharField(allow_null=True)
    quantity_unit = serializers.CharField(allow_blank=True)
    dispatched_quantity = serializers.CharField(allow_null=True)
    dispatched_unit = serializers.CharField(allow_null=True, allow_blank=True)
    received_quantity = serializers.CharField(allow_null=True)
    received_unit = serializers.CharField(allow_blank=True)
    shortage_quantity = serializers.CharField(allow_null=True)
    unit_price = serializers.CharField(allow_null=True)
    price_unit = serializers.CharField(allow_blank=True)
    planned_amount = serializers.CharField(allow_null=True)
    expected_return_date = serializers.DateField(allow_null=True)
    status = serializers.CharField()
    status_display = serializers.CharField()
    detail_access = serializers.CharField()
    reason = serializers.CharField(allow_blank=True)


class OutsourcingSummarySerializer(serializers.Serializer):
    allowed = serializers.BooleanField()
    records = OutsourcingSummaryRecordSerializer(many=True)
    planned_amount = serializers.CharField(allow_null=True)


class MaterialIssueSummaryRecordSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    issue_number = serializers.CharField()
    workshop_name = serializers.CharField(allow_blank=True)
    recipient_name = serializers.CharField(allow_blank=True)
    line_count = serializers.IntegerField()
    issue_at = serializers.DateTimeField(allow_null=True)
    issued_at = serializers.DateTimeField(allow_null=True)
    status = serializers.CharField()
    status_display = serializers.CharField()


class MaterialIssueSummarySerializer(serializers.Serializer):
    allowed = serializers.BooleanField()
    records = MaterialIssueSummaryRecordSerializer(many=True)


class ScheduleProductSummarySerializer(serializers.Serializer):
    schedule_product_id = serializers.UUIDField()
    internal_plans = InternalPlanSummarySerializer(many=True)
    estimated_wage = serializers.CharField(allow_null=True)
    reported_amount = serializers.CharField(allow_null=True)
    estimated_amount_status = serializers.CharField()
    reported_amount_status = serializers.CharField()
    outsourcing = OutsourcingSummarySerializer()
    material_issues = MaterialIssueSummarySerializer()


class ScheduleSummaryTotalsSerializer(serializers.Serializer):
    estimated_wage = serializers.CharField(allow_null=True)
    reported_amount = serializers.CharField(allow_null=True)
    outsourcing_planned_amount = serializers.CharField(allow_null=True)
    complete_scope = serializers.BooleanField()
    reason = serializers.CharField(allow_blank=True)


class ScheduleDetailSummarySerializer(serializers.Serializer):
    schedule_id = serializers.UUIDField()
    products = ScheduleProductSummarySerializer(many=True)
    totals = ScheduleSummaryTotalsSerializer()


class ScheduleDetailSummaryResponseSerializer(serializers.Serializer):
    data = ScheduleDetailSummarySerializer()
