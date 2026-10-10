from rest_framework import serializers


class SampleMaterialIssueInitiateSerializer(serializers.Serializer):
    client_request_id = serializers.UUIDField(required=False, allow_null=True)
    note = serializers.CharField(max_length=2000, allow_blank=True, required=False, default="")


class SampleMaterialIssueLineConfirmSerializer(serializers.Serializer):
    line_id = serializers.UUIDField()
    issued_quantity = serializers.CharField(max_length=30)


class SampleMaterialIssueConfirmSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    lines = SampleMaterialIssueLineConfirmSerializer(many=True, allow_empty=False, max_length=500)

    def validate(self, attrs):
        ids = [str(row["line_id"]) for row in attrs["lines"]]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("领料明细不能重复。")
        return attrs
