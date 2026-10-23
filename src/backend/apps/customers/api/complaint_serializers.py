from apps.access_control import sales_policy
from django.utils import timezone
from rest_framework import serializers

from apps.organizations.selectors import active_department_employees
from apps.organizations.models import Employee, EmployeeStatus
from apps.reference_data.models import ReferenceDictionary
from apps.reference_data.services import published_dictionary_item_id_is_active

from ..models import (
    ComplaintStatus,
    CustomerAccount,
    CustomerComplaint,
    CustomerComplaintAttachment,
    CustomerComplaintProgress,
    CustomerContact,
)
from ..selectors import accessible_customers


COMPLAINT_TYPE_CATEGORY = "COMPLAINT_TYPE"
COMPLAINT_SEVERITY_CATEGORY = "COMPLAINT_SEVERITY"


def active_employees():
    return active_department_employees("DEPT_BUSINESS")


class ComplaintDictionarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferenceDictionary
        fields = ["id", "item_code", "display_name", "description", "sort_order", "extra_data"]


class ComplaintEmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ["id", "employee_code", "display_name"]


class ComplaintCustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAccount
        fields = ["id", "account_code", "account_name"]


class ComplaintContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerContact
        fields = ["id", "display_name", "position_title"]


class ComplaintAttachmentSerializer(serializers.ModelSerializer):
    original_name = serializers.CharField(source="business_file.original_name", read_only=True)
    content_type = serializers.CharField(source="business_file.content_type", read_only=True)
    size_bytes = serializers.IntegerField(source="business_file.size_bytes", read_only=True)
    preview_url = serializers.SerializerMethodField()

    class Meta:
        model = CustomerComplaintAttachment
        fields = [
            "id",
            "progress_entry_id",
            "caption",
            "original_name",
            "content_type",
            "size_bytes",
            "preview_url",
            "created_at",
        ]

    def get_preview_url(self, obj) -> str:
        return f"/api/v1/complaints/{obj.complaint_id}/attachments/{obj.pk}/preview/"


class ComplaintProgressSerializer(serializers.ModelSerializer):
    from_status_label = serializers.CharField(source="get_from_status_display", read_only=True)
    to_status_label = serializers.CharField(source="get_to_status_display", read_only=True)
    created_by = ComplaintEmployeeSerializer(source="created_by_employee", read_only=True)
    attachments = ComplaintAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = CustomerComplaintProgress
        fields = [
            "id",
            "from_status",
            "from_status_label",
            "to_status",
            "to_status_label",
            "progress_note",
            "root_cause",
            "responsibility",
            "solution",
            "customer_feedback",
            "created_by",
            "attachments",
            "created_at",
        ]


class ComplaintReadSerializer(serializers.ModelSerializer):
    customer = ComplaintCustomerSerializer(source="customer_account", read_only=True)
    original_customer = ComplaintCustomerSerializer(source="original_customer_account", read_only=True)
    contact = ComplaintContactSerializer(read_only=True)
    complaint_type = ComplaintDictionarySerializer(source="complaint_type_item", read_only=True)
    severity = ComplaintDictionarySerializer(source="severity_item", read_only=True)
    owner = ComplaintEmployeeSerializer(source="owner_employee", read_only=True)
    collaborators = ComplaintEmployeeSerializer(source="collaborator_employees", many=True, read_only=True)
    created_by = ComplaintEmployeeSerializer(source="created_by_employee", read_only=True)
    last_updated_by = ComplaintEmployeeSerializer(source="last_updated_by_employee", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    sla_status = serializers.SerializerMethodField()
    progress_entries = ComplaintProgressSerializer(many=True, read_only=True)
    attachments = ComplaintAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = CustomerComplaint
        fields = [
            "id",
            "complaint_code",
            "customer",
            "original_customer",
            "contact",
            "complaint_type",
            "severity",
            "title",
            "source_order_reference",
            "source_order_snapshot",
            "issue_description",
            "status",
            "status_label",
            "owner",
            "collaborators",
            "created_by",
            "last_updated_by",
            "root_cause",
            "responsibility",
            "solution",
            "customer_feedback",
            "first_response_due_at",
            "target_completion_at",
            "first_responded_at",
            "completed_at",
            "cancelled_at",
            "sla_status",
            "progress_entries",
            "attachments",
            "created_at",
            "updated_at",
        ]

    def get_sla_status(self, obj) -> str:
        if obj.status in {ComplaintStatus.CLOSED, ComplaintStatus.CANCELLED}:
            return "COMPLETED"
        remaining = obj.target_completion_at - timezone.now()
        if remaining.total_seconds() < 0:
            return "OVERDUE"
        if remaining.total_seconds() <= 24 * 60 * 60:
            return "AT_RISK"
        return "NORMAL"


class ComplaintWriteSerializer(serializers.ModelSerializer):
    customer_id = serializers.PrimaryKeyRelatedField(
        source="customer_account",
        queryset=CustomerAccount.objects.none(),
    )
    contact_id = serializers.PrimaryKeyRelatedField(
        source="contact",
        queryset=CustomerContact.objects.filter(archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    complaint_type_item_id = serializers.PrimaryKeyRelatedField(
        source="complaint_type_item",
        queryset=ReferenceDictionary.objects.filter(
            category_code=COMPLAINT_TYPE_CATEGORY,
            archived_at__isnull=True,
        ),
    )
    severity_item_id = serializers.PrimaryKeyRelatedField(
        source="severity_item",
        queryset=ReferenceDictionary.objects.filter(
            category_code=COMPLAINT_SEVERITY_CATEGORY,
            archived_at__isnull=True,
        ),
    )
    owner_employee_id = serializers.PrimaryKeyRelatedField(
        source="owner_employee",
        queryset=active_employees(),
        required=False,
    )
    collaborator_employee_ids = serializers.PrimaryKeyRelatedField(
        source="collaborator_employees",
        queryset=active_employees(),
        many=True,
        required=False,
    )

    class Meta:
        model = CustomerComplaint
        fields = [
            "customer_id",
            "contact_id",
            "complaint_type_item_id",
            "severity_item_id",
            "title",
            "source_order_reference",
            "source_order_snapshot",
            "issue_description",
            "owner_employee_id",
            "collaborator_employee_ids",
        ]
        extra_kwargs = {
            "title": {"max_length": 250},
            "source_order_reference": {"required": False, "allow_blank": True},
            "source_order_snapshot": {"required": False},
            "issue_description": {"allow_blank": False},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and "customer_id" in self.fields and not self.fields["customer_id"].read_only:
            self.fields["customer_id"].queryset = accessible_customers(request, "add_customercomplaint" if sales_policy.enabled() else "view_customeraccount").filter(archived_at__isnull=True)

    def validate(self, attrs):
        customer = attrs.get("customer_account") or getattr(self.instance, "customer_account", None)
        contact = attrs.get("contact")
        if contact is not None and customer is not None and contact.customer_account_id != customer.pk:
            raise serializers.ValidationError({"contact_id": "联系人不属于所选客户。"})
        snapshot = attrs.get("source_order_snapshot", {})
        if snapshot is not None and not isinstance(snapshot, dict):
            raise serializers.ValidationError({"source_order_snapshot": "订单快照必须是对象。"})
        dictionary_fields = (
            ("complaint_type_item", "complaint_type_item_id", COMPLAINT_TYPE_CATEGORY),
            ("severity_item", "severity_item_id", COMPLAINT_SEVERITY_CATEGORY),
        )
        for attribute_name, input_name, category_code in dictionary_fields:
            selected = attrs.get(attribute_name)
            if selected is None:
                continue
            current_id = getattr(self.instance, f"{attribute_name}_id", None)
            if selected.pk == current_id:
                continue
            if not published_dictionary_item_id_is_active(category_code, selected.pk):
                raise serializers.ValidationError({input_name: "该配置项未发布、已停用或已归档。"})
        return attrs


class ComplaintUpdateSerializer(ComplaintWriteSerializer):
    customer_id = None

    class Meta(ComplaintWriteSerializer.Meta):
        fields = [field for field in ComplaintWriteSerializer.Meta.fields if field != "customer_id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.required = False


class ComplaintProgressCreateSerializer(serializers.Serializer):
    to_status = serializers.ChoiceField(choices=ComplaintStatus.choices)
    progress_note = serializers.CharField(allow_blank=False, max_length=5000)
    root_cause = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    responsibility = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    solution = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    customer_feedback = serializers.CharField(required=False, allow_blank=True, max_length=5000)


class ComplaintAttachmentCreateSerializer(serializers.Serializer):
    file = serializers.FileField()
    progress_id = serializers.PrimaryKeyRelatedField(
        source="progress_entry",
        queryset=CustomerComplaintProgress.objects.all(),
        required=False,
        allow_null=True,
    )
    caption = serializers.CharField(required=False, allow_blank=True, max_length=250)
