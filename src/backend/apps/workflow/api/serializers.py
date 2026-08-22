from drf_spectacular.utils import extend_schema_field
from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from apps.core.serializers import EmployeeSummarySerializer
from apps.organizations.models import Employee

from ..models import ApprovalRequest, BusinessTask, SlaTracking


TASK_SOURCE_TYPES = [
    "CUSTOMER",
    "COMMUNICATION",
    "INQUIRY",
    "QUOTATION_VERSION",
    "SAMPLE_REQUEST",
]


class TaskListSerializer(serializers.ModelSerializer):
    assignee = EmployeeSummarySerializer(source="assignee_employee", read_only=True)
    created_by = EmployeeSummarySerializer(
        source="created_by_employee",
        allow_null=True,
        read_only=True,
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    source = serializers.SerializerMethodField()

    class Meta:
        model = BusinessTask
        fields = [
            "id",
            "title",
            "status",
            "status_display",
            "priority",
            "priority_display",
            "due_at",
            "completed_at",
            "assignee",
            "created_by",
            "source",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(
        serializers.DictField(child=serializers.CharField(), allow_null=True)
    )
    def get_source(self, obj):
        for source_type, relation_name, object_field in [
            ("CUSTOMER", "customer_links", "customer_account_id"),
            ("COMMUNICATION", "communication_links", "communication_id"),
            ("INQUIRY", "inquiry_links", "inquiry_id"),
            ("QUOTATION_VERSION", "quotation_links", "quotation_version_id"),
            ("SAMPLE_REQUEST", "sample_links", "sample_request_id"),
        ]:
            links = list(getattr(obj, relation_name).all())
            primary = next((link for link in links if link.is_primary_source), None)
            if primary:
                return {"type": source_type, "id": str(getattr(primary, object_field))}
        return None


class TaskDetailSerializer(TaskListSerializer):
    class Meta(TaskListSerializer.Meta):
        fields = TaskListSerializer.Meta.fields + ["description"]


class TaskCreateSerializer(serializers.ModelSerializer):
    assignee_employee_id = serializers.PrimaryKeyRelatedField(
        source="assignee_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
    source_type = serializers.ChoiceField(choices=TASK_SOURCE_TYPES, required=False)
    source_id = serializers.UUIDField(required=False)

    class Meta:
        model = BusinessTask
        fields = [
            "assignee_employee_id",
            "title",
            "description",
            "priority",
            "due_at",
            "source_type",
            "source_id",
        ]

    def validate(self, attrs):
        source_type = attrs.get("source_type")
        source_id = attrs.get("source_id")
        if bool(source_type) != bool(source_id):
            raise serializers.ValidationError(
                {"source_type": "source_type 和 source_id 必须同时填写或同时留空。"}
            )
        return attrs


class TaskUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessTask
        fields = ["title", "description", "priority", "due_at"]

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        return attrs


class TaskActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class TaskReassignSerializer(serializers.Serializer):
    assignee_employee_id = serializers.PrimaryKeyRelatedField(
        source="assignee_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class ApprovalListSerializer(serializers.ModelSerializer):
    current_approver = EmployeeSummarySerializer(source="current_approver_employee", read_only=True)
    requested_by = EmployeeSummarySerializer(
        source="requested_by_employee",
        allow_null=True,
        read_only=True,
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    source = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalRequest
        fields = [
            "id",
            "approval_type",
            "status",
            "status_display",
            "current_approver",
            "requested_by",
            "submitted_at",
            "decided_at",
            "source",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.DictField(child=serializers.CharField(), allow_null=True))
    def get_source(self, obj):
        link = getattr(obj, "quotation_link", None)
        if link:
            return {"type": "QUOTATION_VERSION", "id": str(link.quotation_version_id)}
        return None


class ApprovalDetailSerializer(ApprovalListSerializer):
    class Meta(ApprovalListSerializer.Meta):
        fields = ApprovalListSerializer.Meta.fields + ["request_reason", "decision_note"]


class ApprovalDecisionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class ApprovalCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class SlaTrackingSerializer(serializers.ModelSerializer):
    policy_code = serializers.CharField(source="sla_policy.policy_code", read_only=True)
    policy_name = serializers.CharField(source="sla_policy.display_name", read_only=True)
    target_type = serializers.CharField(source="sla_policy.target_type", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    source = serializers.SerializerMethodField()

    class Meta:
        model = SlaTracking
        fields = [
            "id",
            "policy_code",
            "policy_name",
            "target_type",
            "status",
            "status_display",
            "started_at",
            "next_deadline_at",
            "breached_at",
            "completed_at",
            "tracking_data",
            "source",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.DictField(child=serializers.CharField(), allow_null=True))
    def get_source(self, obj):
        for relation, source_type, object_field in [
            ("inquiry_link", "INQUIRY", "inquiry_id"),
            ("quotation_link", "QUOTATION_VERSION", "quotation_version_id"),
            ("sample_link", "SAMPLE_REQUEST", "sample_request_id"),
        ]:
            try:
                link = getattr(obj, relation)
            except ObjectDoesNotExist:
                continue
            return {"type": source_type, "id": str(getattr(link, object_field))}
        return None
