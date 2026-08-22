from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from apps.core.models import currency_code_validator, uppercase_code_validator
from apps.core.serializers import EmployeeSummarySerializer
from apps.customers.models import CustomerAccount, CustomerContact, CustomerEntityAddress, CustomerTransactionEntity
from apps.customers.selectors import accessible_customers
from apps.files.models import BusinessFile
from apps.inquiries.models import Inquiry
from apps.organizations.models import Employee
from ..models import (
    Quotation,
    QuotationDispatchRecord,
    QuotationDocument,
    QuotationLine,
    QuotationQuantityTier,
    QuotationTemplate,
    QuotationVersion,
    QuotationVersionApprovalLink,
)


class QuotationTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuotationTemplate
        fields = [
            "id",
            "template_code",
            "template_name",
            "template_version",
            "requires_approval",
            "template_config",
        ]


class QuotationQuantityTierSerializer(serializers.ModelSerializer):
    min_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    max_quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=False,
        allow_null=True,
    )
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))

    class Meta:
        model = QuotationQuantityTier
        fields = ["id", "min_quantity", "max_quantity", "unit_price", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        min_quantity = attrs.get("min_quantity", getattr(self.instance, "min_quantity", None))
        max_quantity = attrs.get("max_quantity", getattr(self.instance, "max_quantity", None))
        if max_quantity is not None and min_quantity is not None and max_quantity <= min_quantity:
            raise serializers.ValidationError({"max_quantity": "最大数量必须大于最小数量。"})
        return attrs


class QuotationLineSerializer(serializers.ModelSerializer):
    line_number = serializers.IntegerField(required=False, min_value=1)
    unit_code = serializers.CharField(max_length=30, validators=[uppercase_code_validator])
    line_total = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    discount_rate = serializers.DecimalField(
        max_digits=7,
        decimal_places=6,
        min_value=Decimal("0"),
        max_value=Decimal("1"),
        required=False,
        default=Decimal("0"),
    )
    quantity_tiers = QuotationQuantityTierSerializer(many=True, read_only=True)

    class Meta:
        model = QuotationLine
        fields = [
            "id",
            "line_number",
            "product_description_snapshot",
            "specification_snapshot",
            "quantity",
            "unit_code",
            "unit_price",
            "discount_rate",
            "line_total",
            "notes",
            "quantity_tiers",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "line_total", "created_at", "updated_at"]


class QuotationLineUpdateSerializer(QuotationLineSerializer):
    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        return attrs


class QuotationDocumentSerializer(serializers.ModelSerializer):
    file_id = serializers.UUIDField(source="business_file_id", read_only=True)
    original_name = serializers.CharField(source="business_file.original_name", read_only=True)
    content_type = serializers.CharField(source="business_file.content_type", read_only=True)
    size_bytes = serializers.IntegerField(source="business_file.size_bytes", read_only=True)
    scan_status = serializers.CharField(source="business_file.scan_status", read_only=True)
    generated_by = EmployeeSummarySerializer(source="generated_by_employee", read_only=True)

    class Meta:
        model = QuotationDocument
        fields = [
            "id",
            "file_id",
            "original_name",
            "content_type",
            "size_bytes",
            "scan_status",
            "document_type",
            "is_formal",
            "generated_by",
            "generated_at",
            "snapshot_hash",
        ]


class QuotationDispatchSerializer(serializers.ModelSerializer):
    dispatched_by = EmployeeSummarySerializer(source="dispatched_by_employee", read_only=True)

    class Meta:
        model = QuotationDispatchRecord
        fields = [
            "id",
            "channel",
            "recipient_snapshot",
            "dispatched_by",
            "dispatched_at",
            "external_reference",
            "follow_up_due_at",
            "follow_up_status",
            "notes",
        ]


class QuotationApprovalSerializer(serializers.ModelSerializer):
    approval_id = serializers.UUIDField(source="approval_request_id", read_only=True)
    status = serializers.CharField(source="approval_request.status", read_only=True)
    approver = EmployeeSummarySerializer(source="approval_request.current_approver_employee", read_only=True)
    requested_by = EmployeeSummarySerializer(source="approval_request.requested_by_employee", read_only=True)
    request_reason = serializers.CharField(source="approval_request.request_reason", read_only=True)
    decision_note = serializers.CharField(source="approval_request.decision_note", read_only=True)
    submitted_at = serializers.DateTimeField(source="approval_request.submitted_at", read_only=True)
    decided_at = serializers.DateTimeField(source="approval_request.decided_at", read_only=True)

    class Meta:
        model = QuotationVersionApprovalLink
        fields = [
            "id",
            "approval_id",
            "status",
            "approver",
            "requested_by",
            "request_reason",
            "decision_note",
            "submitted_at",
            "decided_at",
        ]


class QuotationVersionListSerializer(serializers.ModelSerializer):
    template_code = serializers.CharField(source="quotation_template.template_code", allow_null=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    locked_by = EmployeeSummarySerializer(source="locked_by_employee", allow_null=True, read_only=True)

    class Meta:
        model = QuotationVersion
        fields = [
            "id",
            "quotation",
            "version_number",
            "status",
            "status_display",
            "template_code",
            "currency_code",
            "language_code",
            "subtotal_amount",
            "discount_amount",
            "tax_amount",
            "total_amount",
            "valid_until",
            "locked_at",
            "locked_by",
            "issued_at",
            "created_at",
            "updated_at",
        ]


class QuotationVersionDetailSerializer(QuotationVersionListSerializer):
    lines = QuotationLineSerializer(many=True, read_only=True)
    documents = QuotationDocumentSerializer(many=True, read_only=True)
    dispatches = QuotationDispatchSerializer(source="dispatch_records", many=True, read_only=True)
    approvals = QuotationApprovalSerializer(source="approval_links", many=True, read_only=True)

    class Meta(QuotationVersionListSerializer.Meta):
        fields = QuotationVersionListSerializer.Meta.fields + [
            "quotation_template",
            "transaction_entity_snapshot",
            "address_snapshot",
            "contact_snapshot",
            "template_snapshot",
            "terms_snapshot",
            "notes",
            "lines",
            "documents",
            "dispatches",
            "approvals",
        ]


class QuotationListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer_account.account_name", read_only=True)
    owner = EmployeeSummarySerializer(source="owner_employee", read_only=True)
    outcome_status_display = serializers.CharField(source="get_outcome_status_display", read_only=True)

    class Meta:
        model = Quotation
        fields = [
            "id",
            "quotation_number",
            "customer_account",
            "customer_name",
            "transaction_entity",
            "source_inquiry",
            "owner",
            "outcome_status",
            "outcome_status_display",
            "accepted_version",
            "subject",
            "outcome_note",
            "archived_at",
            "created_at",
            "updated_at",
        ]


class QuotationDetailSerializer(QuotationListSerializer):
    versions = QuotationVersionListSerializer(many=True, read_only=True)

    class Meta(QuotationListSerializer.Meta):
        fields = QuotationListSerializer.Meta.fields + ["versions"]


class QuotationWritableSerializer(serializers.ModelSerializer):
    transaction_entity_id = serializers.PrimaryKeyRelatedField(
        source="transaction_entity",
        queryset=CustomerTransactionEntity.objects.filter(archived_at__isnull=True),
    )
    source_inquiry_id = serializers.PrimaryKeyRelatedField(
        source="source_inquiry",
        required=False,
        allow_null=True,
        queryset=Inquiry.objects.filter(archived_at__isnull=True),
    )
    owner_employee_id = serializers.PrimaryKeyRelatedField(
        source="owner_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )

    def validate(self, attrs):
        customer = attrs.get("customer_account", getattr(self.instance, "customer_account", None))
        entity = attrs.get("transaction_entity", getattr(self.instance, "transaction_entity", None))
        inquiry = attrs.get("source_inquiry", getattr(self.instance, "source_inquiry", None))
        errors = {}
        if entity and entity.customer_account_id != customer.pk:
            errors["transaction_entity_id"] = "交易主体必须属于当前客户。"
        if inquiry and inquiry.customer_account_id != customer.pk:
            errors["source_inquiry_id"] = "来源询价必须属于当前客户。"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class QuotationCreateSerializer(QuotationWritableSerializer):
    customer_account_id = serializers.PrimaryKeyRelatedField(
        source="customer_account",
        queryset=CustomerAccount.objects.filter(archived_at__isnull=True),
    )

    class Meta:
        model = Quotation
        fields = [
            "customer_account_id",
            "transaction_entity_id",
            "source_inquiry_id",
            "owner_employee_id",
            "subject",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not getattr(request.user, "is_authenticated", False):
            return
        allowed = accessible_customers(request, "add_quotation").filter(archived_at__isnull=True)
        self.fields["customer_account_id"].queryset = allowed
        self.fields["transaction_entity_id"].queryset = CustomerTransactionEntity.objects.filter(
            customer_account__in=allowed, archived_at__isnull=True
        )
        self.fields["source_inquiry_id"].queryset = Inquiry.objects.filter(
            customer_account__in=allowed, archived_at__isnull=True
        )


class QuotationUpdateSerializer(QuotationWritableSerializer):
    class Meta:
        model = Quotation
        fields = ["transaction_entity_id", "source_inquiry_id", "owner_employee_id", "subject"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is None:
            return
        customer = self.instance.customer_account
        self.fields["transaction_entity_id"].queryset = CustomerTransactionEntity.objects.filter(
            customer_account=customer, archived_at__isnull=True
        )
        self.fields["source_inquiry_id"].queryset = Inquiry.objects.filter(
            customer_account=customer, archived_at__isnull=True
        )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        return super().validate(attrs)


class QuotationVersionCreateSerializer(serializers.ModelSerializer):
    quotation_template_id = serializers.PrimaryKeyRelatedField(
        source="quotation_template",
        required=False,
        allow_null=True,
        queryset=QuotationTemplate.objects.filter(archived_at__isnull=True),
    )
    from_version_id = serializers.PrimaryKeyRelatedField(
        source="from_version",
        required=False,
        allow_null=True,
        queryset=QuotationVersion.objects.all(),
    )
    currency_code = serializers.CharField(required=False, max_length=3, validators=[currency_code_validator])

    class Meta:
        model = QuotationVersion
        fields = [
            "quotation_template_id",
            "from_version_id",
            "currency_code",
            "language_code",
            "valid_until",
            "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        quotation = self.context.get("quotation")
        if quotation:
            self.fields["from_version_id"].queryset = QuotationVersion.objects.filter(quotation=quotation)

    def validate(self, attrs):
        if not attrs.get("from_version") and not attrs.get("currency_code"):
            raise serializers.ValidationError({"currency_code": "新建首个版本时必须填写币种。"})
        if attrs.get("valid_until") and attrs["valid_until"] < timezone.localdate():
            raise serializers.ValidationError({"valid_until": "报价有效期不能早于今天。"})
        return attrs


class QuotationVersionUpdateSerializer(serializers.ModelSerializer):
    quotation_template_id = serializers.PrimaryKeyRelatedField(
        source="quotation_template",
        required=False,
        allow_null=True,
        queryset=QuotationTemplate.objects.filter(archived_at__isnull=True),
    )
    currency_code = serializers.CharField(required=False, max_length=3, validators=[currency_code_validator])

    class Meta:
        model = QuotationVersion
        fields = ["quotation_template_id", "currency_code", "language_code", "valid_until", "notes"]

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        if attrs.get("valid_until") and attrs["valid_until"] < timezone.localdate():
            raise serializers.ValidationError({"valid_until": "报价有效期不能早于今天。"})
        return attrs


class QuotationLockSerializer(serializers.Serializer):
    address_id = serializers.PrimaryKeyRelatedField(
        source="address",
        queryset=CustomerEntityAddress.objects.filter(archived_at__isnull=True),
    )
    contact_id = serializers.PrimaryKeyRelatedField(
        source="contact",
        queryset=CustomerContact.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
    tax_rate = serializers.DecimalField(max_digits=7, decimal_places=6, min_value=0, max_value=1, default=0)
    terms = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        version = self.context["version"]
        quotation = version.quotation
        errors = {}
        if attrs["address"].transaction_entity_id != quotation.transaction_entity_id:
            errors["address_id"] = "地址必须属于报价交易主体。"
        if attrs["contact"].customer_account_id != quotation.customer_account_id:
            errors["contact_id"] = "联系人必须属于报价客户。"
        if not isinstance(attrs.get("terms"), dict):
            errors["terms"] = "条款必须是 JSON 对象。"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class QuotationApprovalSubmitSerializer(serializers.Serializer):
    approver_employee_id = serializers.PrimaryKeyRelatedField(
        source="approver_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class QuotationDocumentCreateSerializer(serializers.Serializer):
    file_id = serializers.PrimaryKeyRelatedField(
        source="business_file",
        queryset=BusinessFile.objects.filter(archived_at__isnull=True, scan_status="CLEAN"),
    )

    def validate_file_id(self, business_file):
        version = self.context["version"]
        actor = getattr(self.context["request"], "employee", None)
        customer_id = version.quotation.customer_account_id
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
        if linked_customer_ids and linked_customer_ids != {customer_id}:
            raise serializers.ValidationError("文件已关联到其他客户，不能跨客户复用。")
        if not linked_customer_ids and business_file.uploaded_by_employee_id != getattr(actor, "pk", None):
            raise serializers.ValidationError("未关联文件只能由上传人首次登记。")
        return business_file


class QuotationDispatchCreateSerializer(serializers.Serializer):
    channel = serializers.CharField(max_length=50, validators=[uppercase_code_validator])
    recipient_snapshot = serializers.JSONField()
    external_reference = serializers.CharField(required=False, allow_blank=True, max_length=250)
    follow_up_due_at = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_recipient_snapshot(self, value):
        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError("收件人快照必须是非空 JSON 对象。")
        return value

    def validate_follow_up_due_at(self, value):
        if value is not None and value <= timezone.now():
            raise serializers.ValidationError("跟进时间必须晚于当前时间。")
        return value


class QuotationAcceptSerializer(serializers.Serializer):
    accepted_version_id = serializers.PrimaryKeyRelatedField(
        source="accepted_version",
        queryset=QuotationVersion.objects.all(),
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        quotation = self.context.get("quotation")
        if quotation:
            self.fields["accepted_version_id"].queryset = QuotationVersion.objects.filter(
                quotation=quotation,
                status__in=["ISSUED", "SENT"],
            )


class QuotationReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class EmptyActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
