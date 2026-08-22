from django.db.models import Q
from rest_framework import serializers

from apps.core.models import currency_code_validator, uppercase_code_validator
from apps.core.serializers import EmployeeSummarySerializer
from apps.customers.models import CustomerAccount, CustomerContact, CustomerTransactionEntity
from apps.customers.selectors import accessible_customers
from apps.files.models import BusinessFile
from apps.organizations.models import Employee

from ..models import Inquiry, InquiryFileLink, InquiryItem, InquirySlaLink


class InquiryItemSerializer(serializers.ModelSerializer):
    line_number = serializers.IntegerField(required=False, min_value=1)
    unit_code = serializers.CharField(max_length=30, validators=[uppercase_code_validator])
    target_currency_code = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=3,
        validators=[currency_code_validator],
    )

    class Meta:
        model = InquiryItem
        fields = [
            "id",
            "line_number",
            "product_description",
            "specification",
            "quantity",
            "unit_code",
            "target_unit_price",
            "target_currency_code",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class InquiryItemUpdateSerializer(InquiryItemSerializer):
    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        return attrs


class InquiryFileLinkSerializer(serializers.ModelSerializer):
    file_id = serializers.UUIDField(source="business_file_id", read_only=True)
    original_name = serializers.CharField(source="business_file.original_name", read_only=True)
    content_type = serializers.CharField(source="business_file.content_type", read_only=True)
    size_bytes = serializers.IntegerField(source="business_file.size_bytes", read_only=True)
    scan_status = serializers.CharField(source="business_file.scan_status", read_only=True)

    class Meta:
        model = InquiryFileLink
        fields = [
            "id",
            "file_id",
            "original_name",
            "content_type",
            "size_bytes",
            "scan_status",
            "file_role",
            "created_at",
        ]


class InquiryFileLinkCreateSerializer(serializers.Serializer):
    file_id = serializers.PrimaryKeyRelatedField(
        source="business_file",
        queryset=BusinessFile.objects.filter(archived_at__isnull=True),
    )
    file_role = serializers.CharField(max_length=50, validators=[uppercase_code_validator])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inquiry = self.context.get("inquiry")
        request = self.context.get("request")
        if inquiry is None or request is None:
            self.fields["file_id"].queryset = BusinessFile.objects.none()
            return
        actor = getattr(request, "employee", None)
        self.fields["file_id"].queryset = BusinessFile.objects.filter(
            Q(uploaded_by_employee=actor)
            | Q(customer_links__customer_account=inquiry.customer_account)
            | Q(communication_links__communication__customer_account=inquiry.customer_account)
            | Q(inquiry_links__inquiry__customer_account=inquiry.customer_account)
            | Q(quotation_links__quotation_version__quotation__customer_account=inquiry.customer_account)
            | Q(sample_links__sample_request__customer_account=inquiry.customer_account),
            archived_at__isnull=True,
        ).distinct()

    def validate_file_id(self, business_file):
        inquiry = self.context["inquiry"]
        actor = getattr(self.context["request"], "employee", None)
        linked_customer_ids = set(business_file.customer_links.values_list("customer_account_id", flat=True))
        linked_customer_ids.update(
            business_file.communication_links.values_list("communication__customer_account_id", flat=True)
        )
        linked_customer_ids.update(
            business_file.inquiry_links.values_list("inquiry__customer_account_id", flat=True)
        )
        linked_customer_ids.update(
            business_file.quotation_links.values_list(
                "quotation_version__quotation__customer_account_id", flat=True
            )
        )
        linked_customer_ids.update(
            business_file.sample_links.values_list("sample_request__customer_account_id", flat=True)
        )
        if linked_customer_ids and linked_customer_ids != {inquiry.customer_account_id}:
            raise serializers.ValidationError("文件已关联到其他客户，不能跨客户复用。")
        if not linked_customer_ids and business_file.uploaded_by_employee_id != getattr(actor, "pk", None):
            raise serializers.ValidationError("未关联文件只能由上传人首次挂接。")
        return business_file


class InquirySlaSerializer(serializers.ModelSerializer):
    policy_code = serializers.CharField(source="sla_tracking.sla_policy.policy_code", read_only=True)
    policy_name = serializers.CharField(source="sla_tracking.sla_policy.display_name", read_only=True)
    status = serializers.CharField(source="sla_tracking.status", read_only=True)
    started_at = serializers.DateTimeField(source="sla_tracking.started_at", read_only=True)
    next_deadline_at = serializers.DateTimeField(source="sla_tracking.next_deadline_at", read_only=True)
    breached_at = serializers.DateTimeField(source="sla_tracking.breached_at", read_only=True)
    completed_at = serializers.DateTimeField(source="sla_tracking.completed_at", read_only=True)

    class Meta:
        model = InquirySlaLink
        fields = [
            "id",
            "policy_code",
            "policy_name",
            "status",
            "started_at",
            "next_deadline_at",
            "breached_at",
            "completed_at",
        ]


class InquiryListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer_account.account_name", read_only=True)
    owner = EmployeeSummarySerializer(source="owner_employee", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Inquiry
        fields = [
            "id",
            "inquiry_number",
            "customer_account",
            "customer_name",
            "owner",
            "status",
            "status_display",
            "subject",
            "inquiry_source",
            "received_at",
            "requested_due_at",
            "submitted_at",
            "archived_at",
            "created_at",
            "updated_at",
        ]


class InquiryDetailSerializer(InquiryListSerializer):
    items = InquiryItemSerializer(many=True, read_only=True)
    files = InquiryFileLinkSerializer(source="file_links", many=True, read_only=True)
    sla = InquirySlaSerializer(source="sla_links", many=True, read_only=True)

    class Meta(InquiryListSerializer.Meta):
        fields = InquiryListSerializer.Meta.fields + [
            "transaction_entity",
            "customer_contact",
            "description",
            "source_system",
            "external_id",
            "items",
            "files",
            "sla",
        ]


class InquiryWritableSerializer(serializers.ModelSerializer):
    transaction_entity_id = serializers.PrimaryKeyRelatedField(
        source="transaction_entity",
        required=False,
        allow_null=True,
        queryset=CustomerTransactionEntity.objects.filter(archived_at__isnull=True),
    )
    customer_contact_id = serializers.PrimaryKeyRelatedField(
        source="customer_contact",
        required=False,
        allow_null=True,
        queryset=CustomerContact.objects.filter(archived_at__isnull=True),
    )
    owner_employee_id = serializers.PrimaryKeyRelatedField(
        source="owner_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
    inquiry_source = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[uppercase_code_validator],
    )
    source_system = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        validators=[uppercase_code_validator],
    )
    external_id = serializers.CharField(required=False, allow_blank=True, max_length=150)

    def validate(self, attrs):
        customer = attrs.get("customer_account", getattr(self.instance, "customer_account", None))
        entity = attrs.get("transaction_entity", getattr(self.instance, "transaction_entity", None))
        contact = attrs.get("customer_contact", getattr(self.instance, "customer_contact", None))
        source_system = attrs.get("source_system", getattr(self.instance, "source_system", ""))
        external_id = attrs.get("external_id", getattr(self.instance, "external_id", ""))
        errors = {}
        if entity and entity.customer_account_id != customer.pk:
            errors["transaction_entity_id"] = "交易主体必须属于当前客户。"
        if contact and contact.customer_account_id != customer.pk:
            errors["customer_contact_id"] = "联系人必须属于当前客户。"
        if bool(source_system) != bool(external_id):
            errors["source_system"] = "来源系统和外部编号必须同时填写或同时留空。"
        elif source_system:
            duplicate = Inquiry.objects.filter(source_system=source_system, external_id=external_id)
            if self.instance:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                errors["external_id"] = "该来源系统下的外部编号已经存在。"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class InquiryCreateSerializer(InquiryWritableSerializer):
    customer_account_id = serializers.PrimaryKeyRelatedField(
        source="customer_account",
        queryset=CustomerAccount.objects.filter(archived_at__isnull=True),
    )
    items = InquiryItemSerializer(many=True, required=False)

    class Meta:
        model = Inquiry
        fields = [
            "customer_account_id",
            "transaction_entity_id",
            "customer_contact_id",
            "owner_employee_id",
            "inquiry_source",
            "subject",
            "description",
            "received_at",
            "requested_due_at",
            "source_system",
            "external_id",
            "items",
        ]
        validators = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not getattr(request.user, "is_authenticated", False):
            return
        allowed = accessible_customers(request, "add_inquiry").filter(archived_at__isnull=True)
        self.fields["customer_account_id"].queryset = allowed
        self.fields["transaction_entity_id"].queryset = CustomerTransactionEntity.objects.filter(
            customer_account__in=allowed, archived_at__isnull=True
        )
        self.fields["customer_contact_id"].queryset = CustomerContact.objects.filter(
            customer_account__in=allowed, archived_at__isnull=True
        )

    def validate_items(self, items):
        if len(items) > 200:
            raise serializers.ValidationError("单张询价最多包含 200 条明细。")
        numbers = [item.get("line_number") for item in items if item.get("line_number") is not None]
        if len(numbers) != len(set(numbers)):
            raise serializers.ValidationError("明细行号不能重复。")
        return items


class InquiryUpdateSerializer(InquiryWritableSerializer):
    class Meta:
        model = Inquiry
        fields = [
            "transaction_entity_id",
            "customer_contact_id",
            "owner_employee_id",
            "inquiry_source",
            "subject",
            "description",
            "received_at",
            "requested_due_at",
            "source_system",
            "external_id",
        ]
        validators = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is None:
            return
        self.fields["transaction_entity_id"].queryset = CustomerTransactionEntity.objects.filter(
            customer_account=self.instance.customer_account,
            archived_at__isnull=True,
        )
        self.fields["customer_contact_id"].queryset = CustomerContact.objects.filter(
            customer_account=self.instance.customer_account,
            archived_at__isnull=True,
        )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        return super().validate(attrs)


class InquiryActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class InquiryReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=True)
