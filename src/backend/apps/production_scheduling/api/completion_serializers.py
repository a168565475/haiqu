from rest_framework import serializers


class ScheduleCompleteSerializer(serializers.Serializer):
    task_etag = serializers.CharField(max_length=100)
    reason = serializers.CharField(max_length=500)
    sales_order_etag = serializers.CharField(max_length=100, required=False)

    def validate(self, attrs):
        # 此入口只改变完成状态，不接受覆盖实际数量或重建生产批次。
        unsupported = set(self.initial_data) - set(self.fields)
        if unsupported:
            raise serializers.ValidationError({key: "完成排产不接受此字段。" for key in unsupported})
        return attrs


class ScheduleSalesSyncSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["COMPLETED", "SKIPPED", "NOT_APPLICABLE", "ALREADY_COMPLETED"])
    reason = serializers.CharField()
    before_status = serializers.CharField(allow_null=True)
    after_status = serializers.CharField(allow_null=True)


class ScheduleProductionSyncSerializer(serializers.Serializer):
    before_status = serializers.CharField()
    after_status = serializers.CharField()


class ScheduleCompleteResultSerializer(serializers.Serializer):
    schedule_id = serializers.UUIDField()
    production_task_id = serializers.UUIDField()
    production_task_status = serializers.CharField()
    progress = serializers.DictField(child=serializers.DictField())
    production_sync = ScheduleProductionSyncSerializer()
    sales_sync = ScheduleSalesSyncSerializer()


class ScheduleCompleteResponseSerializer(serializers.Serializer):
    data = ScheduleCompleteResultSerializer()


class ScheduleCompletionTaskSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    task_number = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    etag = serializers.CharField()


class ScheduleCompletionProductSerializer(serializers.Serializer):
    schedule_product_id = serializers.UUIDField()
    product_name = serializers.CharField()
    specification = serializers.CharField(allow_blank=True)
    color = serializers.CharField(allow_blank=True)
    material = serializers.CharField(allow_blank=True)
    required_quantity = serializers.IntegerField()
    received_quantity = serializers.IntegerField()
    unit_name = serializers.CharField()


class ScheduleCompletionSalesOrderSerializer(serializers.Serializer):
    id = serializers.UUIDField(allow_null=True)
    order_number = serializers.CharField(allow_null=True)
    status = serializers.CharField(allow_null=True)
    status_display = serializers.CharField(allow_null=True)
    etag = serializers.CharField(allow_null=True)
    can_sync = serializers.BooleanField()
    reason = serializers.CharField()


class ScheduleCompletionPreviewSerializer(serializers.Serializer):
    schedule_id = serializers.UUIDField()
    schedule_number = serializers.CharField()
    schedule_etag = serializers.CharField()
    task = ScheduleCompletionTaskSerializer()
    progress = serializers.DictField(child=serializers.DictField())
    products = ScheduleCompletionProductSerializer(many=True)
    sales_order = ScheduleCompletionSalesOrderSerializer()


class ScheduleCompletionPreviewResponseSerializer(serializers.Serializer):
    data = ScheduleCompletionPreviewSerializer()
