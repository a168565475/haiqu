from decimal import Decimal

from rest_framework import serializers


class P4WholePiecesField(serializers.IntegerField):
    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, (int, str)) or not str(data).isascii() or not str(data).isdigit():
            raise serializers.ValidationError("支数必须为正整数。")
        return super().to_internal_value(data)


class P4WriteSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["存在不允许提交的字段；库存和历史数量由系统确定。"]})
        return super().to_internal_value(data)


class P4OriginalHandoffWriteSerializer(P4WriteSerializer):
    original_order_id = serializers.UUIDField()
    factory_id = serializers.UUIDField()
    handoff_pieces = P4WholePiecesField(min_value=1)
    handoff_date = serializers.DateField()


class P4UnsprayedReturnWriteSerializer(P4WriteSerializer):
    returned_pieces = P4WholePiecesField(min_value=1)
    received_by_employee_id = serializers.UUIDField()
    storage_location = serializers.CharField(max_length=200, trim_whitespace=True)
    return_date = serializers.DateField()
    remark = serializers.CharField(max_length=1000, allow_blank=True, required=False, default="", trim_whitespace=True)


class P4ReworkWriteSerializer(P4WriteSerializer):
    completed_pieces = P4WholePiecesField(min_value=1)
    completion_date = serializers.DateField()


class P4ExternalOrderWriteSerializer(P4WriteSerializer):
    factory_id = serializers.UUIDField()
    craft_id = serializers.UUIDField()
    allocated_pieces = P4WholePiecesField(min_value=1)


class P4AllocationWriteSerializer(P4WriteSerializer):
    allocated_pieces = P4WholePiecesField(min_value=1, max_value=99_999_999_999_999)


class P4ExternalHandoffWriteSerializer(P4WriteSerializer):
    handoff_pieces = P4WholePiecesField(min_value=1)
    handoff_date = serializers.DateField()


class P4GoodReturnWriteSerializer(P4WriteSerializer):
    good_pieces = P4WholePiecesField(min_value=1)
    zone_id = serializers.UUIDField()
    received_by_employee_id = serializers.UUIDField()
    return_date = serializers.DateField()
    remark = serializers.CharField(max_length=1000, allow_blank=True, required=False, default="", trim_whitespace=True)


class P4ClosureWriteSerializer(P4WriteSerializer):
    remark = serializers.CharField(max_length=1000, allow_blank=False, trim_whitespace=True)


class P4CancelPendingWriteSerializer(P4ClosureWriteSerializer):
    allocation_id = serializers.UUIDField()


class P4SourceResponseSerializer(serializers.Serializer):
    data = serializers.JSONField()


class P4RecordResponseSerializer(serializers.Serializer):
    data = serializers.JSONField()


class P4OrderResponseSerializer(serializers.Serializer):
    data = serializers.JSONField()
