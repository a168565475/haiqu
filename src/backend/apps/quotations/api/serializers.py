from apps.access_control.sales_sources import require_file
from apps.access_control import sales_policy
from apps.access_control.sales_policy import SalesAccessSerializerMixin
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.models import currency_code_validator, uppercase_code_validator
from apps.core.serializers import EmployeeSummarySerializer
from apps.customers.models import CustomerAccount, CustomerContact, CustomerEntityAddress, CustomerTransactionEntity
from apps.customers.selectors import accessible_customers
from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
from apps.inquiries.models import Inquiry
from apps.organizations.models import Employee
from apps.products.models import ProductInformation, ProductStatus
from apps.reference_data.models import Currency, Incoterm, ProductCategory, ProductColor, ProductItemType, ProductionUnit, ReferenceStatus
from ..models import (
    Quotation,
    QuotationAcceptance,
    QuotationContainerConfig,
    QuotationContainerTier,
    QuotationDispatchRecord,
    QuotationEmailDispatchAttempt,
    QuotationDocument,
    QuotationLine,
    QuotationLinePrice,
    QuotationLinePackaging,
    QuotationQuantityTier,
    QuotationPriceBasis,
    QuotationTemplate,
    QuotationVersion,
    QuotationVersionApprovalLink,
)


def _master_code_is_active(model, code):
    normalized = (code or "").strip().upper()
    return bool(normalized) and model.objects.filter(
        code=normalized,
        status=ReferenceStatus.ACTIVE,
        archived_at__isnull=True,
    ).exists()


def _validate_active_currency(code, *, current_code=""):
    normalized = (code or "").strip().upper()
    if normalized == (current_code or "").strip().upper() or _master_code_is_active(Currency, normalized):
        return normalized
    raise serializers.ValidationError("币种不存在、已停用或尚未启用。")


def _validate_active_incoterm(code, *, current_codes=()):
    normalized = (code or "").strip().upper()
    historical_codes = {(item or "").strip().upper() for item in current_codes}
    if normalized in historical_codes or _master_code_is_active(Incoterm, normalized):
        return normalized
    raise serializers.ValidationError("贸易术语不存在、已停用或尚未启用。")


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


class QuotationTemplateSellerProfileSerializer(serializers.Serializer):
    """固定报价模板中允许业务人员维护的卖方联系资料。"""

    company_name = serializers.CharField(required=False, allow_blank=True, max_length=300)
    contact_person = serializers.CharField(required=False, allow_blank=True, max_length=120)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=80)
    fax = serializers.CharField(required=False, allow_blank=True, max_length=80)
    skype = serializers.CharField(required=False, allow_blank=True, max_length=120)
    qq = serializers.CharField(required=False, allow_blank=True, max_length=120)
    wechat = serializers.CharField(required=False, allow_blank=True, max_length=120)
    whatsapp = serializers.CharField(required=False, allow_blank=True, max_length=80)
    address = serializers.CharField(required=False, allow_blank=True, max_length=500)
    email = serializers.EmailField(required=False, allow_blank=True, max_length=254)
    facebook = serializers.URLField(required=False, allow_blank=True, max_length=500)
    website = serializers.URLField(required=False, allow_blank=True, max_length=500)


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


class QuotationContainerConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuotationContainerConfig
        fields = [
            "id",
            "container_type_code",
            "config_version",
            "effective_volume_cbm",
            "default_load_factor",
        ]


class QuotationLinePackagingSerializer(serializers.ModelSerializer):
    total_cbm = serializers.SerializerMethodField()
    carton_cbm = serializers.DecimalField(max_digits=18, decimal_places=3, read_only=True, rounding=ROUND_HALF_UP)
    length_cm = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0.0001"))
    width_cm = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0.0001"))
    height_cm = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0.0001"))
    pieces_per_carton = serializers.IntegerField(min_value=1)
    carton_count = serializers.IntegerField(min_value=1)
    gross_weight_kg = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0"), required=False, allow_null=True)
    net_weight_kg = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0"), required=False, allow_null=True)

    class Meta:
        model = QuotationLinePackaging
        fields = [
            "id", "length_cm", "width_cm", "height_cm", "pieces_per_carton", "carton_count",
            "gross_weight_kg", "net_weight_kg", "carton_cbm", "total_cbm", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "carton_cbm", "total_cbm", "created_at", "updated_at"]

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=3))
    def get_total_cbm(self, packaging):
        total_cbm = (packaging.carton_cbm * packaging.carton_count).quantize(
            Decimal("0.001"),
            rounding=ROUND_HALF_UP,
        )
        return format(total_cbm, ".3f")


class QuotationContainerTierSerializer(serializers.ModelSerializer):
    container_config = QuotationContainerConfigSerializer(read_only=True, allow_null=True)
    container_config_id = serializers.PrimaryKeyRelatedField(
        source="container_config",
        queryset=QuotationContainerConfig.objects.filter(archived_at__isnull=True, is_active=True),
        write_only=True,
        required=False,
    )
    container_type_code = serializers.CharField(max_length=30, validators=[uppercase_code_validator], required=False)
    effective_volume_cbm = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0.0001"), required=False)
    load_factor = serializers.DecimalField(max_digits=7, decimal_places=6, min_value=Decimal("0.000001"), max_value=Decimal("1"), required=False)
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))

    class Meta:
        model = QuotationContainerTier
        fields = [
            "id", "tier_number", "container_config", "container_config_id", "container_type_code", "effective_volume_cbm",
            "load_factor", "auto_carton_count", "auto_quantity", "manual_carton_count",
            "override_reason", "final_quantity", "unit_price", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "tier_number", "auto_carton_count",
            "auto_quantity", "manual_carton_count", "override_reason", "final_quantity", "created_at", "updated_at",
        ]

    def validate(self, attrs):
        config = attrs.get("container_config")
        supplied_custom_fields = {"container_type_code", "effective_volume_cbm", "load_factor"}.issubset(attrs)
        if config is not None and supplied_custom_fields:
            raise serializers.ValidationError("请选择既有装柜参数或填写当前报价参数，不能同时提交两种来源。")
        if config is None and not supplied_custom_fields:
            raise serializers.ValidationError({"container_type_code": "请填写柜型、可用容积和装载系数。"})
        return attrs


class QuotationLinePriceSerializer(serializers.ModelSerializer):
    quotation_line_id = serializers.UUIDField(read_only=True)
    price_basis_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = QuotationLinePrice
        fields = [
            "id", "quotation_line_id", "price_basis_id", "unit_price", "surcharge_note",
            "is_manual_override", "override_reason", "created_at", "updated_at",
        ]


class QuotationPriceBasisSerializer(serializers.ModelSerializer):
    line_prices = QuotationLinePriceSerializer(many=True, read_only=True)

    class Meta:
        model = QuotationPriceBasis
        fields = [
            "id", "label", "incoterm_code", "named_place", "currency_code",
            "is_default", "sort_order", "notes", "line_prices", "created_at", "updated_at",
        ]


class QuotationLinePriceInputSerializer(serializers.Serializer):
    quotation_line_id = serializers.PrimaryKeyRelatedField(
        source="quotation_line",
        queryset=QuotationLine.objects.all(),
    )
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    surcharge_note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    is_manual_override = serializers.BooleanField(required=False, default=False)
    override_reason = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, attrs):
        if attrs.get("is_manual_override") and not attrs.get("override_reason", "").strip():
            raise serializers.ValidationError({"override_reason": "人工覆盖价格时必须填写原因。"})
        return attrs


class QuotationPriceBasisInputSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=120)
    incoterm_code = serializers.CharField(max_length=20, validators=[uppercase_code_validator])
    named_place = serializers.CharField(max_length=180)
    currency_code = serializers.CharField(max_length=3, validators=[currency_code_validator])
    is_default = serializers.BooleanField(required=False, default=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    line_prices = QuotationLinePriceInputSerializer(many=True, allow_empty=False)


class QuotationPriceMatrixSerializer(serializers.Serializer):
    price_bases = QuotationPriceBasisInputSerializer(many=True, allow_empty=False)

    def validate_price_bases(self, value):
        version = self.context["version"]
        historical_incoterms = set(version.price_bases.values_list("incoterm_code", flat=True))
        labels = [item["label"].strip().casefold() for item in value]
        if len(labels) != len(set(labels)):
            raise serializers.ValidationError("价格口径名称不能重复。")
        if sum(1 for item in value if item.get("is_default")) != 1:
            raise serializers.ValidationError("必须且只能设置一个默认价格口径。")
        if any(item["currency_code"] != version.currency_code for item in value):
            raise serializers.ValidationError("当前阶段各价格口径币种必须与报价版本币种一致。")
        for item in value:
            item["currency_code"] = _validate_active_currency(
                item["currency_code"],
                current_code=version.currency_code,
            )
            item["incoterm_code"] = _validate_active_incoterm(
                item["incoterm_code"],
                current_codes=historical_incoterms,
            )
        return value


class QuotationLineSerializer(serializers.ModelSerializer):
    line_number = serializers.IntegerField(required=False, min_value=1)
    unit_code = serializers.CharField(max_length=30, validators=[uppercase_code_validator])
    line_total = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"), required=False, allow_null=True)
    source_inquiry_item = serializers.UUIDField(source="source_inquiry_item_id", read_only=True)
    price_status = serializers.SerializerMethodField()
    discount_rate = serializers.DecimalField(
        max_digits=7,
        decimal_places=6,
        min_value=Decimal("0"),
        max_value=Decimal("1"),
        required=False,
        default=Decimal("0"),
    )
    quantity_tiers = QuotationQuantityTierSerializer(many=True, read_only=True)
    packaging = QuotationLinePackagingSerializer(read_only=True)
    container_tiers = QuotationContainerTierSerializer(many=True, read_only=True)
    product_image = serializers.SerializerMethodField()
    product_id = serializers.PrimaryKeyRelatedField(
        source="product",
        queryset=ProductInformation.objects.filter(status=ProductStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    product_category_id = serializers.PrimaryKeyRelatedField(
        source="product_category",
        queryset=ProductCategory.objects.filter(
            item_type=ProductItemType.FINISHED,
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ),
        required=False,
        allow_null=True,
    )
    product_unit_id = serializers.PrimaryKeyRelatedField(
        source="product_unit",
        queryset=ProductionUnit.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    product_color_id = serializers.PrimaryKeyRelatedField(
        source="product_color",
        queryset=ProductColor.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    product_specification = serializers.CharField(source="product.specification", read_only=True, allow_null=True)
    basis_prices = QuotationLinePriceSerializer(many=True, read_only=True)

    def get_product_image(self, line):
        image = line.product_image
        if image is None:
            return None
        return {
            "id": str(image.pk),
            "original_name": image.original_name,
            "scan_status": image.scan_status,
        }

    class Meta:
        model = QuotationLine
        fields = [
            "id",
            "lineage_id",
            "source_inquiry_item",
            "product_id",
            "product_specification",
            "product_category_id",
            "product_unit_id",
            "product_color_id",
            "line_number",
            "product_description_snapshot",
            "specification_snapshot",
            "color_snapshot",
            "product_number_snapshot",
            "product_code_snapshot",
            "item_number_snapshot",
            "material_snapshot",
            "quantity",
            "unit_code",
            "unit_price",
            "price_status",
            "discount_rate",
            "line_total",
            "notes",
            "quantity_tiers",
            "packaging",
            "container_tiers",
            "product_image",
            "basis_prices",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "lineage_id", "source_inquiry_item", "line_total", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._available_relation_querysets = {
            name: self.fields[name].queryset
            for name in ("product_id", "product_category_id", "product_unit_id", "product_color_id")
        }
        self._saved_line = None

    def to_internal_value(self, data):
        current = self.instance if isinstance(self.instance, QuotationLine) else None
        self._saved_line = current
        for name in self._available_relation_querysets:
            queryset = self._available_relation_querysets[name].all()
            relation_name = self.fields[name].source
            saved = getattr(current, relation_name, None) if current is not None else None
            if saved is not None:
                queryset = queryset | queryset.model.objects.filter(pk=saved.pk)
            self.fields[name].queryset = queryset
        return super().to_internal_value(data)

    def get_price_status(self, line):
        return "PENDING" if line.unit_price is None else "READY"

    def validate(self, attrs):
        if self.instance is None and attrs.get("unit_price") is None:
            raise serializers.ValidationError({"unit_price": "新建手工报价明细时必须填写单价。"})
        current = self._saved_line
        product = attrs.get("product", getattr(current, "product", None))
        product_changed = current is None or "product" in attrs and getattr(current, "product_id", None) != getattr(product, "pk", None)
        category = attrs.get("product_category", getattr(current, "product_category", None))
        unit = attrs.get("product_unit", getattr(current, "product_unit", None))
        color = attrs.get("product_color", getattr(current, "product_color", None))
        unit_code = str(attrs.get("unit_code", getattr(current, "unit_code", "")) or "").strip().upper()
        description = str(attrs.get("product_description_snapshot", getattr(current, "product_description_snapshot", "")) or "").strip()
        specification = str(attrs.get("specification_snapshot", getattr(current, "specification_snapshot", "")) or "").strip()
        color_text = str(attrs.get("color_snapshot", getattr(current, "color_snapshot", "")) or "").strip()
        errors = {}
        if product is not None:
            if product_changed and (
                product.status != ProductStatus.ACTIVE
                or product.archived_at is not None
                or product.category.status != ReferenceStatus.ACTIVE
                or product.category.archived_at is not None
                or product.unit.status != ReferenceStatus.ACTIVE
                or product.unit.archived_at is not None
            ):
                errors["product_id"] = "产品的类别或单位已停用或归档，不能建立新的产品关联。"
            if category is not None and category.pk != product.category_id:
                errors["product_category_id"] = "产品类别与产品主档不匹配。"
            if unit is not None and unit.pk != product.unit_id:
                errors["product_unit_id"] = "产品单位与产品主档不匹配。"
            if description != product.product_name:
                errors["product_description_snapshot"] = "已关联产品不能直接改名；请解除关联后作为定制产品保存。"
            specification_parts = [part.strip() for part in specification.split("；") if part.strip()]
            product_specification = str(product.specification or "").strip()
            has_only_order_suffixes = (
                bool(specification_parts)
                and specification_parts[0] == product_specification
                and all(part.startswith(("颜色：", "材质：")) for part in specification_parts[1:])
            )
            if specification != product_specification and not has_only_order_suffixes:
                errors["specification_snapshot"] = "已关联产品的规格必须与产品主档一致；不同规格请选择另一条产品记录。"
            if unit_code != product.unit.unit_code:
                errors["unit_code"] = "已关联产品的单位必须与产品主档一致。"
        else:
            if unit is not None and unit.unit_code != unit_code:
                errors["product_unit_id"] = "单位关联与填写内容不一致；手填单位请清除维护项关联。"
            if color is not None and color.color_name != color_text:
                errors["product_color_id"] = "颜色关联与填写内容不一致；手填颜色请清除维护项关联。"
        for field_name, relation in (("product_category_id", category), ("product_unit_id", unit), ("product_color_id", color)):
            if relation is not None and (relation.status != ReferenceStatus.ACTIVE or relation.archived_at is not None) and not (
                current is not None and getattr(current, self.fields[field_name].source + "_id", None) == relation.pk
            ):
                errors[field_name] = "维护项已停用或归档，不能建立新的关联。"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class QuotationLineSyncInquirySerializer(serializers.Serializer):
    inquiry_etag = serializers.CharField(max_length=200)


class QuotationLineSyncInquiryResponseSerializer(serializers.Serializer):
    inquiry_item_id = serializers.UUIDField()
    inquiry_etag = serializers.CharField()


class QuotationLineUpdateSerializer(QuotationLineSerializer):
    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        return attrs


class InquiryQuotationCreateSerializer(serializers.Serializer):
    inquiry_id = serializers.PrimaryKeyRelatedField(queryset=Inquiry.objects.filter(archived_at__isnull=True))
    transaction_entity_id = serializers.PrimaryKeyRelatedField(
        queryset=CustomerTransactionEntity.objects.filter(archived_at__isnull=True), required=False, allow_null=True
    )
    transaction_entity = serializers.DictField(required=False, write_only=True)
    subject = serializers.CharField(max_length=250, required=False, allow_blank=True)
    currency_code = serializers.CharField(max_length=3, validators=[currency_code_validator])
    due_at = serializers.DateTimeField()
    idempotency_key = serializers.CharField(max_length=64)
    create_another = serializers.BooleanField(required=False, default=False)

    def validate_currency_code(self, value):
        return _validate_active_currency(value)

    def validate(self, attrs):
        entity = attrs.get("transaction_entity")
        if entity and attrs.get("transaction_entity_id"):
            raise serializers.ValidationError({"transaction_entity": "请选择已有主体或填写新主体，不能同时提交。"})
        if entity:
            errors = {}
            if not str(entity.get("legal_name") or "").strip():
                errors["transaction_entity.legal_name"] = "法定主体名称不能为空。"
            if not str(entity.get("registration_country_code") or "").strip():
                errors["transaction_entity.registration_country_code"] = "注册国家不能为空。"
            if errors:
                raise serializers.ValidationError(errors)
        if attrs["due_at"] <= timezone.now():
            raise serializers.ValidationError({"due_at": "报价草稿任务截止时间必须晚于当前时间。"})
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
    price_basis_id = serializers.UUIDField(allow_null=True, read_only=True)
    evidence_file_id = serializers.UUIDField(allow_null=True, read_only=True)

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
            "is_simulated",
            "price_basis_id",
            "evidence_file_id",
        ]


class QuotationEmailDispatchAttemptSerializer(serializers.ModelSerializer):
    price_basis_id = serializers.UUIDField(read_only=True)
    quotation_document_id = serializers.UUIDField(read_only=True)
    dispatch_record_id = serializers.UUIDField(allow_null=True, read_only=True)
    requested_by = EmployeeSummarySerializer(source="requested_by_employee", read_only=True)
    resolved_by = EmployeeSummarySerializer(source="resolved_by_employee", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = QuotationEmailDispatchAttempt
        fields = [
            "id",
            "quotation_version_id",
            "price_basis_id",
            "quotation_document_id",
            "idempotency_key",
            "status",
            "status_display",
            "recipient",
            "cc_snapshot",
            "subject",
            "body_html",
            "recipient_snapshot",
            "attachment_snapshot",
            "follow_up_due_at",
            "error_message",
            "dispatch_record_id",
            "requested_by",
            "resolved_by",
            "resolved_at",
            "resolution_note",
            "created_at",
            "updated_at",
        ]


class QuotationAcceptanceSerializer(serializers.ModelSerializer):
    quotation_version_id = serializers.UUIDField(read_only=True)
    price_basis_id = serializers.UUIDField(read_only=True)
    customer_contact_id = serializers.UUIDField(allow_null=True, read_only=True)
    recorded_by = EmployeeSummarySerializer(source="recorded_by_employee", read_only=True)

    class Meta:
        model = QuotationAcceptance
        fields = [
            "id", "quotation_version_id", "price_basis_id", "customer_contact_id",
            "accepted_at", "source", "note", "recorded_by", "created_at",
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


class QuotationVersionListSerializer(SalesAccessSerializerMixin, serializers.ModelSerializer):
    template_code = serializers.CharField(source="quotation_template.template_code", allow_null=True, read_only=True)
    template_name = serializers.CharField(source="quotation_template.template_name", allow_null=True, read_only=True)
    template_version = serializers.IntegerField(source="quotation_template.template_version", allow_null=True, read_only=True)
    template_config = serializers.JSONField(source="quotation_template.template_config", allow_null=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    locked_by = EmployeeSummarySerializer(source="locked_by_employee", allow_null=True, read_only=True)

    class Meta:
        model = QuotationVersion
        fields = [
            "allowed_permissions",
            "id",
            "quotation",
            "parent_version",
            "version_number",
            "status",
            "status_display",
            "template_code",
            "template_name",
            "template_version",
            "template_config",
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
    price_bases = QuotationPriceBasisSerializer(many=True, read_only=True)
    payment_breakdown = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_payment_breakdown(self, version):
        terms = version.terms_snapshot if isinstance(version.terms_snapshot, dict) else {}
        raw_percent = terms.get("deposit_percent")
        if raw_percent in (None, ""):
            return None
        try:
            deposit_percent = Decimal(str(raw_percent))
        except (ArithmeticError, ValueError):
            return None
        if deposit_percent < 0 or deposit_percent > 100:
            return None
        balance_percent = Decimal("100") - deposit_percent
        deposit_amount = (version.total_amount * deposit_percent / Decimal("100")).quantize(Decimal("0.0001"))
        balance_amount = version.total_amount - deposit_amount
        return {
            "deposit_percent": format(deposit_percent.normalize(), "f"),
            "balance_percent": format(balance_percent.normalize(), "f"),
            "deposit_amount": str(deposit_amount),
            "balance_amount": str(balance_amount),
        }

    class Meta(QuotationVersionListSerializer.Meta):
        fields = QuotationVersionListSerializer.Meta.fields + [
            "quotation_template",
            "transaction_entity_snapshot",
            "address_snapshot",
            "contact_snapshot",
            "template_snapshot",
            "terms_snapshot",
            "customer_requirement_snapshot",
            "notes",
            "lines",
            "documents",
            "dispatches",
            "approvals",
            "price_bases",
            "payment_breakdown",
        ]


class QuotationListSerializer(SalesAccessSerializerMixin, serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer_account.account_name", read_only=True)
    source_inquiry_number = serializers.CharField(source="source_inquiry.inquiry_number", allow_null=True, read_only=True)
    owner = EmployeeSummarySerializer(source="owner_employee", read_only=True)
    outcome_status_display = serializers.CharField(source="get_outcome_status_display", read_only=True)
    current_version = serializers.SerializerMethodField()
    display_status = serializers.SerializerMethodField()
    display_status_label = serializers.SerializerMethodField()
    allowed_actions = serializers.SerializerMethodField()

    def _current_version(self, quotation):
        versions = list(quotation.versions.all())
        return max(versions, key=lambda item: item.version_number) if versions else None

    def _display_status(self, quotation, version):
        if quotation.outcome_status == "WON":
            return "ACCEPTED", "已接受"
        if quotation.outcome_status == "LOST":
            return "REJECTED", "已失单"
        if quotation.outcome_status == "CANCELLED":
            return "WITHDRAWN", "已取消"
        if version is None:
            return "DRAFT", "草稿"
        if version.status == "VOID":
            return "WITHDRAWN", "已作废"
        if version.valid_until and version.valid_until < timezone.localdate():
            return "EXPIRED", "已过期"
        labels = {
            "DRAFT": ("DRAFT", "草稿"),
            "LOCKED": ("LOCKED", "已锁定"),
            "ISSUED": ("READY_TO_SEND", "待发送"),
            "SENT": ("SENT", "已发送"),
            "SUPERSEDED": ("SUPERSEDED", "已替代"),
        }
        return labels.get(version.status, (version.status, version.get_status_display()))

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_current_version(self, quotation):
        version = self._current_version(quotation)
        if version is None:
            return None
        terms = version.terms_snapshot if isinstance(version.terms_snapshot, dict) else {}
        return {
            "id": str(version.pk),
            "version_number": version.version_number,
            "status": version.status,
            "currency_code": version.currency_code,
            "total_amount": str(version.total_amount),
            "valid_until": version.valid_until,
            "incoterm_label": terms.get("incoterm_label") or terms.get("incoterm_code") or "未填写",
            "updated_at": version.updated_at,
        }

    @extend_schema_field(OpenApiTypes.STR)
    def get_display_status(self, quotation):
        return self._display_status(quotation, self._current_version(quotation))[0]

    @extend_schema_field(OpenApiTypes.STR)
    def get_display_status_label(self, quotation):
        return self._display_status(quotation, self._current_version(quotation))[1]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_allowed_actions(self, quotation):
        version = self._current_version(quotation)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        can_change = bool(user and sales_policy.can_customer(request, "quotations.change_quotation", quotation.customer_account_id))
        can_create_version = bool(user and sales_policy.can_customer(request, "quotations.add_quotationversion", quotation.customer_account_id))
        return {
            "view": True,
            "edit": bool(can_change and version and version.status == "DRAFT"),
            "create_version": bool(can_create_version and quotation.outcome_status == "OPEN"),
        }

    class Meta:
        model = Quotation
        fields = [
            "allowed_permissions",
            "id",
            "quotation_number",
            "customer_account",
            "customer_name",
            "transaction_entity",
            "source_inquiry",
            "source_inquiry_number",
            "owner",
            "outcome_status",
            "outcome_status_display",
            "accepted_version",
            "subject",
            "outcome_note",
            "current_version",
            "display_status",
            "display_status_label",
            "allowed_actions",
            "archived_at",
            "created_at",
            "updated_at",
        ]


class QuotationDetailSerializer(QuotationListSerializer):
    versions = QuotationVersionListSerializer(many=True, read_only=True)
    acceptance = QuotationAcceptanceSerializer(read_only=True)

    class Meta(QuotationListSerializer.Meta):
        fields = QuotationListSerializer.Meta.fields + ["versions", "acceptance"]


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


class QuotationDraftCreateSerializer(QuotationCreateSerializer):
    currency_code = serializers.CharField(max_length=3, validators=[currency_code_validator])
    valid_until = serializers.DateField(required=False, allow_null=True)

    class Meta(QuotationCreateSerializer.Meta):
        fields = QuotationCreateSerializer.Meta.fields + ["currency_code", "valid_until"]

    def validate_currency_code(self, value):
        return _validate_active_currency(value)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("valid_until") and attrs["valid_until"] < timezone.localdate():
            raise serializers.ValidationError({"valid_until": "报价有效期不能早于今天。"})
        return attrs


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

    def validate_currency_code(self, value):
        return _validate_active_currency(value)


class QuotationVersionUpdateSerializer(serializers.ModelSerializer):
    quotation_template_id = serializers.PrimaryKeyRelatedField(
        source="quotation_template",
        required=False,
        allow_null=True,
        queryset=QuotationTemplate.objects.filter(archived_at__isnull=True),
    )
    currency_code = serializers.CharField(required=False, max_length=3, validators=[currency_code_validator])
    terms_snapshot = serializers.JSONField(required=False)

    class Meta:
        model = QuotationVersion
        fields = ["quotation_template_id", "currency_code", "language_code", "valid_until", "terms_snapshot", "notes"]

    def validate_currency_code(self, value):
        return _validate_active_currency(value, current_code=getattr(self.instance, "currency_code", ""))

    def validate_terms_snapshot(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("条款快照必须是对象。")
        allowed_keys = {"payment_terms", "deposit_percent", "lead_time", "incoterm_code", "incoterm_label"}
        unknown_keys = sorted(set(value) - allowed_keys)
        if unknown_keys:
            raise serializers.ValidationError(f"不支持的条款字段：{', '.join(unknown_keys)}。")
        cleaned = {}
        for key in ("payment_terms", "lead_time", "incoterm_code", "incoterm_label"):
            if key in value:
                text = str(value[key] or "").strip()
                if len(text) > 200:
                    raise serializers.ValidationError(f"{key} 不能超过 200 个字符。")
                cleaned[key] = text
        if cleaned.get("incoterm_code"):
            current_code = ""
            if self.instance is not None:
                current_code = (self.instance.terms_snapshot or {}).get("incoterm_code", "")
            cleaned["incoterm_code"] = _validate_active_incoterm(
                cleaned["incoterm_code"],
                current_codes=[current_code],
            )
        if "deposit_percent" in value:
            if value["deposit_percent"] in (None, ""):
                cleaned["deposit_percent"] = ""
                return cleaned
            try:
                percent = Decimal(str(value["deposit_percent"]))
            except (ArithmeticError, ValueError):
                raise serializers.ValidationError("订金比例必须是 0 到 100 之间的数字。")
            if percent < 0 or percent > 100:
                raise serializers.ValidationError("订金比例必须是 0 到 100 之间的数字。")
            cleaned["deposit_percent"] = format(percent.normalize(), "f")
        return cleaned

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
        queryset=BusinessFile.objects.filter(archived_at__isnull=True, scan_status__in=USABLE_FILE_SCAN_STATUSES),
    )

    def validate_file_id(self, business_file):
        require_file(self.context.get("request"), business_file)
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


class QuotationManualDispatchSerializer(serializers.Serializer):
    price_basis_id = serializers.PrimaryKeyRelatedField(
        source="price_basis",
        queryset=QuotationPriceBasis.objects.all(),
    )
    recipient_snapshot = serializers.JSONField()
    evidence_file_id = serializers.PrimaryKeyRelatedField(
        source="evidence_file",
        queryset=BusinessFile.objects.filter(archived_at__isnull=True, scan_status__in=USABLE_FILE_SCAN_STATUSES),
        required=False,
        allow_null=True,
        default=None,
    )
    external_reference = serializers.CharField(required=False, allow_blank=True, max_length=250, default="")
    evidence_note = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")
    follow_up_due_at = serializers.DateTimeField(required=False, allow_null=True, default=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        version = self.context.get("version")
        if version:
            self.fields["price_basis_id"].queryset = version.price_bases.all()

    def validate_recipient_snapshot(self, value):
        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError("收件人快照必须是非空 JSON 对象。")
        return value

    def validate_evidence_file_id(self, business_file):
        require_file(self.context.get("request"), business_file)
        if business_file is None:
            return None
        version = self.context["version"]
        actor = getattr(self.context["request"], "employee", None)
        customer_id = version.quotation.customer_account_id
        linked_customer_ids = set(business_file.customer_links.values_list("customer_account_id", flat=True))
        linked_customer_ids.update(
            business_file.quotation_links.values_list(
                "quotation_version__quotation__customer_account_id", flat=True
            )
        )
        if linked_customer_ids and linked_customer_ids != {customer_id}:
            raise serializers.ValidationError("证据文件已关联其他客户，不能跨客户复用。")
        if not linked_customer_ids and business_file.uploaded_by_employee_id != getattr(actor, "pk", None):
            raise serializers.ValidationError("未关联证据文件只能由上传人登记。")
        return business_file

    def validate_follow_up_due_at(self, value):
        if value is not None and value <= timezone.now():
            raise serializers.ValidationError("跟进时间必须晚于当前时间。")
        return value

    def validate(self, attrs):
        if (
            attrs.get("evidence_file") is None
            and not attrs.get("external_reference", "").strip()
            and not attrs.get("evidence_note", "").strip()
        ):
            raise serializers.ValidationError({"evidence_note": "人工发送必须至少保留一种发送证据。"})
        return attrs


class QuotationEmailDispatchSerializer(serializers.Serializer):
    idempotency_key = serializers.UUIDField()
    price_basis_id = serializers.PrimaryKeyRelatedField(
        source="price_basis",
        queryset=QuotationPriceBasis.objects.all(),
    )
    recipient = serializers.EmailField()
    cc = serializers.ListField(child=serializers.EmailField(), required=False, default=list)
    subject = serializers.CharField(max_length=250)
    body = serializers.CharField(max_length=10000)
    follow_up_due_at = serializers.DateTimeField(required=False, allow_null=True, default=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        version = self.context.get("version")
        if version:
            self.fields["price_basis_id"].queryset = version.price_bases.all()

    def validate_follow_up_due_at(self, value):
        if value is not None and value <= timezone.now():
            raise serializers.ValidationError("跟进时间必须晚于当前时间。")
        return value


class QuotationEmailAttemptResolutionSerializer(serializers.Serializer):
    result = serializers.ChoiceField(choices=["ACCEPTED", "NOT_SENT"])
    note = serializers.CharField(min_length=2, max_length=1000, trim_whitespace=True)


class QuotationSimulatedDispatchSerializer(serializers.Serializer):
    recipient = serializers.EmailField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class QuotationAcceptSerializer(serializers.Serializer):
    accepted_version_id = serializers.PrimaryKeyRelatedField(
        source="accepted_version",
        queryset=QuotationVersion.objects.all(),
    )
    price_basis_id = serializers.PrimaryKeyRelatedField(
        source="accepted_price_basis",
        queryset=QuotationPriceBasis.objects.all(),
    )
    customer_contact_id = serializers.PrimaryKeyRelatedField(
        source="customer_contact",
        queryset=CustomerContact.objects.filter(archived_at__isnull=True, status="ACTIVE"),
        required=False,
        allow_null=True,
    )
    accepted_at = serializers.DateTimeField()
    source = serializers.ChoiceField(choices=["EMAIL", "PHONE", "MEETING", "OTHER"])
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        quotation = self.context.get("quotation")
        if quotation:
            self.fields["accepted_version_id"].queryset = QuotationVersion.objects.filter(
                quotation=quotation,
                status="SENT",
            )
            self.fields["price_basis_id"].queryset = QuotationPriceBasis.objects.filter(
                quotation_version__quotation=quotation,
            )
            self.fields["customer_contact_id"].queryset = CustomerContact.objects.filter(
                customer_account=quotation.customer_account,
                archived_at__isnull=True,
                status="ACTIVE",
            )

    def validate(self, attrs):
        version = attrs["accepted_version"]
        basis = attrs["accepted_price_basis"]
        if basis.quotation_version_id != version.pk:
            raise serializers.ValidationError({"price_basis_id": "价格口径必须属于接受版本。"})
        if attrs["accepted_at"] > timezone.now():
            raise serializers.ValidationError({"accepted_at": "客户接受时间不能晚于当前时间。"})
        return attrs


class QuotationReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class EmptyActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
