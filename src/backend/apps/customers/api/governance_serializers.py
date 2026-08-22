from django.contrib.auth.models import Permission
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.serializers import EmployeeSummarySerializer
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee

from ..models import (
    CustomerDataAccessGrant,
    CustomerDuplicateCandidate,
    CustomerDuplicateCase,
    CustomerMergeChange,
    CustomerMergeMember,
    CustomerMergeOperation,
    CustomerTransferRequest,
    DuplicateDecision,
)


class CustomerTransferRequestSerializer(serializers.ModelSerializer):
    customer = serializers.SerializerMethodField()
    from_employee = EmployeeSummarySerializer(read_only=True)
    to_employee = EmployeeSummarySerializer(read_only=True)
    requested_by = EmployeeSummarySerializer(source="requested_by_employee", read_only=True, allow_null=True)
    decided_by = EmployeeSummarySerializer(source="decided_by_employee", read_only=True, allow_null=True)

    class Meta:
        model = CustomerTransferRequest
        fields = [
            "id", "customer", "from_employee", "to_employee", "requested_by", "decided_by",
            "status", "request_reason", "decision_note", "submitted_at", "decided_at",
            "created_at", "updated_at",
        ]

    @extend_schema_field(serializers.DictField())
    def get_customer(self, obj):
        customer = obj.customer_account
        return {"id": str(customer.pk), "account_code": customer.account_code, "account_name": customer.account_name}


class CustomerTransferCreateSerializer(serializers.Serializer):
    customer_id = serializers.UUIDField()
    to_employee_id = serializers.PrimaryKeyRelatedField(
        source="to_employee", queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True)
    )
    reason = serializers.CharField(min_length=2, max_length=2000, trim_whitespace=True)


class DecisionNoteSerializer(serializers.Serializer):
    decision_note = serializers.CharField(min_length=2, max_length=2000, trim_whitespace=True)


class CustomerAccessGrantSerializer(serializers.ModelSerializer):
    etag = serializers.SerializerMethodField()
    employee = EmployeeSummarySerializer(read_only=True)
    permission = serializers.SerializerMethodField()
    granted_by = EmployeeSummarySerializer(source="granted_by_employee", read_only=True, allow_null=True)
    revoked_by = EmployeeSummarySerializer(source="revoked_by_employee", read_only=True, allow_null=True)

    class Meta:
        model = CustomerDataAccessGrant
        fields = [
            "id", "etag", "employee", "permission", "effective_from", "effective_to", "granted_by",
            "revoked_at", "revoked_by", "reason", "created_at", "updated_at",
        ]

    @extend_schema_field(serializers.DictField())
    def get_permission(self, obj):
        return {
            "id": obj.permission_id,
            "code": f"{obj.permission.content_type.app_label}.{obj.permission.codename}",
            "name": obj.permission.name,
        }

    def get_etag(self, obj) -> str:
        return etag_for_instance(obj)


class CustomerAccessGrantCreateSerializer(serializers.Serializer):
    employee_id = serializers.PrimaryKeyRelatedField(
        source="employee", queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True)
    )
    permission_code = serializers.CharField(max_length=200)
    effective_from = serializers.DateTimeField(required=False)
    effective_to = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(min_length=2, max_length=500, trim_whitespace=True)

    def validate_permission_code(self, value):
        try:
            app_label, codename = value.split(".", 1)
        except ValueError as exc:
            raise serializers.ValidationError("权限代号格式必须为 app_label.codename。") from exc
        allowed_apps = {"customers", "crm", "inquiries", "quotations", "samples", "workflow", "files"}
        if app_label not in allowed_apps or codename in {"view_all_customer", "view_all_auditlog"}:
            raise serializers.ValidationError("该权限不允许通过客户级授权下放。")
        try:
            return Permission.objects.select_related("content_type").get(
                content_type__app_label=app_label, codename=codename
            )
        except Permission.DoesNotExist as exc:
            raise serializers.ValidationError("权限代号不存在。") from exc

    def validate(self, attrs):
        if attrs.get("effective_to") and attrs.get("effective_from") and attrs["effective_to"] <= attrs["effective_from"]:
            raise serializers.ValidationError({"effective_to": "结束时间必须晚于开始时间。"})
        return attrs


class DuplicateCandidateSerializer(serializers.ModelSerializer):
    customer = serializers.SerializerMethodField()
    etag = serializers.SerializerMethodField()

    class Meta:
        model = CustomerDuplicateCandidate
        fields = ["id", "etag", "customer", "confidence_score", "matched_fields", "decision", "created_at", "updated_at"]

    @extend_schema_field(serializers.DictField())
    def get_customer(self, obj):
        customer = obj.customer_account
        return {
            "id": str(customer.pk), "account_code": customer.account_code,
            "account_name": customer.account_name, "archived_at": customer.archived_at,
        }

    def get_etag(self, obj) -> str:
        return etag_for_instance(obj)


class DuplicateCaseSerializer(serializers.ModelSerializer):
    reviewer = EmployeeSummarySerializer(source="reviewer_employee", read_only=True, allow_null=True)
    candidates = DuplicateCandidateSerializer(many=True, read_only=True)

    class Meta:
        model = CustomerDuplicateCase
        fields = [
            "id", "reviewer", "status", "matching_strategy_version", "notes", "candidates",
            "created_at", "updated_at",
        ]


class DuplicateCandidateInputSerializer(serializers.Serializer):
    customer_id = serializers.UUIDField()
    confidence_score = serializers.DecimalField(max_digits=5, decimal_places=4, min_value=0, max_value=1)
    matched_fields = serializers.DictField(required=False)


class DuplicateCaseCreateSerializer(serializers.Serializer):
    reviewer_employee_id = serializers.PrimaryKeyRelatedField(
        source="reviewer_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    matching_strategy_version = serializers.CharField(min_length=1, max_length=50)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    candidates = DuplicateCandidateInputSerializer(many=True, min_length=2, max_length=20)

    def validate_candidates(self, value):
        ids = [item["customer_id"] for item in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("同一客户不能在候选列表中重复出现。")
        return value


class DuplicateDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=DuplicateDecision.choices)


class MergeRequestSerializer(serializers.Serializer):
    survivor_customer_id = serializers.UUIDField()
    source_customer_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=20, allow_empty=False
    )
    reason = serializers.CharField(min_length=2, max_length=2000, trim_whitespace=True)
    field_decisions = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        sources = attrs["source_customer_ids"]
        if len(sources) != len(set(sources)):
            raise serializers.ValidationError({"source_customer_ids": "来源客户不能重复。"})
        if attrs["survivor_customer_id"] in sources:
            raise serializers.ValidationError({"source_customer_ids": "存续客户不能同时作为来源客户。"})
        return attrs


class MergeMemberSerializer(serializers.ModelSerializer):
    customer = serializers.SerializerMethodField()

    class Meta:
        model = CustomerMergeMember
        fields = ["id", "member_role", "customer"]

    @extend_schema_field(serializers.DictField())
    def get_customer(self, obj):
        customer = obj.customer_account
        return {"id": str(customer.pk), "account_code": customer.account_code, "account_name": customer.account_name}


class MergeChangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerMergeChange
        fields = ["sequence_number", "object_type", "object_id", "change_data"]


class MergeOperationSerializer(serializers.ModelSerializer):
    executed_by = EmployeeSummarySerializer(source="executed_by_employee", read_only=True, allow_null=True)
    members = MergeMemberSerializer(many=True, read_only=True)
    changes = MergeChangeSerializer(many=True, read_only=True)

    class Meta:
        model = CustomerMergeOperation
        fields = [
            "id", "duplicate_case_id", "executed_by", "status", "reason", "executed_at",
            "members", "changes", "created_at", "updated_at",
        ]
