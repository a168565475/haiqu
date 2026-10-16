from apps.access_control.sales_sources import require_file
from apps.access_control import sales_policy
from drf_spectacular.utils import extend_schema_field
from django.db.models import Q
from rest_framework import serializers

from apps.core.models import uppercase_code_validator
from apps.core.serializers import EmployeeSummarySerializer
from apps.customers.models import CustomerAccount, CustomerContact
from apps.customers.selectors import accessible_customers
from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
from apps.inquiries.models import Inquiry
from apps.organizations.models import Employee
from apps.quotations.models import QuotationVersion
from apps.reference_data.services import published_dictionary_code_is_active
from apps.samples.models import SampleRequest

from ..models import (
    CommunicationContactParticipant,
    CommunicationEmployeeParticipant,
    CommunicationFileLink,
    CustomerCommunication,
    CustomerTimelineEvent,
)


class ContactSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerContact
        fields = ["id", "display_name", "position_title", "status"]


class CommunicationEmployeeParticipantSerializer(serializers.ModelSerializer):
    employee = EmployeeSummarySerializer(read_only=True)

    class Meta:
        model = CommunicationEmployeeParticipant
        fields = ["id", "employee", "participant_role"]


class CommunicationContactParticipantSerializer(serializers.ModelSerializer):
    customer_contact = ContactSummarySerializer(read_only=True)

    class Meta:
        model = CommunicationContactParticipant
        fields = ["id", "customer_contact", "participant_role"]


class CommunicationFileLinkSerializer(serializers.ModelSerializer):
    file_id = serializers.UUIDField(source="business_file_id")
    original_name = serializers.CharField(source="business_file.original_name")
    scan_status = serializers.CharField(source="business_file.scan_status")

    class Meta:
        model = CommunicationFileLink
        fields = ["id", "file_id", "original_name", "scan_status", "file_role"]


class CommunicationListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer_account.account_name", read_only=True)
    created_by = EmployeeSummarySerializer(
        source="created_by_employee",
        allow_null=True,
        read_only=True,
    )
    direction_display = serializers.CharField(source="get_direction_display", read_only=True)

    class Meta:
        model = CustomerCommunication
        fields = [
            "id",
            "customer_account",
            "customer_name",
            "communication_type",
            "direction",
            "direction_display",
            "subject",
            "occurred_at",
            "created_by",
            "archived_at",
            "created_at",
            "updated_at",
        ]


class CommunicationDetailSerializer(CommunicationListSerializer):
    employee_participants = CommunicationEmployeeParticipantSerializer(many=True, read_only=True)
    contact_participants = CommunicationContactParticipantSerializer(many=True, read_only=True)
    files = serializers.SerializerMethodField()
    inquiry_ids = serializers.SerializerMethodField()
    quotation_version_ids = serializers.SerializerMethodField()
    sample_request_ids = serializers.SerializerMethodField()

    class Meta(CommunicationListSerializer.Meta):
        fields = CommunicationListSerializer.Meta.fields + [
            "content",
            "source_system",
            "external_id",
            "archive_reason",
            "employee_participants",
            "contact_participants",
            "inquiry_ids",
            "quotation_version_ids",
            "sample_request_ids",
            "files",
        ]

    @extend_schema_field(CommunicationFileLinkSerializer(many=True))
    def get_files(self, obj):
        return CommunicationFileLinkSerializer(obj.file_links.all(), many=True).data

    @extend_schema_field(serializers.ListField(child=serializers.UUIDField()))
    def get_inquiry_ids(self, obj):
        if sales_policy.enabled() and not sales_policy.can_customer(self.context["request"], "inquiries.view_inquiry", obj.customer_account_id):
            return []
        return [link.inquiry_id for link in obj.inquiry_links.all()]

    @extend_schema_field(serializers.ListField(child=serializers.UUIDField()))
    def get_quotation_version_ids(self, obj):
        if sales_policy.enabled() and not sales_policy.can_customer(self.context["request"], "quotations.view_quotationversion", obj.customer_account_id):
            return []
        return [link.quotation_version_id for link in obj.quotation_links.all()]

    @extend_schema_field(serializers.ListField(child=serializers.UUIDField()))
    def get_sample_request_ids(self, obj):
        return [link.sample_request_id for link in obj.sample_links.all()]


class CommunicationCreateSerializer(serializers.ModelSerializer):
    customer_account_id = serializers.PrimaryKeyRelatedField(
        source="customer_account",
        queryset=CustomerAccount.objects.filter(archived_at__isnull=True),
    )
    employee_participant_ids = serializers.PrimaryKeyRelatedField(
        source="participant_employees",
        many=True,
        required=False,
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
    contact_participant_ids = serializers.PrimaryKeyRelatedField(
        source="participant_contacts",
        many=True,
        required=False,
        queryset=CustomerContact.objects.filter(archived_at__isnull=True),
    )
    inquiry_id = serializers.PrimaryKeyRelatedField(
        source="inquiry",
        required=False,
        allow_null=True,
        queryset=Inquiry.objects.filter(archived_at__isnull=True),
    )
    quotation_version_id = serializers.PrimaryKeyRelatedField(
        source="quotation_version",
        required=False,
        allow_null=True,
        queryset=QuotationVersion.objects.filter(quotation__archived_at__isnull=True),
    )
    sample_request_id = serializers.PrimaryKeyRelatedField(
        source="sample_request",
        required=False,
        allow_null=True,
        queryset=SampleRequest.objects.filter(archived_at__isnull=True),
    )
    file_ids = serializers.PrimaryKeyRelatedField(
        source="business_files",
        many=True,
        required=False,
        queryset=BusinessFile.objects.filter(archived_at__isnull=True, scan_status__in=USABLE_FILE_SCAN_STATUSES),
    )
    source_system = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[uppercase_code_validator],
    )
    external_id = serializers.CharField(required=False, allow_blank=True, max_length=150)

    class Meta:
        model = CustomerCommunication
        fields = [
            "customer_account_id",
            "communication_type",
            "direction",
            "subject",
            "content",
            "occurred_at",
            "source_system",
            "external_id",
            "employee_participant_ids",
            "contact_participant_ids",
            "inquiry_id",
            "quotation_version_id",
            "sample_request_id",
            "file_ids",
        ]
        validators = []

    def validate_communication_type(self, value):
        normalized = value.strip().upper()
        if not published_dictionary_code_is_active("COMMUNICATION_TYPE", normalized):
            raise serializers.ValidationError("沟通方式不存在、已停用或尚未发布。")
        return normalized

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not getattr(request.user, "is_authenticated", False):
            return
        allowed_customers = accessible_customers(
            request,
            "add_customercommunication",
        ).filter(archived_at__isnull=True)
        self.fields["customer_account_id"].queryset = allowed_customers
        self.fields["contact_participant_ids"].child_relation.queryset = (
            CustomerContact.objects.filter(
                customer_account__in=allowed_customers,
                archived_at__isnull=True,
            )
        )
        self.fields["inquiry_id"].queryset = Inquiry.objects.filter(
            customer_account__in=allowed_customers,
            archived_at__isnull=True,
        )
        self.fields["quotation_version_id"].queryset = QuotationVersion.objects.filter(
            quotation__customer_account__in=allowed_customers,
            quotation__archived_at__isnull=True,
        )
        self.fields["sample_request_id"].queryset = SampleRequest.objects.filter(
            customer_account__in=allowed_customers,
            archived_at__isnull=True,
        )
        actor_employee = getattr(request, "employee", None)
        self.fields["file_ids"].child_relation.queryset = BusinessFile.objects.filter(
            Q(uploaded_by_employee=actor_employee)
            | Q(customer_links__customer_account__in=allowed_customers)
            | Q(communication_links__communication__customer_account__in=allowed_customers)
            | Q(inquiry_links__inquiry__customer_account__in=allowed_customers)
            | Q(
                quotation_links__quotation_version__quotation__customer_account__in=allowed_customers
            )
            | Q(sample_links__sample_request__customer_account__in=allowed_customers),
            archived_at__isnull=True,
            scan_status__in=USABLE_FILE_SCAN_STATUSES,
        ).distinct()

    def validate(self, attrs):
        customer = attrs["customer_account"]
        request = self.context.get("request")
        if attrs.get("inquiry"):
            sales_policy.require_customer(request, "inquiries.view_inquiry", attrs["inquiry"].customer_account)
        if attrs.get("quotation_version"):
            sales_policy.require_customer(request, "quotations.view_quotationversion", attrs["quotation_version"].quotation.customer_account)
        for contact in attrs.get("participant_contacts", []):
            sales_policy.require_customer(request, "customers.view_customercontact", contact.customer_account)
        source_system = attrs.get("source_system", "")
        external_id = attrs.get("external_id", "")
        errors = {}

        if bool(source_system) != bool(external_id):
            errors["source_system"] = "来源系统和外部编号必须同时填写或同时留空。"
        elif source_system and CustomerCommunication.objects.filter(
            source_system=source_system,
            external_id=external_id,
        ).exists():
            errors["external_id"] = "该来源系统下的外部编号已经存在。"

        contacts = attrs.get("participant_contacts", [])
        if any(contact.customer_account_id != customer.pk for contact in contacts):
            errors["contact_participant_ids"] = "所有沟通联系人必须属于当前客户。"

        inquiry = attrs.get("inquiry")
        if inquiry and inquiry.customer_account_id != customer.pk:
            errors["inquiry_id"] = "关联询价必须属于当前客户。"

        quotation_version = attrs.get("quotation_version")
        if quotation_version and quotation_version.quotation.customer_account_id != customer.pk:
            errors["quotation_version_id"] = "关联报价版本必须属于当前客户。"

        sample_request = attrs.get("sample_request")
        if sample_request and sample_request.customer_account_id != customer.pk:
            errors["sample_request_id"] = "关联样品申请必须属于当前客户。"

        participant_employees = attrs.get("participant_employees", [])
        if len({employee.pk for employee in participant_employees}) != len(participant_employees):
            errors["employee_participant_ids"] = "员工参与人不能重复。"
        if len({contact.pk for contact in contacts}) != len(contacts):
            errors["contact_participant_ids"] = "客户联系人不能重复。"

        business_files = attrs.get("business_files", [])
        if len(business_files) > 20:
            errors["file_ids"] = "单条沟通最多关联 20 个文件。"
        if len({business_file.pk for business_file in business_files}) != len(business_files):
            errors["file_ids"] = "文件不能重复。"
        request = self.context.get("request")
        actor_employee = getattr(request, "employee", None) if request else None
        for business_file in business_files:
            require_file(request, business_file)
            linked_customer_ids = set(
                business_file.customer_links.values_list("customer_account_id", flat=True)
            )
            linked_customer_ids.update(
                business_file.communication_links.values_list(
                    "communication__customer_account_id",
                    flat=True,
                )
            )
            linked_customer_ids.update(
                business_file.inquiry_links.values_list(
                    "inquiry__customer_account_id",
                    flat=True,
                )
            )
            linked_customer_ids.update(
                business_file.quotation_links.values_list(
                    "quotation_version__quotation__customer_account_id",
                    flat=True,
                )
            )
            linked_customer_ids.update(
                business_file.sample_links.values_list(
                    "sample_request__customer_account_id",
                    flat=True,
                )
            )
            if linked_customer_ids and linked_customer_ids != {customer.pk}:
                errors["file_ids"] = "文件已关联到其他客户，不能跨客户复用。"
                break
            if not linked_customer_ids and business_file.uploaded_by_employee_id != getattr(
                actor_employee,
                "pk",
                None,
            ):
                errors["file_ids"] = "未关联文件只能由上传人首次挂接。"
                break

        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class CommunicationUpdateSerializer(serializers.ModelSerializer):
    source_system = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[uppercase_code_validator],
    )
    external_id = serializers.CharField(required=False, allow_blank=True, max_length=150)

    class Meta:
        model = CustomerCommunication
        fields = [
            "communication_type",
            "direction",
            "subject",
            "content",
            "occurred_at",
            "source_system",
            "external_id",
        ]
        validators = []

    def validate_communication_type(self, value):
        normalized = value.strip().upper()
        if normalized == self.instance.communication_type or published_dictionary_code_is_active(
            "COMMUNICATION_TYPE", normalized
        ):
            return normalized
        raise serializers.ValidationError("沟通方式不存在、已停用或尚未发布。")

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        source_system = attrs.get("source_system", self.instance.source_system)
        external_id = attrs.get("external_id", self.instance.external_id)
        if bool(source_system) != bool(external_id):
            raise serializers.ValidationError(
                {"source_system": "来源系统和外部编号必须同时填写或同时留空。"}
            )
        duplicate = CustomerCommunication.objects.filter(
            source_system=source_system,
            external_id=external_id,
        ).exclude(pk=self.instance.pk)
        if source_system and duplicate.exists():
            raise serializers.ValidationError(
                {"external_id": "该来源系统下的外部编号已经存在。"}
            )
        return attrs


class TimelineEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerTimelineEvent
        fields = [
            "id",
            "event_type",
            "source_type",
            "source_id",
            "title",
            "summary",
            "occurred_at",
            "event_data",
            "created_at",
        ]


class TimelineQuerySerializer(serializers.Serializer):
    event_type = serializers.CharField(required=False, max_length=80)
    source_type = serializers.CharField(required=False, max_length=80)
    occurred_from = serializers.DateTimeField(required=False)
    occurred_to = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        occurred_from = attrs.get("occurred_from")
        occurred_to = attrs.get("occurred_to")
        if occurred_from and occurred_to and occurred_from > occurred_to:
            raise serializers.ValidationError(
                {"occurred_to": "结束时间不能早于开始时间。"}
            )
        return attrs
