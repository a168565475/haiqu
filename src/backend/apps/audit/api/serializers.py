from rest_framework import serializers

from apps.core.serializers import EmployeeSummarySerializer

from ..models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor = EmployeeSummarySerializer(source="actor_employee", read_only=True, allow_null=True)

    class Meta:
        model = AuditLog
        fields = [
            "id", "actor", "actor_employee_code_snapshot", "actor_name_snapshot", "object_type",
            "object_id", "context_type", "context_id", "action", "before_data", "after_data",
            "request_id", "ip_address", "user_agent", "occurred_at",
        ]
