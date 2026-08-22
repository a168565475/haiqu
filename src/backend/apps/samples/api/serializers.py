from decimal import Decimal

from django.db.models import Q
from rest_framework import serializers

from apps.core.models import currency_code_validator, uppercase_code_validator
from apps.core.serializers import EmployeeSummarySerializer
from apps.customers.models import CustomerAccount, CustomerContact, CustomerEntityAddress, CustomerTransactionEntity
from apps.customers.selectors import accessible_customers
from apps.files.models import BusinessFile
from apps.inquiries.models import Inquiry
from apps.organizations.models import Employee
from apps.quotations.models import QuotationVersion

from ..models import (
    FeeVerificationStatus,
    SampleFeeDecision,
    SampleFeeRecord,
    SampleFeedback,
    SampleFileLink,
    SampleItem,
    SampleRequest,
    SampleShipment,
    SampleShipmentItem,
    SampleSlaLink,
)


class SampleItemSerializer(serializers.ModelSerializer):
    line_number = serializers.IntegerField(required=False, min_value=1)
    requested_quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0001"),
    )
    unit_code = serializers.CharField(max_length=30, validators=[uppercase_code_validator])

    class Meta:
        model = SampleItem
        fields = [
            "id",
            "line_number",
            "product_description_snapshot",
            "specification_snapshot",
            "requested_quantity",
            "unit_code",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class SampleItemUpdateSerializer(SampleItemSerializer):
    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        return attrs


class SampleFeeRecordSerializer(serializers.ModelSerializer):
    decided_by = EmployeeSummarySerializer(source="decided_by_employee", allow_null=True, read_only=True)

    class Meta:
        model = SampleFeeRecord
        fields = [
            "id",
            "fee_decision",
            "amount",
            "currency_code",
            "verification_status",
            "decision_reason",
            "decided_by",
            "decided_at",
            "superseded_at",
            "created_at",
        ]


class SampleFeeRecordCreateSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    currency_code = serializers.CharField(max_length=3, validators=[currency_code_validator])

    class Meta:
        model = SampleFeeRecord
        fields = [
            "fee_decision",
            "amount",
            "currency_code",
            "verification_status",
            "decision_reason",
        ]

    def validate(self, attrs):
        decision = attrs["fee_decision"]
        amount = attrs["amount"]
        verification = attrs["verification_status"]
        errors = {}
        if decision == SampleFeeDecision.PAID:
            if amount <= 0:
                errors["amount"] = "收费样品的金额必须大于 0。"
            if verification == FeeVerificationStatus.NOT_REQUIRED:
                errors["verification_status"] = "收费样品不能标记为无需确认。"
        elif decision in {SampleFeeDecision.FREE, SampleFeeDecision.WAIVED}:
            if amount != 0:
                errors["amount"] = "免费或减免时金额必须为 0。"
            if verification != FeeVerificationStatus.NOT_REQUIRED:
                errors["verification_status"] = "免费或减免时应标记为无需确认。"
        elif decision == SampleFeeDecision.PENDING and amount != 0:
            errors["amount"] = "待决定时金额必须为 0。"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class SampleShipmentItemSerializer(serializers.ModelSerializer):
    sample_item_id = serializers.PrimaryKeyRelatedField(source="sample_item", queryset=SampleItem.objects.all())
    product_description = serializers.CharField(
        source="sample_item.product_description_snapshot",
        read_only=True,
    )
    shipped_quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0001"),
    )

    class Meta:
        model = SampleShipmentItem
        fields = ["id", "sample_item_id", "product_description", "shipped_quantity"]
        read_only_fields = ["id"]


class SampleShipmentSerializer(serializers.ModelSerializer):
    shipped_by = EmployeeSummarySerializer(source="shipped_by_employee", allow_null=True, read_only=True)
    fee_warning_acknowledged_by = EmployeeSummarySerializer(
        source="fee_warning_acknowledged_by_employee",
        allow_null=True,
        read_only=True,
    )
    items = SampleShipmentItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SampleShipment
        fields = [
            "id",
            "status",
            "status_display",
            "carrier_code",
            "tracking_number",
            "recipient_snapshot",
            "address_snapshot",
            "shipped_by",
            "shipped_at",
            "delivered_at",
            "fee_warning_acknowledged",
            "fee_warning_acknowledged_by",
            "fee_warning_acknowledged_at",
            "notes",
            "items",
            "created_at",
            "updated_at",
        ]


class SampleShipmentCreateSerializer(serializers.Serializer):
    items = SampleShipmentItemSerializer(many=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_items(self, items):
        request_obj = self.context["sample_request"]
        if not items:
            raise serializers.ValidationError("寄送记录至少包含一条明细。")
        ids = [item["sample_item"].pk for item in items]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("寄送明细不能重复。")
        if any(item["sample_item"].sample_request_id != request_obj.pk for item in items):
            raise serializers.ValidationError("寄送明细必须属于当前样品申请。")
        return items


class SampleShipSerializer(serializers.Serializer):
    address_id = serializers.PrimaryKeyRelatedField(
        source="address",
        queryset=CustomerEntityAddress.objects.filter(archived_at__isnull=True),
    )
    contact_id = serializers.PrimaryKeyRelatedField(
        source="contact",
        queryset=CustomerContact.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
    carrier_code = serializers.CharField(max_length=50, validators=[uppercase_code_validator])
    tracking_number = serializers.CharField(max_length=150)
    fee_warning_acknowledged = serializers.BooleanField(default=False)
    fee_warning_reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        shipment = self.context["shipment"]
        sample_request = shipment.sample_request
        errors = {}
        address = attrs["address"]
        if sample_request.transaction_entity_id:
            if address.transaction_entity_id != sample_request.transaction_entity_id:
                errors["address_id"] = "寄送地址必须属于样品申请交易主体。"
        elif address.transaction_entity.customer_account_id != sample_request.customer_account_id:
            errors["address_id"] = "寄送地址必须属于样品申请客户。"
        if attrs["contact"].customer_account_id != sample_request.customer_account_id:
            errors["contact_id"] = "收件联系人必须属于样品申请客户。"
        if attrs["fee_warning_acknowledged"] and not attrs.get("fee_warning_reason", "").strip():
            errors["fee_warning_reason"] = "确认收费风险时必须填写原因。"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class SampleFeedbackSerializer(serializers.ModelSerializer):
    customer_contact = serializers.PrimaryKeyRelatedField(read_only=True)
    recorded_by = EmployeeSummarySerializer(source="recorded_by_employee", allow_null=True, read_only=True)
    feedback_type_display = serializers.CharField(source="get_feedback_type_display", read_only=True)

    class Meta:
        model = SampleFeedback
        fields = [
            "id",
            "customer_contact",
            "recorded_by",
            "feedback_type",
            "feedback_type_display",
            "feedback_content",
            "occurred_at",
            "created_at",
        ]


class SampleFeedbackCreateSerializer(serializers.ModelSerializer):
    customer_contact_id = serializers.PrimaryKeyRelatedField(
        source="customer_contact",
        required=False,
        allow_null=True,
        queryset=CustomerContact.objects.filter(archived_at__isnull=True),
    )

    class Meta:
        model = SampleFeedback
        fields = ["customer_contact_id", "feedback_type", "feedback_content", "occurred_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sample_request = self.context.get("sample_request")
        if sample_request:
            self.fields["customer_contact_id"].queryset = CustomerContact.objects.filter(
                customer_account=sample_request.customer_account,
                archived_at__isnull=True,
            )


class SampleFileLinkSerializer(serializers.ModelSerializer):
    file_id = serializers.UUIDField(source="business_file_id", read_only=True)
    original_name = serializers.CharField(source="business_file.original_name", read_only=True)
    scan_status = serializers.CharField(source="business_file.scan_status", read_only=True)

    class Meta:
        model = SampleFileLink
        fields = ["id", "file_id", "original_name", "scan_status", "file_role", "created_at"]


class SampleFileLinkCreateSerializer(serializers.Serializer):
    file_id = serializers.PrimaryKeyRelatedField(
        source="business_file",
        queryset=BusinessFile.objects.filter(archived_at__isnull=True),
    )
    file_role = serializers.CharField(max_length=50, validators=[uppercase_code_validator])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sample_request = self.context.get("sample_request")
        request = self.context.get("request")
        if sample_request is None or request is None:
            self.fields["file_id"].queryset = BusinessFile.objects.none()
            return
        actor = getattr(request, "employee", None)
        self.fields["file_id"].queryset = BusinessFile.objects.filter(
            Q(uploaded_by_employee=actor)
            | Q(customer_links__customer_account=sample_request.customer_account)
            | Q(communication_links__communication__customer_account=sample_request.customer_account)
            | Q(inquiry_links__inquiry__customer_account=sample_request.customer_account)
            | Q(quotation_links__quotation_version__quotation__customer_account=sample_request.customer_account)
            | Q(sample_links__sample_request__customer_account=sample_request.customer_account),
            archived_at__isnull=True,
        ).distinct()

    def validate_file_id(self, business_file):
        sample_request = self.context["sample_request"]
        actor = getattr(self.context["request"], "employee", None)
        customer_id = sample_request.customer_account_id
        linked_ids = set(business_file.customer_links.values_list("customer_account_id", flat=True))
        linked_ids.update(
            business_file.communication_links.values_list("communication__customer_account_id", flat=True)
        )
        linked_ids.update(business_file.inquiry_links.values_list("inquiry__customer_account_id", flat=True))
        linked_ids.update(
            business_file.quotation_links.values_list(
                "quotation_version__quotation__customer_account_id", flat=True
            )
        )
        linked_ids.update(business_file.sample_links.values_list("sample_request__customer_account_id", flat=True))
        if linked_ids and linked_ids != {customer_id}:
            raise serializers.ValidationError("文件已关联到其他客户，不能跨客户复用。")
        if not linked_ids and business_file.uploaded_by_employee_id != getattr(actor, "pk", None):
            raise serializers.ValidationError("未关联文件只能由上传人首次挂接。")
        return business_file


class SampleSlaSerializer(serializers.ModelSerializer):
    policy_code = serializers.CharField(source="sla_tracking.sla_policy.policy_code", read_only=True)
    status = serializers.CharField(source="sla_tracking.status", read_only=True)
    started_at = serializers.DateTimeField(source="sla_tracking.started_at", read_only=True)
    next_deadline_at = serializers.DateTimeField(source="sla_tracking.next_deadline_at", read_only=True)
    breached_at = serializers.DateTimeField(source="sla_tracking.breached_at", read_only=True)
    completed_at = serializers.DateTimeField(source="sla_tracking.completed_at", read_only=True)

    class Meta:
        model = SampleSlaLink
        fields = ["id", "policy_code", "status", "started_at", "next_deadline_at", "breached_at", "completed_at"]


class SampleRequestListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer_account.account_name", read_only=True)
    owner = EmployeeSummarySerializer(source="owner_employee", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SampleRequest
        fields = [
            "id",
            "request_number",
            "customer_account",
            "customer_name",
            "owner",
            "status",
            "status_display",
            "requested_at",
            "requested_due_at",
            "archived_at",
            "created_at",
            "updated_at",
        ]


class SampleRequestDetailSerializer(SampleRequestListSerializer):
    items = SampleItemSerializer(many=True, read_only=True)
    fee_records = SampleFeeRecordSerializer(many=True, read_only=True)
    shipments = SampleShipmentSerializer(many=True, read_only=True)
    feedback = SampleFeedbackSerializer(source="feedback_records", many=True, read_only=True)
    files = SampleFileLinkSerializer(source="file_links", many=True, read_only=True)
    sla = SampleSlaSerializer(source="sla_links", many=True, read_only=True)

    class Meta(SampleRequestListSerializer.Meta):
        fields = SampleRequestListSerializer.Meta.fields + [
            "transaction_entity",
            "customer_contact",
            "source_inquiry",
            "source_quotation_version",
            "purpose",
            "notes",
            "items",
            "fee_records",
            "shipments",
            "feedback",
            "files",
            "sla",
        ]


class SampleRequestWritableSerializer(serializers.ModelSerializer):
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
    source_inquiry_id = serializers.PrimaryKeyRelatedField(
        source="source_inquiry",
        required=False,
        allow_null=True,
        queryset=Inquiry.objects.filter(archived_at__isnull=True),
    )
    source_quotation_version_id = serializers.PrimaryKeyRelatedField(
        source="source_quotation_version",
        required=False,
        allow_null=True,
        queryset=QuotationVersion.objects.all(),
    )

    def validate(self, attrs):
        customer = attrs.get("customer_account", getattr(self.instance, "customer_account", None))
        entity = attrs.get("transaction_entity", getattr(self.instance, "transaction_entity", None))
        contact = attrs.get("customer_contact", getattr(self.instance, "customer_contact", None))
        inquiry = attrs.get("source_inquiry", getattr(self.instance, "source_inquiry", None))
        quote = attrs.get("source_quotation_version", getattr(self.instance, "source_quotation_version", None))
        errors = {}
        if entity and entity.customer_account_id != customer.pk:
            errors["transaction_entity_id"] = "交易主体必须属于当前客户。"
        if contact and contact.customer_account_id != customer.pk:
            errors["customer_contact_id"] = "联系人必须属于当前客户。"
        if inquiry and inquiry.customer_account_id != customer.pk:
            errors["source_inquiry_id"] = "来源询价必须属于当前客户。"
        if quote and quote.quotation.customer_account_id != customer.pk:
            errors["source_quotation_version_id"] = "来源报价版本必须属于当前客户。"
        if inquiry and quote:
            errors["source_quotation_version_id"] = "来源询价和来源报价版本最多填写一个。"
        requested_at = attrs.get("requested_at", getattr(self.instance, "requested_at", None))
        requested_due_at = attrs.get(
            "requested_due_at",
            getattr(self.instance, "requested_due_at", None),
        )
        if requested_due_at and requested_at and requested_due_at <= requested_at:
            errors["requested_due_at"] = "期望完成时间必须晚于申请时间。"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class SampleRequestCreateSerializer(SampleRequestWritableSerializer):
    customer_account_id = serializers.PrimaryKeyRelatedField(
        source="customer_account",
        queryset=CustomerAccount.objects.filter(archived_at__isnull=True),
    )
    items = SampleItemSerializer(many=True, required=False)

    class Meta:
        model = SampleRequest
        fields = [
            "customer_account_id",
            "transaction_entity_id",
            "customer_contact_id",
            "owner_employee_id",
            "source_inquiry_id",
            "source_quotation_version_id",
            "purpose",
            "requested_at",
            "requested_due_at",
            "notes",
            "items",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not getattr(request.user, "is_authenticated", False):
            return
        allowed = accessible_customers(request, "add_samplerequest").filter(archived_at__isnull=True)
        self.fields["customer_account_id"].queryset = allowed
        self.fields["transaction_entity_id"].queryset = CustomerTransactionEntity.objects.filter(
            customer_account__in=allowed, archived_at__isnull=True
        )
        self.fields["customer_contact_id"].queryset = CustomerContact.objects.filter(
            customer_account__in=allowed, archived_at__isnull=True
        )
        self.fields["source_inquiry_id"].queryset = Inquiry.objects.filter(
            customer_account__in=allowed, archived_at__isnull=True
        )
        self.fields["source_quotation_version_id"].queryset = QuotationVersion.objects.filter(
            quotation__customer_account__in=allowed,
            quotation__archived_at__isnull=True,
        )

    def validate_items(self, items):
        if len(items) > 200:
            raise serializers.ValidationError("单张样品申请最多包含 200 条明细。")
        numbers = [item.get("line_number") for item in items if item.get("line_number") is not None]
        if len(numbers) != len(set(numbers)):
            raise serializers.ValidationError("明细行号不能重复。")
        return items


class SampleRequestUpdateSerializer(SampleRequestWritableSerializer):
    class Meta:
        model = SampleRequest
        fields = [
            "transaction_entity_id",
            "customer_contact_id",
            "owner_employee_id",
            "source_inquiry_id",
            "source_quotation_version_id",
            "purpose",
            "requested_at",
            "requested_due_at",
            "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is None:
            return
        customer = self.instance.customer_account
        self.fields["transaction_entity_id"].queryset = CustomerTransactionEntity.objects.filter(
            customer_account=customer, archived_at__isnull=True
        )
        self.fields["customer_contact_id"].queryset = CustomerContact.objects.filter(
            customer_account=customer, archived_at__isnull=True
        )
        self.fields["source_inquiry_id"].queryset = Inquiry.objects.filter(
            customer_account=customer, archived_at__isnull=True
        )
        self.fields["source_quotation_version_id"].queryset = QuotationVersion.objects.filter(
            quotation__customer_account=customer,
            quotation__archived_at__isnull=True,
        )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        return super().validate(attrs)


class SampleActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class SampleReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)
