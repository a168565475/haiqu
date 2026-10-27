from rest_framework import serializers
from drf_spectacular.utils import extend_schema_serializer

from ..processing_selectors import MAX_PIECES


class ProcessingWriteSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["存在不允许提交的字段；支根米来源及累计量由系统确定。"]})
        return super().to_internal_value(data)


class WholePiecesField(serializers.IntegerField):
    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, (int, str)) or not str(data).isascii() or not str(data).isdigit():
            raise serializers.ValidationError("合格支数必须为正整数。")
        return super().to_internal_value(data)


class ProcessingCompletionWriteSerializer(ProcessingWriteSerializer):
    good_pieces = WholePiecesField(min_value=1, max_value=MAX_PIECES)
    completion_date = serializers.DateField()


class ProcessingClosureWriteSerializer(ProcessingWriteSerializer):
    remark = serializers.CharField(max_length=1000, allow_blank=False, trim_whitespace=True)


class ProcessingSourceFilterSerializer(serializers.Serializer):
    production_task_id = serializers.UUIDField(required=False)
    product_line_id = serializers.UUIDField(required=False)
    component_identity = serializers.UUIDField(required=False)
    issue_id = serializers.UUIDField(required=False)
    original_order_id = serializers.UUIDField(required=False)
    source_id = serializers.UUIDField(required=False)
    issue_number = serializers.CharField(required=False, max_length=100)
    status = serializers.ChoiceField(choices=["OPEN", "CLOSED"], required=False)


class ProcessingSourceReadSerializer(serializers.Serializer):
    issue_line_id = serializers.UUIDField()
    source_id = serializers.UUIDField(allow_null=True)
    issue_number = serializers.CharField()
    production_task_id = serializers.UUIDField()
    product_line_id = serializers.UUIDField()
    component_identity = serializers.UUIDField(allow_null=True)
    part_name = serializers.CharField()
    unit = serializers.CharField()
    issued_pieces = serializers.IntegerField(required=False)
    completed_pieces = serializers.IntegerField(required=False)
    reserved_pieces = serializers.IntegerField(required=False)
    dispatched_pieces = serializers.IntegerField(required=False)
    unfinished_pieces = serializers.IntegerField(required=False)
    unallocated_pieces = serializers.IntegerField(required=False)
    available_pieces = serializers.IntegerField(required=False)
    remaining_completion_pieces = serializers.IntegerField(required=False)
    status = serializers.ChoiceField(choices=["OPEN", "CLOSED"], required=False)
    version = serializers.IntegerField(required=False)
    bar_count = serializers.IntegerField(required=False)
    meters = serializers.DecimalField(max_digits=22, decimal_places=2, required=False)
    can_register = serializers.BooleanField()
    can_close = serializers.BooleanField()
    blockers = serializers.JSONField()
    etag = serializers.CharField(allow_null=True)
    source_snapshot = serializers.JSONField(required=False)
    completions = serializers.ListField(child=serializers.JSONField(), required=False)
    closure = serializers.JSONField(allow_null=True, required=False)
    operation_id = serializers.UUIDField(required=False)
    original_handoffs = serializers.ListField(child=serializers.JSONField(), required=False)
    can_handoff = serializers.BooleanField(required=False)
    original_handoff_order_ids = serializers.ListField(child=serializers.UUIDField(), required=False)


class ProcessingSourceResponseSerializer(serializers.Serializer):
    data = ProcessingSourceReadSerializer()


class ProcessingErrorResponseSerializer(serializers.Serializer):
    error = serializers.JSONField(help_text="包含 code、message、field_errors 和 request_id。")


class ProcessingPageMetaSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()
    total_pages = serializers.IntegerField()


@extend_schema_serializer(many=False)
class ProcessingSourceListResponseSerializer(serializers.Serializer):
    data = ProcessingSourceReadSerializer(many=True)
    meta = ProcessingPageMetaSerializer()
