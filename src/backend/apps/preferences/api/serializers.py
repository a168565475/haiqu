from rest_framework import serializers

from ..models import SavedView


MODULE_FIELDS = {
    "CUSTOMER": {"q", "lifecycle_stage", "primary_country_code", "owner_employee_id", "attention_level", "archived"},
    "INQUIRY": {"q", "status", "owner_employee_id", "customer_id", "received_from", "received_to", "overdue"},
    "QUOTATION": {"q", "outcome_status", "owner_employee_id", "customer_id", "created_from", "created_to"},
    "SAMPLE_REQUEST": {"q", "status", "owner_employee_id", "customer_id", "requested_from", "requested_to", "overdue"},
    "TASK": {"q", "status", "priority", "assignee_employee_id", "due_from", "due_to", "overdue"},
    "AUDIT_LOG": {"object_type", "action", "actor_employee_id", "occurred_from", "occurred_to"},
}


class SavedViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedView
        fields = [
            "id", "module_code", "view_name", "filter_definition", "column_definition",
            "sort_definition", "is_default", "sort_order", "archived_at", "archive_reason",
            "created_at", "updated_at",
        ]
        read_only_fields = ["is_default", "archived_at", "archive_reason"]

    def validate_module_code(self, value):
        value = value.upper()
        if value not in MODULE_FIELDS:
            raise serializers.ValidationError("不支持该模块的保存视图。")
        return value

    def validate_filter_definition(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("筛选定义必须是对象。")
        module = (self.initial_data.get("module_code") or getattr(self.instance, "module_code", "")).upper()
        allowed = MODULE_FIELDS.get(module, set())
        invalid = set(value) - allowed
        if invalid:
            raise serializers.ValidationError(f"包含不允许的筛选字段：{', '.join(sorted(invalid))}。")
        if len(value) > 20:
            raise serializers.ValidationError("筛选条件不能超过 20 项。")
        return value

    def _validate_string_list(self, value, label):
        if not isinstance(value, list) or len(value) > 30 or any(not isinstance(item, str) or len(item) > 100 for item in value):
            raise serializers.ValidationError(f"{label}必须是最多 30 项的短字符串列表。")
        return value

    def validate_column_definition(self, value):
        return self._validate_string_list(value, "列定义")

    def validate_sort_definition(self, value):
        return self._validate_string_list(value, "排序定义")

    def validate(self, attrs):
        instance = self.instance
        module_code = attrs.get("module_code", getattr(instance, "module_code", ""))
        filters = attrs.get("filter_definition", getattr(instance, "filter_definition", {}))
        invalid = set(filters) - MODULE_FIELDS.get(module_code, set())
        if invalid:
            raise serializers.ValidationError(
                {"filter_definition": f"切换模块后存在无效筛选字段：{', '.join(sorted(invalid))}。"}
            )
        return attrs


class SavedViewArchiveSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500, default="用户归档保存视图")
