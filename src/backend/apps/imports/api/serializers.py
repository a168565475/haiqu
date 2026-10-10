from rest_framework import serializers

from ..models import ImportBatch, ImportRecord


class ContactImportUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    customer_id = serializers.UUIDField(required=False)
    allow_same_customer_duplicates = serializers.BooleanField(required=False, default=False)


class ImportRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportRecord
        fields = [
            "id", "row_number", "status", "raw_data", "warning_messages", "error_message",
            "target_type", "target_id", "created_at", "updated_at",
        ]


class ContactImportBatchSerializer(serializers.ModelSerializer):
    source_file = serializers.SerializerMethodField()

    class Meta:
        model = ImportBatch
        fields = [
            "id", "import_type", "status", "total_count", "success_count", "failure_count",
            "started_at", "finished_at", "config_data", "error_summary", "source_file",
            "created_at", "updated_at",
        ]

    def get_source_file(self, obj) -> dict:
        return {
            "id": str(obj.source_file_id),
            "original_name": obj.source_file.original_name,
            "size_bytes": obj.source_file.size_bytes,
            "scan_status": obj.source_file.scan_status,
        }
