from rest_framework import serializers


class SampleMaterialIssueInitiateSerializer(serializers.Serializer):
    client_request_id = serializers.UUIDField(required=False, allow_null=True)
    note = serializers.CharField(max_length=2000, allow_blank=True, required=False, default="")


class SampleMaterialIssueConfirmSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()

    def validate(self, attrs):
        if set(self.initial_data) - {"request_id"}:
            raise serializers.ValidationError("样品领料按本次安排的材料全部领走，不再填写领料明细或数量。")
        return attrs
