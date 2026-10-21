from apps.access_control.module_policy import can_sample, enabled as module_access_enabled
from apps.access_control.module_policy import ModuleAccessSerializerMixin
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.models import currency_code_validator, uppercase_code_validator
from apps.core.api.concurrency import etag_for_instance
from apps.core.serializers import EmployeeSummarySerializer
from apps.customers.models import CustomerAccount, CustomerContact, CustomerEntityAddress, CustomerTransactionEntity
from apps.customers.selectors import accessible_customers
from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
from apps.inquiries.models import Inquiry, InquiryItem
from apps.organizations.models import Employee
from apps.reference_data.models import Currency, ReferenceStatus
from apps.quotations.models import QuotationLine, QuotationVersion, QuotationVersionStatus

from ..models import (
    FeeVerificationStatus,
    FeedbackConfirmationResult,
    FreightBearer,
    SampleFeeDecision,
    SampleFeeRecord,
    SampleFeedback,
    SampleFileLink,
    SampleParameterImage,
    SampleItem,
    SampleRequest,
    SampleRequestStatus,
    SampleShipment,
    SampleShipmentEvent,
    SampleShipmentItem,
    SampleSlaLink,
    SampleApprovalLink,
    SampleType,
    SampleWorkflowRecord,
)
from ..form_services import sample_form_edit_capabilities
from ..application_services import application_actions
from .form_serializers import SampleFormProductReadSerializer


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
            "source_inquiry_item",
            "source_quotation_line",
            "product_description_snapshot",
            "specification_snapshot",
            "requested_quantity",
            "unit_code",
            "sample_product",
            "product_color",
            "color_card_snapshot",
            "color_name_snapshot",
            "color_code_snapshot",
            "tolerance",
            "sample_quantity",
            "cutting_reported_quantity",
            "metalwork_reported_quantity",
            "cutting_completed",
            "metalwork_completed",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "source_inquiry_item",
            "source_quotation_line",
            "sample_product",
            "product_color",
            "created_at",
            "updated_at",
        ]


class SampleItemUpdateSerializer(SampleItemSerializer):
    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        return attrs


class SampleFeeRecordSerializer(serializers.ModelSerializer):
    decided_by = EmployeeSummarySerializer(source="decided_by_employee", allow_null=True, read_only=True)
    fee_decision_display = serializers.CharField(source="get_fee_decision_display", read_only=True)
    approval_status_display = serializers.CharField(source="get_approval_status_display", read_only=True)
    verification_status_display = serializers.CharField(source="get_verification_status_display", read_only=True)
    free_confirmed_by = EmployeeSummarySerializer(
        source="free_confirmed_by_employee",
        allow_null=True,
        read_only=True,
    )

    class Meta:
        model = SampleFeeRecord
        fields = [
            "id",
            "fee_decision",
            "fee_decision_display",
            "requested_decision",
            "amount",
            "currency_code",
            "sample_fee_amount",
            "shipping_fee_amount",
            "discount_amount",
            "payable_amount",
            "payment_terms",
            "freight_bearer",
            "payment_due_at",
            "account_reference",
            "approval_status",
            "approval_status_display",
            "verification_status",
            "verification_status_display",
            "decision_reason",
            "decided_by",
            "free_confirmed_by",
            "decided_at",
            "superseded_at",
            "created_at",
        ]


class SampleFeeRecordCreateSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"), required=False)
    currency_code = serializers.CharField(max_length=3, validators=[currency_code_validator])
    sample_fee_amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"), required=False)
    shipping_fee_amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"), required=False)
    discount_amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"), required=False)
    payment_terms = serializers.CharField(max_length=200, required=False, allow_blank=True)
    freight_bearer = serializers.ChoiceField(choices=FreightBearer.choices, required=False, allow_blank=True)
    payment_due_at = serializers.DateTimeField(required=False, allow_null=True)
    free_confirmed_by_employee_id = serializers.PrimaryKeyRelatedField(
        source="free_confirmed_by_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    approver_employee_id = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = SampleFeeRecord
        fields = [
            "fee_decision",
            "amount",
            "currency_code",
            "sample_fee_amount",
            "shipping_fee_amount",
            "discount_amount",
            "payment_terms",
            "freight_bearer",
            "payment_due_at",
            "verification_status",
            "decision_reason",
            "free_confirmed_by_employee_id",
            "approver_employee_id",
        ]

    def validate_currency_code(self, value):
        normalized = value.strip().upper()
        if not Currency.objects.filter(
            code=normalized,
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).exists():
            raise serializers.ValidationError("币种不存在、已停用或尚未启用。")
        return normalized

    def validate(self, attrs):
        decision = attrs["fee_decision"]
        # 兼容已有调用方仍传 amount；新页面只传拆分后的费用字段。
        sample_fee = attrs.get("sample_fee_amount", attrs.get("amount", Decimal("0")))
        shipping_fee = attrs.get("shipping_fee_amount", Decimal("0"))
        discount = attrs.get("discount_amount", Decimal("0"))
        payable = sample_fee + shipping_fee - discount
        verification = attrs.get("verification_status", FeeVerificationStatus.PENDING)
        reason = attrs.get("decision_reason", "").strip()
        freight_bearer = attrs.get("freight_bearer", "")
        errors = {}
        if decision == SampleFeeDecision.PAID:
            if payable <= 0:
                errors["sample_fee_amount"] = "收费样品的应付合计必须大于 0。"
            if discount > sample_fee + shipping_fee:
                errors["discount_amount"] = "折扣不能大于样品费与运费之和。"
            if not freight_bearer:
                errors["freight_bearer"] = "收费样品必须明确运费承担方。"
            if verification in {FeeVerificationStatus.NOT_REQUIRED, FeeVerificationStatus.MANUALLY_CONFIRMED}:
                errors["verification_status"] = "收费样品只能等待财务确认或关联付款凭证，不能在页面人工确认到账。"
        elif decision == SampleFeeDecision.FREE:
            if not reason:
                errors["decision_reason"] = "免费样必须填写商业理由。"
            if not freight_bearer:
                errors["freight_bearer"] = "免费样必须明确运费承担方。"
            if not attrs.get("free_confirmed_by_employee"):
                errors["free_confirmed_by_employee_id"] = "免费样必须选择确认人。"
            payable = Decimal("0")
            verification = FeeVerificationStatus.NOT_REQUIRED
        elif decision == SampleFeeDecision.WAIVED:
            if not reason:
                errors["decision_reason"] = "费用豁免必须填写申请原因。"
            if not attrs.get("approver_employee_id"):
                errors["approver_employee_id"] = "费用豁免必须选择审批人。"
            payable = Decimal("0")
            verification = FeeVerificationStatus.NOT_REQUIRED
        elif decision == SampleFeeDecision.PENDING:
            payable = Decimal("0")
            verification = FeeVerificationStatus.NOT_REQUIRED
        if errors:
            raise serializers.ValidationError(errors)
        attrs["sample_fee_amount"] = sample_fee
        attrs["shipping_fee_amount"] = shipping_fee
        attrs["discount_amount"] = discount
        attrs["payable_amount"] = payable
        attrs["amount"] = payable
        attrs["verification_status"] = verification
        return attrs


class SampleApprovalLinkSerializer(serializers.ModelSerializer):
    approval_id = serializers.UUIDField(source="approval_request_id", read_only=True)
    status = serializers.CharField(source="approval_request.status", read_only=True)
    status_display = serializers.CharField(source="approval_request.get_status_display", read_only=True)
    approver = EmployeeSummarySerializer(source="approval_request.current_approver_employee", read_only=True)
    requested_by = EmployeeSummarySerializer(source="approval_request.requested_by_employee", allow_null=True, read_only=True)
    request_reason = serializers.CharField(source="approval_request.request_reason", read_only=True)
    decision_note = serializers.CharField(source="approval_request.decision_note", read_only=True)
    submitted_at = serializers.DateTimeField(source="approval_request.submitted_at", read_only=True)
    decided_at = serializers.DateTimeField(source="approval_request.decided_at", read_only=True)

    class Meta:
        model = SampleApprovalLink
        fields = [
            "id", "approval_id", "status", "status_display", "approver", "requested_by",
            "request_reason", "decision_note", "submitted_at", "decided_at", "created_at",
        ]


class SampleApprovalDecisionSerializer(serializers.Serializer):
    approval_id = serializers.UUIDField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)


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


class SampleShipmentEventSerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(source="get_event_type_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    recorded_by = EmployeeSummarySerializer(source="recorded_by_employee", allow_null=True, read_only=True)

    class Meta:
        model = SampleShipmentEvent
        fields = [
            "id", "event_type", "event_type_display", "source", "source_display",
            "event_identifier", "source_object_version", "occurred_at", "synchronized_at",
            "payload_snapshot", "recorded_by", "created_at",
        ]


class SampleShipmentSerializer(serializers.ModelSerializer):
    shipped_by = EmployeeSummarySerializer(source="shipped_by_employee", allow_null=True, read_only=True)
    fee_warning_acknowledged_by = EmployeeSummarySerializer(
        source="fee_warning_acknowledged_by_employee",
        allow_null=True,
        read_only=True,
    )
    items = SampleShipmentItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    recipient_summary = serializers.SerializerMethodField()
    events = SampleShipmentEventSerializer(many=True, read_only=True)

    def get_recipient_summary(self, instance):
        """详情页只显示脱敏收件摘要，原始姓名、电话和地址不下发。"""
        recipient = instance.recipient_snapshot or {}
        address = instance.address_snapshot or {}
        name = recipient.get("display_name") or recipient.get("name") or ""
        location = address.get("city") or address.get("country_code") or ""
        return {"recipient_name": f"{str(name)[:1]}**" if name else "未维护", "location": location or "未维护"}

    class Meta:
        model = SampleShipment
        fields = [
            "id",
            "status",
            "status_display",
            "carrier_code",
            "tracking_number",
            "recipient_summary",
            "shipped_by",
            "shipped_at",
            "delivered_at",
            "fee_warning_acknowledged",
            "fee_warning_acknowledged_by",
            "fee_warning_acknowledged_at",
            "notes",
            "items",
            "events",
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
    confirmation_result_display = serializers.CharField(source="get_confirmation_result_display", read_only=True)
    confirmation_source_display = serializers.CharField(source="get_confirmation_source_display", read_only=True)
    requotation_source_label = serializers.SerializerMethodField()
    resulting_quotation_id = serializers.SerializerMethodField()
    resulting_quotation_label = serializers.SerializerMethodField()
    requotation_created_by = EmployeeSummarySerializer(
        source="requotation_created_by_employee",
        allow_null=True,
        read_only=True,
    )

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
            "confirmation_result",
            "confirmation_result_display",
            "confirmation_source",
            "confirmation_source_display",
            "source_object_version",
            "rejection_reason",
            "corrective_action_request",
            "confirmed_at",
            "requotation_source_version",
            "requotation_source_label",
            "resulting_quotation_version",
            "resulting_quotation_id",
            "resulting_quotation_label",
            "requotation_created_by",
            "requotation_created_at",
            "created_at",
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_requotation_source_label(self, obj):
        if not obj.requotation_source_version_id:
            return ""
        version = obj.requotation_source_version
        return f"{version.quotation.quotation_number} V{version.version_number}"

    @extend_schema_field(OpenApiTypes.UUID)
    def get_resulting_quotation_id(self, obj):
        if not obj.resulting_quotation_version_id:
            return None
        return obj.resulting_quotation_version.quotation_id

    @extend_schema_field(OpenApiTypes.STR)
    def get_resulting_quotation_label(self, obj):
        if not obj.resulting_quotation_version_id:
            return ""
        version = obj.resulting_quotation_version
        return f"{version.quotation.quotation_number} V{version.version_number}"


class SampleFeedbackCreateSerializer(serializers.ModelSerializer):
    customer_contact_id = serializers.PrimaryKeyRelatedField(
        source="customer_contact",
        required=False,
        allow_null=True,
        queryset=CustomerContact.objects.filter(archived_at__isnull=True),
    )

    class Meta:
        model = SampleFeedback
        fields = [
            "customer_contact_id", "feedback_type", "feedback_content", "occurred_at",
            "confirmation_result", "confirmation_source", "source_object_version",
            "rejection_reason", "corrective_action_request",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sample_request = self.context.get("sample_request")
        if sample_request:
            self.fields["customer_contact_id"].queryset = CustomerContact.objects.filter(
                customer_account=sample_request.customer_account,
                archived_at__isnull=True,
            )

    def validate(self, attrs):
        if "confirmation_result" not in attrs:
            if attrs["feedback_type"] == "POSITIVE":
                attrs["confirmation_result"] = FeedbackConfirmationResult.PASSED
            elif attrs["feedback_type"] == "NEGATIVE":
                attrs["confirmation_result"] = FeedbackConfirmationResult.REJECTED
            else:
                attrs["confirmation_result"] = FeedbackConfirmationResult.PENDING
        if attrs["confirmation_result"] == FeedbackConfirmationResult.REJECTED:
            if not attrs.get("rejection_reason", "").strip():
                raise serializers.ValidationError({"rejection_reason": "确认未通过时必须填写原因。"})
        if attrs["confirmation_result"] != FeedbackConfirmationResult.PENDING:
            attrs["confirmed_at"] = timezone.now()
        return attrs


class SampleRequotationCreateSerializer(serializers.Serializer):
    source_quotation_version_id = serializers.PrimaryKeyRelatedField(
        source="source_version",
        queryset=QuotationVersion.objects.none(),
    )
    valid_until = serializers.DateField()
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=2000,
        trim_whitespace=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sample_request = self.context.get("sample_request")
        if sample_request is not None:
            self.fields["source_quotation_version_id"].queryset = QuotationVersion.objects.filter(
                quotation__customer_account=sample_request.customer_account,
                quotation__archived_at__isnull=True,
                lines__isnull=False,
            ).exclude(status=QuotationVersionStatus.VOID).select_related("quotation").distinct()

    def validate_valid_until(self, value):
        if value < timezone.localdate():
            raise serializers.ValidationError("报价有效期不能早于今天。")
        return value


class SampleRequotationOptionSerializer(serializers.Serializer):
    quotation_id = serializers.UUIDField()
    quotation_number = serializers.CharField()
    quotation_outcome_status = serializers.CharField()
    version_id = serializers.UUIDField()
    version_number = serializers.IntegerField()
    version_status = serializers.CharField()
    currency_code = serializers.CharField()
    subject = serializers.CharField()
    updated_at = serializers.DateTimeField()
    is_sample_source = serializers.BooleanField()
    target_mode = serializers.ChoiceField(choices=["APPEND_VERSION", "CREATE_QUOTATION"])
    target_label = serializers.CharField()


class SampleRequotationResultSerializer(serializers.Serializer):
    quotation_id = serializers.UUIDField()
    quotation_number = serializers.CharField()
    quotation_version_id = serializers.UUIDField()
    version_number = serializers.IntegerField()
    created_new_quotation = serializers.BooleanField()
    replayed = serializers.BooleanField()


class SampleFileLinkSerializer(serializers.ModelSerializer):
    file_id = serializers.UUIDField(source="business_file_id", read_only=True)
    original_name = serializers.CharField(source="business_file.original_name", read_only=True)
    scan_status = serializers.CharField(source="business_file.scan_status", read_only=True)
    content_type = serializers.CharField(source="business_file.content_type", read_only=True)
    size_bytes = serializers.IntegerField(source="business_file.size_bytes", read_only=True)
    uploaded_by = EmployeeSummarySerializer(source="business_file.uploaded_by_employee", read_only=True)

    class Meta:
        model = SampleFileLink
        fields = [
            "id",
            "file_id",
            "original_name",
            "scan_status",
            "content_type",
            "size_bytes",
            "uploaded_by",
            "file_role",
            "created_at",
        ]


class SampleParameterImageSerializer(serializers.ModelSerializer):
    parameter_type_display = serializers.CharField(source="get_parameter_type_display", read_only=True)
    file_id = serializers.UUIDField(source="business_file_id", read_only=True)
    file_name = serializers.CharField(source="business_file.original_name", read_only=True)
    content_type = serializers.CharField(source="business_file.content_type", read_only=True)
    size_bytes = serializers.IntegerField(source="business_file.size_bytes", read_only=True)
    operator = EmployeeSummarySerializer(source="uploaded_by_employee", allow_null=True, read_only=True)

    class Meta:
        model = SampleParameterImage
        fields = [
            "id",
            "parameter_type",
            "parameter_type_display",
            "file_id",
            "file_name",
            "content_type",
            "size_bytes",
            "operator",
            "uploaded_at",
        ]


class SampleWorkflowRecordSerializer(serializers.ModelSerializer):
    stage_display = serializers.CharField(source="get_stage_display", read_only=True)
    file_id = serializers.UUIDField(source="business_file_id", allow_null=True, read_only=True)
    file_name = serializers.CharField(source="business_file.original_name", default="", read_only=True)
    file_content_type = serializers.CharField(source="business_file.content_type", default="", read_only=True)
    file_size_bytes = serializers.IntegerField(source="business_file.size_bytes", default=0, read_only=True)
    operator = EmployeeSummarySerializer(source="operated_by_employee", allow_null=True, read_only=True)

    class Meta:
        model = SampleWorkflowRecord
        fields = [
            "id",
            "stage",
            "stage_display",
            "note",
            "file_id",
            "file_name",
            "file_content_type",
            "file_size_bytes",
            "operator",
            "operated_at",
        ]


class SampleWorkflowActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000, trim_whitespace=True)


class SampleFileLinkCreateSerializer(serializers.Serializer):
    file_id = serializers.PrimaryKeyRelatedField(
        source="business_file",
        queryset=BusinessFile.objects.filter(archived_at__isnull=True, scan_status__in=USABLE_FILE_SCAN_STATUSES),
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
            scan_status__in=USABLE_FILE_SCAN_STATUSES,
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


class SampleRequestListProductSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    line_number = serializers.IntegerField()
    category_name = serializers.CharField(source="category_name_snapshot")
    product_name = serializers.CharField()
    specification = serializers.CharField()
    color = serializers.SerializerMethodField()
    task_sheet_file_id = serializers.UUIDField(allow_null=True)
    task_sheet_file_name = serializers.CharField(source="task_sheet_file.original_name", default="")
    length_cm = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    armrest_width_cm = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    seat_width_cm = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    back_height_cm = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    seat_height_cm = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    total_sample_quantity = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField(allow_blank=True))
    def get_color(self, instance) -> str:
        labels = []
        for detail in instance.details.all():
            color = detail.product_color
            values = [
                (detail.color_card_snapshot or (color.color_card if color else '')).strip(),
                (detail.color_code_snapshot or (color.color_code if color else '')).strip(),
                (detail.color_name_snapshot or (color.color_name if color else '')).strip(),
            ]
            label = ' / '.join(value for value in values if value)
            if label and label not in labels:
                labels.append(label)
        return '；'.join(labels)

    @extend_schema_field(OpenApiTypes.INT)
    def get_total_sample_quantity(self, instance) -> int:
        return sum(detail.sample_quantity or 0 for detail in instance.details.all())


class SampleRequestListSerializer(ModuleAccessSerializerMixin, serializers.ModelSerializer):
    edit_capabilities = serializers.SerializerMethodField()

    def get_edit_capabilities(self, instance) -> dict:
        return sample_form_edit_capabilities(instance)

    def get_status_display(self, instance) -> str:
        from ..procurement_status import sample_status_display
        return sample_status_display(instance)

    application_actions = serializers.SerializerMethodField()
    material_summary = serializers.SerializerMethodField()

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_material_summary(self, instance) -> dict | None:
        if not instance.application_payload_hash:
            return None
        from ..material_arrival_services import material_progress
        progress = material_progress(instance)
        return {key: progress[key] for key in ['label', 'status']}

    def get_application_actions(self, instance) -> dict:
        return application_actions(instance, self.context.get('request'))

    customer_name = serializers.CharField(source="customer_account.account_name", read_only=True)
    owner = EmployeeSummarySerializer(source="owner_employee", read_only=True)
    requested_by = EmployeeSummarySerializer(source="requested_by_employee", read_only=True)
    status_display = serializers.SerializerMethodField()
    sample_type_display = serializers.CharField(source="get_sample_type_display", read_only=True)
    shipping_method_display = serializers.CharField(source="get_shipping_method_display", read_only=True)
    delivery_batch_display = serializers.CharField(source="get_delivery_batch_display", read_only=True)
    created_by = EmployeeSummarySerializer(source="created_by_employee", read_only=True)
    products = SampleRequestListProductSerializer(many=True, read_only=True)
    etag = serializers.SerializerMethodField()
    item_summary = serializers.SerializerMethodField()
    current_fee = serializers.SerializerMethodField()
    latest_shipment = serializers.SerializerMethodField()
    waiting_seconds = serializers.SerializerMethodField()

    def get_etag(self, instance):
        return etag_for_instance(instance)

    def get_item_summary(self, instance):
        items = list(instance.items.all())
        if not items:
            return {"text": "暂无明细", "count": 0}
        first_item = items[0]
        suffix = f" 等 {len(items)} 项" if len(items) > 1 else ""
        return {"text": f"{first_item.product_description_snapshot}{suffix}", "count": len(items)}

    def get_current_fee(self, instance):
        fee = next((item for item in instance.fee_records.all() if item.superseded_at is None), None)
        if fee is None:
            return None
        return {
            "fee_decision": fee.fee_decision,
            "fee_decision_display": fee.get_fee_decision_display(),
            "amount": str(fee.amount),
            "currency_code": fee.currency_code,
            "verification_status": fee.verification_status,
            "verification_status_display": fee.get_verification_status_display(),
            "decision_reason": fee.decision_reason,
            "decided_at": fee.decided_at,
            "decided_by": EmployeeSummarySerializer(fee.decided_by_employee).data
            if fee.decided_by_employee_id
            else None,
        }

    def get_latest_shipment(self, instance):
        shipments = list(instance.shipments.all())
        if not shipments:
            return None
        shipment = max(shipments, key=lambda item: (item.shipped_at or item.created_at, item.pk))
        return {
            "status": shipment.status,
            "status_display": shipment.get_status_display(),
            "tracking_number": shipment.tracking_number,
            "carrier_code": shipment.carrier_code,
            "shipped_at": shipment.shipped_at,
            "delivered_at": shipment.delivered_at,
        }

    def get_waiting_seconds(self, instance):
        if instance.status != "PENDING_COMPLETION":
            return None
        return max(0, int((timezone.now() - instance.requested_at).total_seconds()))

    class Meta:
        model = SampleRequest
        fields = [
            "allowed_permissions",
            "edit_capabilities",
            "id",
            "request_number",
            "application_actions",
            "material_summary",
            "intake_number",
            "customer_account",
            "customer_name",
            "owner",
            "requested_by",
            "status",
            "status_display",
            "sample_type",
            "sample_type_display",
            "manual_request_number",
            "shipping_method",
            "shipping_method_display",
            "order_date",
            "sample_due_date",
            "delivery_batch",
            "delivery_batch_display",
            "is_repeat_order",
            "created_by",
            "submitted_on",
            "products",
            "etag",
            "item_summary",
            "current_fee",
            "latest_shipment",
            "waiting_seconds",
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
    fee_approvals = SampleApprovalLinkSerializer(source="approval_links", many=True, read_only=True)
    collaborators = EmployeeSummarySerializer(many=True, read_only=True)
    transaction_entity_name = serializers.CharField(source="transaction_entity.legal_name", default="", read_only=True)
    customer_contact_name = serializers.CharField(source="customer_contact.display_name", default="", read_only=True)
    source_inquiry_number = serializers.CharField(source="source_inquiry.inquiry_number", default="", read_only=True)
    source_quotation_id = serializers.SerializerMethodField()
    source_quotation_number = serializers.SerializerMethodField()
    created_by = EmployeeSummarySerializer(source="created_by_employee", read_only=True)
    products = SampleFormProductReadSerializer(many=True, read_only=True)
    edit_capabilities = serializers.SerializerMethodField()
    workflow_records = SampleWorkflowRecordSerializer(many=True, read_only=True)
    workflow_actions = serializers.SerializerMethodField()
    parameter_images = serializers.SerializerMethodField()

    def get_parameter_images(self, instance):
        images = instance.parameter_images.filter(archived_at__isnull=True).select_related(
            "business_file", "uploaded_by_employee"
        )
        return SampleParameterImageSerializer(images, many=True).data

    def get_edit_capabilities(self, instance) -> dict:
        capabilities = sample_form_edit_capabilities(instance)
        request = self.context.get("request")
        actor = getattr(request, "employee", None) if request is not None else None
        capabilities["can_complete"] = bool(
            capabilities.get("can_complete")
            and request is not None
            and can_sample(request, instance, "samples.complete_sample_requirements")
        )
        capabilities["can_cancel"] = bool(
            instance.status == "PENDING_COMPLETION"
            and actor is not None
            and (
                (not module_access_enabled() and instance.requested_by_employee_id == actor.pk)
                or can_sample(request, instance, "access_control.cancel_samplerequest", "samples.change_samplerequest")
            )
        )
        return capabilities

    def get_workflow_actions(self, instance):
        from ..production_services import can_report_production, production_ready
        request = self.context.get("request")
        if request is None:
            return {
                "can_finance_confirm": False,
                "can_pmc_approve": False,
                "can_upload_metalwork": False,
                "can_upload_cutting": False,
                "can_delete_metalwork": False,
                "can_delete_cutting": False,
            }
        ready = not instance.application_payload_hash or (instance.archived_at is None and instance.customer_account.archived_at is None and production_ready(instance))
        from apps.access_control.module_policy import can_report_sample
        return {
            "can_report_production": can_report_production(instance, request),
            "can_delete_metalwork": instance.status not in {SampleRequestStatus.FINISHED, SampleRequestStatus.CANCELLED, SampleRequestStatus.REJECTED}
                and can_sample(request, instance, 'access_control.metalwork_sample', 'samples.change_samplerequest'),
            "can_delete_cutting": instance.status not in {SampleRequestStatus.FINISHED, SampleRequestStatus.CANCELLED, SampleRequestStatus.REJECTED}
                and can_sample(request, instance, 'access_control.cutting_sample', 'samples.change_samplerequest'),
            "can_report_metalwork": can_report_production(instance, request) and can_report_sample(request, instance, 'metalwork'),
            "can_report_cutting": can_report_production(instance, request) and can_report_sample(request, instance, 'cutting'),
            "can_finance_confirm": bool(
                instance.status == SampleRequestStatus.PENDING
                and can_sample(request, instance, "access_control.financeconfirm_sample", "samples.decide_sample_fee")
            ),
            "can_pmc_approve": bool(
                instance.status == SampleRequestStatus.PMC_REVIEW
                and can_sample(request, instance, "access_control.pmcapprove_sample", "samples.change_samplerequest")
            ),
            "can_upload_metalwork": bool(
                instance.status in {
                    SampleRequestStatus.METALWORK_PENDING,
                    SampleRequestStatus.CUTTING_PENDING,
                    SampleRequestStatus.PRODUCTION_PENDING,
                } and ready
                and can_sample(request, instance, "access_control.metalwork_sample", "samples.change_samplerequest")
            ),
            "can_upload_cutting": bool(
                instance.status in {
                    SampleRequestStatus.METALWORK_PENDING,
                    SampleRequestStatus.CUTTING_PENDING,
                    SampleRequestStatus.PRODUCTION_PENDING,
                } and ready
                and can_sample(request, instance, "access_control.cutting_sample", "samples.change_samplerequest")
            ),
        }

    def get_source_quotation_id(self, instance) -> str | None:
        version = instance.source_quotation_version
        return str(version.quotation_id) if version is not None else None

    def get_source_quotation_number(self, instance) -> str:
        version = instance.source_quotation_version
        if version is None:
            return ""
        return f"{version.quotation.quotation_number} V{version.version_number}"

    class Meta(SampleRequestListSerializer.Meta):
        fields = SampleRequestListSerializer.Meta.fields + [
            "transaction_entity",
            "transaction_entity_name",
            "customer_contact",
            "customer_contact_name",
            "source_inquiry",
            "source_inquiry_number",
            "source_quotation_version",
            "source_quotation_id",
            "source_quotation_number",
            "manual_request_number",
            "requested_by_employee",
            "created_by_employee",
            "created_by",
            "shipping_method",
            "order_date",
            "sample_due_date",
            "delivery_batch",
            "is_repeat_order",
            "submitted_on",
            "sample_type",
            "purpose",
            "notes",
            "expected_shipped_at",
            "expected_received_at",
            "collaborators",
            "items",
            "products",
            "workflow_records",
            "workflow_actions",
            "director_note",
            "reference_image",
            "fee_records",
            "shipments",
            "feedback",
            "files",
            "parameter_images",
            "sla",
            "fee_approvals",
        ]


class SampleRequestWritableSerializer(serializers.ModelSerializer):
    collaborator_employee_ids = serializers.PrimaryKeyRelatedField(
        source="collaborators",
        many=True,
        required=False,
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
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
        if inquiry and quote and quote.quotation.source_inquiry_id != inquiry.pk:
            errors["source_quotation_version_id"] = "来源报价版本必须来自当前来源询价。"
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
            "sample_type",
            "purpose",
            "requested_at",
            "requested_due_at",
            "expected_shipped_at",
            "expected_received_at",
            "collaborator_employee_ids",
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
            "sample_type",
            "purpose",
            "requested_at",
            "requested_due_at",
            "expected_shipped_at",
            "expected_received_at",
            "collaborator_employee_ids",
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


class SampleSourceItemSerializer(serializers.Serializer):
    requested_quantity = serializers.IntegerField(min_value=1)


class SampleFromInquiryItemSerializer(SampleSourceItemSerializer):
    source_item_id = serializers.PrimaryKeyRelatedField(
        source="source_item",
        queryset=InquiryItem.objects.none(),
    )


class SampleFromQuotationItemSerializer(SampleSourceItemSerializer):
    source_line_id = serializers.PrimaryKeyRelatedField(
        source="source_line",
        queryset=QuotationLine.objects.none(),
    )


class SampleFromSourceCreateSerializer(serializers.Serializer):
    sample_type = serializers.ChoiceField(choices=SampleType.choices)
    purpose = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    sample_due_date = serializers.DateField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(min_length=8, max_length=64)


class SampleFromInquiryCreateSerializer(SampleFromSourceCreateSerializer):
    inquiry_id = serializers.PrimaryKeyRelatedField(
        source="inquiry",
        queryset=Inquiry.objects.none(),
    )
    items = SampleFromInquiryItemSerializer(many=True, min_length=1, max_length=200)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not getattr(request.user, "is_authenticated", False):
            return
        customers = accessible_customers(request, "add_samplerequest").filter(archived_at__isnull=True)
        if module_access_enabled():
            customers = customers.filter(pk__in=accessible_customers(request, 'inquiries.view_inquiry').values('pk'))
        self.fields["inquiry_id"].queryset = Inquiry.objects.filter(
            customer_account__in=customers,
            archived_at__isnull=True,
        )
        self.fields["items"].child.fields["source_item_id"].queryset = InquiryItem.objects.filter(
            inquiry__customer_account__in=customers,
            inquiry__archived_at__isnull=True,
        )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        inquiry = attrs["inquiry"]
        source_ids = [item["source_item"].pk for item in attrs["items"]]
        if len(source_ids) != len(set(source_ids)):
            raise serializers.ValidationError({"items": "同一询价明细不能重复选择。"})
        if any(item.inquiry_id != inquiry.pk for item in (row["source_item"] for row in attrs["items"])):
            raise serializers.ValidationError({"items": "所选询价明细必须属于当前询盘。"})
        return attrs


class SampleFromQuotationCreateSerializer(SampleFromSourceCreateSerializer):
    quotation_version_id = serializers.PrimaryKeyRelatedField(
        source="quotation_version",
        queryset=QuotationVersion.objects.none(),
    )
    items = SampleFromQuotationItemSerializer(many=True, min_length=1, max_length=200)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not getattr(request.user, "is_authenticated", False):
            return
        customers = accessible_customers(request, "add_samplerequest").filter(archived_at__isnull=True)
        if module_access_enabled():
            customers = customers.filter(pk__in=accessible_customers(request, 'quotations.view_quotationversion').values('pk'))
        self.fields["quotation_version_id"].queryset = QuotationVersion.objects.filter(
            quotation__customer_account__in=customers,
            quotation__archived_at__isnull=True,
        )
        self.fields["items"].child.fields["source_line_id"].queryset = QuotationLine.objects.filter(
            quotation_version__quotation__customer_account__in=customers,
            quotation_version__quotation__archived_at__isnull=True,
        )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        version = attrs["quotation_version"]
        source_ids = [item["source_line"].pk for item in attrs["items"]]
        if len(source_ids) != len(set(source_ids)):
            raise serializers.ValidationError({"items": "同一报价行不能重复选择。"})
        if any(line.quotation_version_id != version.pk for line in (row["source_line"] for row in attrs["items"])):
            raise serializers.ValidationError({"items": "所选报价行必须属于当前报价版本。"})
        return attrs


class SampleBatchSelectionSerializer(serializers.Serializer):
    sample_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=100,
    )
    etags = serializers.DictField(child=serializers.CharField(max_length=100))

    def validate(self, attrs):
        sample_ids = {str(value) for value in attrs["sample_ids"]}
        missing = sample_ids.difference(attrs["etags"].keys())
        if missing:
            raise serializers.ValidationError({"etags": "每条样品记录都必须提供当前 ETag。"})
        return attrs


class SampleBulkTransferSerializer(SampleBatchSelectionSerializer):
    owner_employee_id = serializers.PrimaryKeyRelatedField(
        source="owner_employee",
        queryset=Employee.objects.filter(status="ACTIVE", archived_at__isnull=True),
    )
    note = serializers.CharField(max_length=500, trim_whitespace=True)


class SampleBulkReminderSerializer(SampleBatchSelectionSerializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500, trim_whitespace=True)


class SampleActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class SampleShipmentProgressSerializer(serializers.Serializer):
    occurred_at = serializers.DateTimeField()
    material_status = serializers.CharField(max_length=1000, trim_whitespace=True)

    def validate_occurred_at(self, value):
        if value > timezone.now():
            raise serializers.ValidationError("进度时间不能晚于当前时间。")
        return value


class SampleReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)
