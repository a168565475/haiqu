import json
import uuid

from rest_framework import serializers


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    client_request_id = serializers.UUIDField(required=False, default=uuid.uuid4)

    def validate_file(self, value):
        if value.size <= 0:
            raise serializers.ValidationError("上传文件不能为空。")
        return value


class TaskDraftWriteSerializer(serializers.Serializer):
    payload = serializers.JSONField()
    task_key = serializers.CharField(required=False, max_length=100)

    def validate_payload(self, value):
        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError("生产任务草稿必须是 JSON 对象。")
        return value


class BomDraftWriteSerializer(serializers.Serializer):
    plans = serializers.ListField(child=serializers.DictField(), allow_empty=False, max_length=100)
    task_key = serializers.CharField(required=False, max_length=100)


class TaskSelectionSerializer(serializers.Serializer):
    task_key = serializers.CharField(max_length=100)


class ReviewDraftSerializer(serializers.Serializer):
    task_payload = serializers.JSONField(allow_null=True)
    bom_plans = serializers.ListField(child=serializers.DictField(), allow_empty=True, max_length=100, allow_null=True)
    task_key = serializers.CharField(required=False, max_length=100)

    def validate_task_payload(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("任务表单必须是对象。")
        return value

    def validate(self, attrs):
        if len(json.dumps(attrs, ensure_ascii=False).encode("utf-8")) > 2 * 1024 * 1024:
            raise serializers.ValidationError("核对表单内容过大，请缩短附加说明后保存。")
        return attrs


class RecordListQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(default=20, min_value=1, max_value=100)
    offset = serializers.IntegerField(default=0, min_value=0)


class RecordSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    original_name = serializers.CharField()
    state = serializers.SerializerMethodField()
    task_number = serializers.CharField(allow_blank=True)
    task_id = serializers.UUIDField(allow_null=True)
    bom_ids = serializers.ListField(child=serializers.UUIDField())
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_state(self, obj) -> str:
        return "RECOGNIZING" if getattr(obj, "is_recognizing", False) else obj.state


class RecordListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = RecordSummarySerializer(many=True)


class ReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    state = serializers.CharField()
    phase = serializers.CharField()
    progress = serializers.JSONField()
    original_name = serializers.CharField()
    sha256 = serializers.CharField()
    size_bytes = serializers.IntegerField()
    model = serializers.CharField(allow_blank=True)
    result = serializers.JSONField()
    active_task_key = serializers.CharField(required=False)
    task_choices = serializers.JSONField(required=False)
    has_created_tasks = serializers.BooleanField(required=False)
    has_previous_recognition = serializers.BooleanField(required=False)
    issues = serializers.JSONField()
    error_code = serializers.CharField(allow_blank=True)
    task_draft = serializers.JSONField()
    bom_draft = serializers.JSONField()
    review_draft = ReviewDraftSerializer(allow_null=True)
    task_id = serializers.UUIDField(allow_null=True, required=False)
    task_number = serializers.CharField(required=False, allow_blank=True)
    task_status = serializers.CharField(required=False, allow_blank=True)
    task_products = serializers.JSONField(required=False)
    bom_id = serializers.UUIDField(allow_null=True, required=False)
    bom_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    source_summary = serializers.JSONField()
    sources = serializers.JSONField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
