import json
from decimal import Decimal

from rest_framework import serializers

from ..nesting_models import BomNestingJob


class NestingTargetSerializer(serializers.Serializer):
    line_id = serializers.UUIDField(required=False, allow_null=True)
    draft_key = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if bool(attrs.get("line_id")) == bool(attrs.get("draft_key")):
            raise serializers.ValidationError("请指定一条已保存面料行或一个新增行临时标识。")
        return attrs


class NestingUploadSerializer(NestingTargetSerializer):
    file = serializers.FileField(allow_empty_file=False)
    source_unit = serializers.ChoiceField(choices=["auto", "mm", "cm", "m", "inch"], default="auto")
    target_snapshot = serializers.JSONField()

    def validate_target_snapshot(self, value):
        try:
            valid_size = isinstance(value, dict) and len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) <= 4096
        except (ValueError, TypeError, RecursionError):
            valid_size = False
        if not valid_size:
            raise serializers.ValidationError("面料身份快照必须是最多 4 KiB 的对象。")
        if value.get("unit") != "米":
            raise serializers.ValidationError("仅支持单位为米的面料行。")
        if value.get("category_key", "FABRIC") != "FABRIC" or value.get("processing_state", "RAW") != "RAW":
            raise serializers.ValidationError("只能对原料面料排料，不能把裁片半成品作为来源。")
        return value


class NestingPieceInputSerializer(serializers.Serializer):
    piece_id = serializers.CharField(max_length=100)
    quantity = serializers.IntegerField(min_value=1, max_value=160)
    rotation_mode = serializers.ChoiceField(choices=["fixed", "half_turn", "quarter_turn", "free"])
    name = serializers.CharField(max_length=80, required=False, allow_blank=False)


class NestingParametersSerializer(serializers.Serializer):
    width_mm = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal("0.001"), max_value=Decimal("100000"))
    gap_mm = serializers.DecimalField(max_digits=8, decimal_places=3, min_value=Decimal("0"), max_value=Decimal("1000"))
    set_count = serializers.IntegerField(min_value=1, max_value=160)
    products_per_set = serializers.IntegerField(min_value=1, max_value=1000000)
    pieces = NestingPieceInputSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        pieces = attrs["pieces"]
        ids = [piece["piece_id"] for piece in pieces]
        if len(ids) > 160 or len(set(ids)) != len(ids):
            raise serializers.ValidationError("裁片编号不能重复，种类不能超过 160。")
        if sum(piece["quantity"] for piece in pieces) * attrs["set_count"] > 160:
            raise serializers.ValidationError("混排总片数不能超过 160。")
        return attrs


class BomNestingJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = BomNestingJob
        fields = ["id", "bom_id", "line_id", "draft_key", "target_snapshot", "status", "phase", "original_name",
                  "source_unit", "analysis", "analysis_digest", "execution", "artifacts", "parameters", "result", "optimization", "error_code", "error_message", "created_at", "updated_at"]
        read_only_fields = fields


class BomNestingResponseSerializer(serializers.Serializer):
    data = BomNestingJobSerializer()


class BomNestingListResponseSerializer(serializers.Serializer):
    data = BomNestingJobSerializer(many=True)
