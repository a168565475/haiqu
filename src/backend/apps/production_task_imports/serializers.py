from rest_framework import serializers

from apps.codex_connection.serializers import StrictSerializer


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    client_request_id = serializers.UUIDField()


class SelectionSerializer(StrictSerializer):
    object_id = serializers.RegexField(r'^[0-9a-f]{64}$')


class ReviewSerializer(StrictSerializer):
    review = serializers.JSONField()


class ImportReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    state = serializers.CharField()
    phase = serializers.CharField()
    original_name = serializers.CharField()
    scan_status = serializers.CharField()
    expires_at = serializers.DateTimeField()
    attempt_no = serializers.IntegerField()
    result_revision = serializers.IntegerField()
    candidates = serializers.JSONField()
    selected_candidate = serializers.JSONField()
    extraction = serializers.JSONField()
    matching = serializers.JSONField()
    review = serializers.JSONField()
    issues = serializers.JSONField()
    error_code = serializers.CharField()
    blocked_reason = serializers.CharField()
    saved_task_id = serializers.UUIDField(allow_null=True)
    saved_task_number = serializers.CharField()
    saved_at = serializers.DateTimeField(allow_null=True)
    duplicates = serializers.JSONField()


class ImportResponseSerializer(serializers.Serializer):
    data = ImportReadSerializer()
