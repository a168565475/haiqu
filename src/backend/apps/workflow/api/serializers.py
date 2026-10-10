from apps.access_control.module_policy import ModuleAccessSerializerMixin
from drf_spectacular.utils import extend_schema_field
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from rest_framework import serializers

from apps.core.serializers import EmployeeSummarySerializer
from apps.customers.models import CustomerContact
from apps.organizations.models import Employee

from ..models import (
    ApprovalRequest,
    BusinessTask,
    SlaTracking,
    TaskChecklistItem,
    TaskPriority,
    TaskStatus,
    TaskType,
    TaskWorkState,
)


TASK_SOURCE_TYPES = [
    "CUSTOMER",
    "COMMUNICATION",
    "INQUIRY",
    "QUOTATION_VERSION",
    "SAMPLE_REQUEST",
]


class TaskListSerializer(ModuleAccessSerializerMixin, serializers.ModelSerializer):
    assignee = EmployeeSummarySerializer(source="assignee_employee", read_only=True)
    created_by = EmployeeSummarySerializer(
        source="created_by_employee",
        allow_null=True,
        read_only=True,
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    task_type_display = serializers.CharField(source="get_task_type_display", read_only=True)
    origin_type_display = serializers.CharField(source="get_origin_type_display", read_only=True)
    work_state_display = serializers.CharField(source="get_work_state_display", read_only=True)
    source = serializers.SerializerMethodField()
    customer = serializers.SerializerMethodField()
    contact_summary = serializers.SerializerMethodField()
    display_status = serializers.SerializerMethodField()
    checklist_progress = serializers.SerializerMethodField()

    class Meta:
        model = BusinessTask
        fields = [
            "allowed_permissions",
            "id",
            "task_number",
            "title",
            "status",
            "status_display",
            "priority",
            "priority_display",
            "task_type",
            "task_type_display",
            "origin_type",
            "origin_type_display",
            "work_state",
            "work_state_display",
            "display_status",
            "work_state_reason",
            "next_check_at",
            "due_at",
            "completed_at",
            "completion_result",
            "cancelled_at",
            "cancel_reason",
            "reschedule_count",
            "business_version",
            "assignee",
            "created_by",
            "contact_summary",
            "customer",
            "source",
            "checklist_progress",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(
        serializers.DictField(child=serializers.CharField(), allow_null=True)
    )
    def get_source(self, obj):
        for source_type, relation_name, object_field in [
            ("CUSTOMER", "primary_customer_links", "customer_account"),
            ("COMMUNICATION", "primary_communication_links", "communication"),
            ("INQUIRY", "primary_inquiry_links", "inquiry"),
            ("QUOTATION_VERSION", "primary_quotation_links", "quotation_version"),
            ("SAMPLE_REQUEST", "primary_sample_links", "sample_request"),
        ]:
            links = getattr(obj, relation_name, None)
            if links is None:
                links = getattr(obj, relation_name.replace("primary_", "")).filter(is_primary_source=True)
            if links:
                source = getattr(links[0], object_field)
                return {
                    "type": source_type,
                    "id": str(source.pk),
                    "code": self._source_code(source, source_type),
                    "title": self._source_title(source, source_type),
                    "open_url": None,
                }
        return None

    def get_customer(self, obj):
        source = self.get_source(obj)
        if not source:
            return None
        for links, field, path in [
            (getattr(obj, "primary_customer_links", []), "customer_account", None),
            (getattr(obj, "primary_communication_links", []), "communication", "customer_account"),
            (getattr(obj, "primary_inquiry_links", []), "inquiry", "customer_account"),
            (getattr(obj, "primary_quotation_links", []), "quotation_version", "quotation.customer_account"),
            (getattr(obj, "primary_sample_links", []), "sample_request", "customer_account"),
        ]:
            if not links:
                continue
            customer = getattr(links[0], field)
            if path:
                for attribute in path.split("."):
                    customer = getattr(customer, attribute)
            return {"id": str(customer.pk), "code": customer.account_code, "name": customer.account_name}
        return None

    def get_contact_summary(self, obj):
        if not obj.contact_id:
            return None
        return {"id": str(obj.contact_id), "name": obj.contact.display_name, "position": obj.contact.position_title}

    def get_display_status(self, obj):
        if obj.work_state == TaskWorkState.BLOCKED:
            return "BLOCKED"
        if obj.status in {TaskStatus.PENDING, TaskStatus.IN_PROGRESS} and obj.due_at and obj.due_at < timezone.now():
            return "OVERDUE"
        if obj.work_state == TaskWorkState.WAITING_CUSTOMER:
            return "WAITING_CUSTOMER"
        return obj.status

    def get_checklist_progress(self, obj):
        items = list(getattr(obj, "checklist_items", []).all()) if hasattr(getattr(obj, "checklist_items", None), "all") else []
        return {"completed": sum(item.is_completed for item in items), "total": len(items)}

    @staticmethod
    def _source_code(source, source_type):
        if source_type == "CUSTOMER":
            return source.account_code
        if source_type == "QUOTATION_VERSION":
            return f"{source.quotation.quotation_number} V{source.version_number}"
        return getattr(source, "communication_number", "") or getattr(source, "inquiry_number", "") or getattr(source, "request_number", "") or ""

    @staticmethod
    def _source_title(source, source_type):
        if source_type == "CUSTOMER":
            return source.account_name
        if source_type == "QUOTATION_VERSION":
            return source.quotation.quotation_number
        return getattr(source, "subject", "") or getattr(source, "product_description_snapshot", "") or str(source)


class TaskDetailSerializer(TaskListSerializer):
    checklist_items = serializers.SerializerMethodField()
    reminders = serializers.SerializerMethodField()
    collaborators = serializers.SerializerMethodField()
    source_attachments = serializers.SerializerMethodField()

    class Meta(TaskListSerializer.Meta):
        fields = TaskListSerializer.Meta.fields + ["description", "checklist_items", "reminders", "collaborators", "source_attachments"]

    def get_checklist_items(self, obj):
        return [
            {
                "id": str(item.pk),
                "content": item.content,
                "sort_order": item.sort_order,
                "is_completed": item.is_completed,
                "completed_at": item.completed_at,
            }
            for item in obj.checklist_items.all()
        ]

    def get_reminders(self, obj):
        return [
            {"id": str(item.pk), "remind_at": item.remind_at, "status": item.status, "status_display": item.get_status_display()}
            for item in obj.reminders.all().order_by("remind_at", "id")
        ]

    def get_collaborators(self, obj):
        return EmployeeSummarySerializer([item.employee for item in obj.collaborators.all()], many=True).data

    def get_source_attachments(self, obj):
        from apps.workflow.services import task_customer_and_source

        _, _, source_id = task_customer_and_source(obj)
        source = self.get_source(obj)
        if not source or not source_id:
            return []
        source_object = None
        for relation_name, field_name in [
            ("primary_customer_links", "customer_account"),
            ("primary_communication_links", "communication"),
            ("primary_inquiry_links", "inquiry"),
            ("primary_quotation_links", "quotation_version"),
            ("primary_sample_links", "sample_request"),
        ]:
            links = getattr(obj, relation_name, [])
            if links:
                source_object = getattr(links[0], field_name)
                break
        from apps.access_control import module_policy
        if source_object is not None and source_object._meta.model_name == 'samplerequest' and module_policy.enabled():
            if not module_policy.can_sample(self.context.get('request'), source_object, 'samples.view_samplefilelink'):
                return []
        if not source_object or not hasattr(source_object, "file_links"):
            return []
        return [
            {
                "id": str(link.business_file_id),
                "name": link.business_file.original_name,
                "content_type": link.business_file.content_type,
                "size_bytes": link.business_file.size_bytes,
                "preview_url": f"/api/v1/tasks/{obj.pk}/attachments/{link.business_file_id}/preview/",
                "download_url": f"/api/v1/tasks/{obj.pk}/attachments/{link.business_file_id}/download/",
            }
            for link in source_object.file_links.filter(
                business_file__scan_status="CLEAN",
                business_file__archived_at__isnull=True,
            ).select_related("business_file")
        ]


class TaskCreateSerializer(serializers.ModelSerializer):
    def validate_contact_id(self, contact):
        from apps.access_control import sales_policy
        if contact:
            sales_policy.require_customer(self.context.get("request"), "customers.view_customercontact", contact.customer_account)
        return contact

    assignee_employee_id = serializers.PrimaryKeyRelatedField(
        source="assignee_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
    source_type = serializers.ChoiceField(choices=TASK_SOURCE_TYPES, required=False)
    source_id = serializers.UUIDField(required=False)
    contact_id = serializers.PrimaryKeyRelatedField(
        source="contact",
        queryset=CustomerContact.objects.filter(archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    checklist = serializers.ListField(child=serializers.CharField(max_length=500), required=False, write_only=True)
    reminder_at_list = serializers.ListField(child=serializers.DateTimeField(), required=False, write_only=True)

    class Meta:
        model = BusinessTask
        fields = [
            "assignee_employee_id",
            "title",
            "description",
            "priority",
            "task_type",
            "contact_id",
            "due_at",
            "source_type",
            "source_id",
            "checklist",
            "reminder_at_list",
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
    def validate_contact_id(self, contact):
        from apps.access_control import sales_policy
        if contact:
            sales_policy.require_customer(self.context.get("request"), "customers.view_customercontact", contact.customer_account)
        return contact

    contact_id = serializers.PrimaryKeyRelatedField(
        source="contact",
        queryset=CustomerContact.objects.filter(archived_at__isnull=True),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = BusinessTask
        fields = ["title", "description", "priority", "task_type", "contact_id", "due_at"]

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


class TaskWorkStateSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=True, required=False, allow_blank=True)
    next_check_at = serializers.DateTimeField(required=False, allow_null=True)


class TaskRescheduleSerializer(serializers.Serializer):
    new_due_at = serializers.DateTimeField()
    reason = serializers.CharField(max_length=500, trim_whitespace=True)
    sync_reminders = serializers.BooleanField(default=True)


class ChecklistToggleSerializer(serializers.Serializer):
    is_completed = serializers.BooleanField()


class TaskBatchItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    version = serializers.IntegerField(min_value=1)


class TaskBatchSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    items = TaskBatchItemSerializer(many=True, allow_empty=False, max_length=100)
    reason = serializers.CharField(max_length=500, trim_whitespace=True, required=False, allow_blank=True)


class TaskBulkReassignSerializer(TaskBatchSerializer):
    assignee_employee_id = serializers.PrimaryKeyRelatedField(
        source="assignee_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )


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
