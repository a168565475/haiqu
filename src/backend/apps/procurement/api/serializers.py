import re
from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..models import (
    PurchaseContractTemplate,
    PurchaseContractTemplateStatus,
    PurchaseContractTemplateVersion,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    SupplierCategory,
    SupplierPaymentCycle,
    SupplierPurchaseSheet,
    SupplierType,
)


PHONE_PATTERN = re.compile(r"^(?=.*[0-9])[0-9+\-()（）\s#.,，、/:：转分机EXText]+$")


class SupplierListSerializer(serializers.ModelSerializer):
    supplier_type_display = serializers.CharField(source="get_supplier_type_display", read_only=True)
    supplier_category_labels = serializers.SerializerMethodField()
    payment_cycle_display = serializers.CharField(source="get_payment_cycle_display", read_only=True)
    status_display = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = [
            "id",
            "supplier_number",
            "supplier_type",
            "supplier_type_display",
            "supplier_categories",
            "supplier_category_labels",
            "supplier_name",
            "payment_cycle",
            "payment_cycle_display",
            "remark",
            "phone",
            "is_disabled",
            "status_display",
            "submitted_by_name",
            "submitted_at",
            "updated_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_supplier_category_labels(self, instance):
        labels = dict(SupplierCategory.choices)
        return [labels.get(value, value) for value in instance.supplier_categories]

    @extend_schema_field(serializers.CharField())
    def get_status_display(self, instance):
        return "禁用" if instance.is_disabled else "正常"

    @extend_schema_field(serializers.CharField())
    def get_updated_by_name(self, instance):
        employee = instance.updated_by_employee or instance.created_by_employee
        if employee:
            return employee.display_name
        return instance.submitted_by_name or "系统"


class DuplicateSupplierSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    supplier_number = serializers.CharField()
    is_disabled = serializers.BooleanField()
    status_display = serializers.CharField()


class SupplierDetailSerializer(SupplierListSerializer):
    duplicate_suppliers = serializers.SerializerMethodField()

    class Meta(SupplierListSerializer.Meta):
        fields = SupplierListSerializer.Meta.fields + ["duplicate_suppliers"]

    @extend_schema_field(DuplicateSupplierSerializer(many=True))
    def get_duplicate_suppliers(self, instance):
        matches = Supplier.objects.filter(
            archived_at__isnull=True,
            supplier_name=instance.supplier_name,
        ).exclude(pk=instance.pk).order_by("supplier_number")[:20]
        return [
            {
                "id": str(item.pk),
                "supplier_number": item.supplier_number,
                "is_disabled": item.is_disabled,
                "status_display": "禁用" if item.is_disabled else "正常",
            }
            for item in matches
        ]


class SupplierInputSerializer(serializers.ModelSerializer):
    supplier_categories = serializers.ListField(
        child=serializers.ChoiceField(choices=SupplierCategory.choices),
        allow_empty=False,
        max_length=len(SupplierCategory.values),
    )

    class Meta:
        model = Supplier
        fields = [
            "supplier_type",
            "supplier_categories",
            "supplier_name",
            "payment_cycle",
            "remark",
            "phone",
            "is_disabled",
        ]

    def validate_supplier_name(self, value):
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("请输入供应商名称。")
        return normalized

    def validate_supplier_categories(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("供应商类别不能重复。")
        return value

    def validate_remark(self, value):
        normalized = value.strip()
        if len(normalized) > 2000:
            raise serializers.ValidationError("备注不能超过 2000 个字符。")
        return normalized

    def validate_phone(self, value):
        normalized = value.strip()
        if not normalized:
            return ""
        if len(normalized) < 3 or not PHONE_PATTERN.fullmatch(normalized):
            raise serializers.ValidationError("联系电话格式不正确。")
        return normalized

    def validate_payment_cycle(self, value):
        if value and value not in SupplierPaymentCycle.values:
            raise serializers.ValidationError("付款周期选项不正确。")
        return value

    def validate_supplier_type(self, value):
        if value not in SupplierType.values:
            raise serializers.ValidationError("供应商类型选项不正确。")
        return value


class PurchaseOrderLineInputSerializer(serializers.Serializer):
    actual_bar_count = serializers.IntegerField(min_value=1, max_value=99999999999999, required=False, allow_null=True, default=None)
    raw_bar_length_m = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True, default=None)
    quantity_difference_reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default='')
    bom_line_id = serializers.UUIDField(required=False)
    sample_line_key = serializers.UUIDField(required=False)
    supplier_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    delivery_date = serializers.DateField(required=False, allow_null=True, default=None)
    actual_purchase_quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=False,
        allow_null=True,
        default=None,
    )
    unit_price = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0"),
        required=False,
        allow_null=True,
        default=None,
    )


class PurchaseOrderCreateSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(choices=["PRODUCTION", "SAMPLE"], default="PRODUCTION")
    production_task_id = serializers.UUIDField(required=False)
    bom_id = serializers.UUIDField(required=False)
    sample_procurement_request_id = serializers.UUIDField(required=False)
    source_revision = serializers.RegexField(regex=r"^[0-9a-f]{64}$", max_length=64)
    currency_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    is_mailed = serializers.BooleanField(required=False, allow_null=True, default=None)
    lines = PurchaseOrderLineInputSerializer(many=True, allow_empty=False, max_length=5000)

    def validate(self, value):
        sample = value["source_type"] == "SAMPLE"
        required = ["sample_procurement_request_id"] if sample else ["production_task_id", "bom_id"]
        forbidden = ["production_task_id", "bom_id"] if sample else ["sample_procurement_request_id"]
        if any(key not in value for key in required) or any(key in value for key in forbidden):
            raise serializers.ValidationError("请选择且仅提交对应的采购来源。")
        key, other = ("sample_line_key", "bom_line_id") if sample else ("bom_line_id", "sample_line_key")
        if any(key not in item or other in item for item in value["lines"]):
            raise serializers.ValidationError({"lines": "采购行来源与采购订单来源不一致。"})
        line_ids = [item[key] for item in value["lines"]]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError({"lines": "同一条采购来源明细不能重复提交。"})
        return value


class PurchaseOrderUpdateLineSerializer(serializers.Serializer):
    actual_bar_count = serializers.IntegerField(min_value=1, max_value=99999999999999, required=False, allow_null=True, default=None)
    raw_bar_length_m = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True, default=None)
    quantity_difference_reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    id = serializers.UUIDField()
    supplier_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    delivery_date = serializers.DateField(required=False, allow_null=True, default=None)
    actual_purchase_quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=False,
        allow_null=True,
        default=None,
    )
    unit_price = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0"),
        required=False,
        allow_null=True,
        default=None,
    )


class PurchaseOrderUpdateSerializer(serializers.Serializer):
    is_mailed = serializers.BooleanField(required=False, allow_null=True)
    lines = PurchaseOrderUpdateLineSerializer(many=True, allow_empty=False, max_length=5000)

    def validate_lines(self, value):
        line_ids = [item["id"] for item in value]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError("采购明细不能重复提交。")
        return value


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    sample_line_key = serializers.UUIDField(source="sample_material_source.line_key", read_only=True, allow_null=True, default=None)
    color = serializers.CharField(source="color_snapshot", read_only=True)
    bom_id = serializers.UUIDField(read_only=True, allow_null=True)
    bom_line_id = serializers.UUIDField(read_only=True, allow_null=True)
    product_line_id = serializers.UUIDField(source="product_line_id_snapshot", read_only=True)
    bom_number = serializers.CharField(source="bom_number_snapshot", read_only=True)
    product_number = serializers.CharField(source="product_number_snapshot", read_only=True)
    product_code = serializers.CharField(source="product_code_snapshot", read_only=True)
    product_name = serializers.CharField(source="product_name_snapshot", read_only=True)
    product_specification = serializers.CharField(source="product_specification_snapshot", read_only=True)
    section_type = serializers.CharField(source="section_type_snapshot", read_only=True)
    section_title = serializers.CharField(source="section_title_snapshot", read_only=True)
    category = serializers.CharField(source="category_snapshot", read_only=True)
    material = serializers.CharField(source="material_snapshot", read_only=True)
    part_name = serializers.CharField(source="part_name_snapshot", read_only=True)
    specification = serializers.CharField(source="specification_snapshot", read_only=True)
    raw_material = serializers.CharField(source="raw_material_snapshot", read_only=True)
    material_attributes_snapshot = serializers.JSONField(read_only=True)
    supplier_id = serializers.UUIDField(read_only=True, allow_null=True)
    supplier_number = serializers.CharField(source="supplier_number_snapshot", read_only=True)
    supplier_name = serializers.CharField(source="supplier_name_snapshot", read_only=True)
    supplier_type = serializers.CharField(source="supplier_type_snapshot", read_only=True)
    supplier_categories = serializers.ListField(source="supplier_categories_snapshot", read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = [
            "sample_line_key", "sample_demand_quantity", "sample_supply_quantity", "color",
            "id",
            "line_number",
            "bom_id",
            "bom_line_id",
            "source_bom_line_id_snapshot",
            "product_line_id",
            "bom_number",
            "product_number",
            "product_code",
            "product_name",
            "product_specification",
            "section_type",
            "section_title",
            "category",
            "material",
            "part_name",
            "specification",
            "raw_material",
            "material_attributes_snapshot",
            "required_quantity",
            "source_quantity_field",
            "source_quantity_text",
            "source_unit_text",
            "quantity_parse_status",
            "supplier_id",
            "supplier_number",
            "supplier_name",
            "supplier_type",
            "supplier_categories",
            "delivery_date",
            "raw_bar_length_m", "suggested_bar_count", "suggested_purchase_meters",
            "actual_bar_count", "actual_purchase_meters", "quantity_difference_reason", "calculation_snapshot",
            "actual_purchase_quantity",
            "unit_price",
            "amount",
        ]
        read_only_fields = fields


class PurchaseOrderListSerializer(serializers.ModelSerializer):
    source_type_display = serializers.CharField(source="get_source_type_display", read_only=True)
    source_number = serializers.SerializerMethodField()
    completion = serializers.SerializerMethodField()
    production_task_id = serializers.UUIDField(read_only=True)
    production_task_number = serializers.CharField(source="production_task_number_snapshot", read_only=True)
    sales_order_number = serializers.CharField(source="sales_order_number_snapshot", read_only=True)
    is_historical_unlinked = serializers.SerializerMethodField()
    customer_name = serializers.CharField(source="customer_name_snapshot", read_only=True)
    order_date = serializers.SerializerMethodField()
    delivery_date = serializers.SerializerMethodField()
    currency_id = serializers.UUIDField(read_only=True, allow_null=True)
    currency_code = serializers.CharField(source="currency_code_snapshot", read_only=True)
    currency_name = serializers.CharField(source="currency_name_snapshot", read_only=True)
    currency_symbol = serializers.CharField(source="currency_symbol_snapshot", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    line_count = serializers.SerializerMethodField()
    supplier_count = serializers.SerializerMethodField()
    supplier_assigned_line_count = serializers.SerializerMethodField()
    supplier_summary = serializers.SerializerMethodField()
    product_summary = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = [
            "source_type", "source_type_display", "source_number", "sample_procurement_request_id", "sample_number_snapshot",
            "completion", "completed_at", "completion_remark",
            "id",
            "order_number",
            "source_revision",
            "status",
            "status_display",
            "production_task_id",
            "production_task_number",
            "sales_order_number",
            "is_historical_unlinked",
            "customer_name",
            "order_date",
            "delivery_date",
            "currency_id",
            "currency_code",
            "currency_name",
            "currency_symbol",
            "is_mailed",
            "total_amount",
            "line_count",
            "supplier_count",
            "supplier_assigned_line_count",
            "supplier_summary",
            "product_summary",
            "created_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @staticmethod
    def _lines(instance):
        return list(instance.lines.all())

    def get_completion(self, instance):
        from ..completion_services import purchase_completion_summary
        return purchase_completion_summary(instance)

    def get_line_count(self, instance):
        return len(self._lines(instance))

    def get_is_historical_unlinked(self, instance):
        return bool(instance.production_task_id and instance.production_task.sales_order_id is None)

    def get_source_number(self, instance):
        return instance.sample_number_snapshot if instance.source_type == "SAMPLE" else instance.production_task_number_snapshot

    def get_order_date(self, instance):
        value = (instance.production_task.order_date if instance.production_task_id
                 else instance.sample_procurement_request.material_request.sample_request.order_date)
        return value.isoformat() if value else None

    def get_delivery_date(self, instance):
        value = (instance.production_task.delivery_date if instance.production_task_id
                 else instance.sample_procurement_request.material_request.sample_request.sample_due_date)
        return value.isoformat() if value else None

    def get_supplier_summary(self, instance):
        result = []
        seen = set()
        for line in self._lines(instance):
            if not line.supplier_id or line.supplier_id in seen:
                continue
            seen.add(line.supplier_id)
            result.append(
                {
                    "id": str(line.supplier_id),
                    "supplier_number": line.supplier_number_snapshot,
                    "supplier_name": line.supplier_name_snapshot,
                }
            )
        return result

    def get_supplier_count(self, instance):
        return len(self.get_supplier_summary(instance))

    def get_product_summary(self, instance):
        if instance.source_type == "SAMPLE":
            return []
        products = getattr(instance.production_task, "purchase_order_products", [])
        products_by_id = {product.pk: product for product in products}
        result = []
        seen = set()
        for line in self._lines(instance):
            product_line_id = line.product_line_id_snapshot
            if product_line_id in seen:
                continue
            seen.add(product_line_id)
            product = products_by_id.get(product_line_id)
            result.append(
                {
                    "product_line_id": str(product_line_id),
                    "product_name": line.product_name_snapshot,
                    "specification": line.product_specification_snapshot,
                    "color_card": product.color_card_snapshot if product else "",
                    "color_name": product.color_name_snapshot if product else "",
                    "color_code": product.color_code_snapshot if product else "",
                }
            )
        return result

    def get_supplier_assigned_line_count(self, instance):
        return sum(1 for line in self._lines(instance) if line.supplier_id)

    def get_created_by_name(self, instance):
        return instance.created_by_employee.display_name if instance.created_by_employee else "系统"


class PurchaseOrderCompletionSerializer(serializers.Serializer):
    remark = serializers.CharField(max_length=2000, allow_blank=True, required=False, default="", trim_whitespace=True)


class PurchaseOrderDetailSerializer(PurchaseOrderListSerializer):
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)

    class Meta(PurchaseOrderListSerializer.Meta):
        fields = PurchaseOrderListSerializer.Meta.fields + ["lines"]


class PurchaseSheetAssignmentSerializer(serializers.Serializer):
    supplier_id = serializers.UUIDField()
    template_version_id = serializers.UUIDField()


class PurchaseSheetGenerateSerializer(serializers.Serializer):
    assignments = PurchaseSheetAssignmentSerializer(many=True, allow_empty=False, max_length=1000)


class PurchaseContractTemplateInputSerializer(serializers.Serializer):
    template_code = serializers.RegexField(
        regex=r"^[A-Z0-9_]{2,50}$",
        required=False,
    )
    template_name = serializers.CharField(max_length=150, trim_whitespace=True)
    version_name = serializers.CharField(max_length=150, trim_whitespace=True, required=False)
    supplier_categories = serializers.ListField(
        child=serializers.ChoiceField(choices=SupplierCategory.choices),
        allow_empty=True,
        max_length=len(SupplierCategory.values),
    )
    status = serializers.ChoiceField(
        choices=PurchaseContractTemplateStatus.choices,
        required=False,
        default=PurchaseContractTemplateStatus.ACTIVE,
    )
    content_config = serializers.JSONField(required=False)
    change_summary = serializers.CharField(max_length=500, allow_blank=True, required=False)
    save_mode = serializers.ChoiceField(
        choices=["CURRENT", "NEW_VERSION"],
        required=False,
        default="NEW_VERSION",
    )

    def validate(self, attrs):
        if self.instance is None and not attrs.get("version_name"):
            raise serializers.ValidationError({"version_name": "请输入版本名称。"})
        if self.instance is None and not isinstance(attrs.get("content_config"), dict):
            raise serializers.ValidationError({"content_config": "请输入模板内容。"})
        if "content_config" in attrs and not isinstance(attrs["content_config"], dict):
            raise serializers.ValidationError({"content_config": "模板内容必须是对象。"})
        categories = attrs.get("supplier_categories", [])
        if len(categories) != len(set(categories)):
            raise serializers.ValidationError({"supplier_categories": "供应商类别不能重复。"})
        return attrs


class PurchaseContractTemplateVersionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseContractTemplateVersion
        fields = [
            "id",
            "version_number",
            "version_name",
            "content_config",
            "change_summary",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = fields

    def get_created_by_name(self, instance):
        return instance.created_by_employee.display_name if instance.created_by_employee else "系统"


class PurchaseContractTemplateSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    current_version = serializers.SerializerMethodField()
    versions = PurchaseContractTemplateVersionSerializer(many=True, read_only=True)
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseContractTemplate
        fields = [
            "id",
            "template_code",
            "template_name",
            "supplier_categories",
            "status",
            "status_display",
            "current_version_number",
            "current_version",
            "versions",
            "updated_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_current_version(self, instance):
        versions = list(instance.versions.all())
        current = next(
            (item for item in versions if item.version_number == instance.current_version_number),
            versions[0] if versions else None,
        )
        return PurchaseContractTemplateVersionSerializer(current).data if current else None

    def get_updated_by_name(self, instance):
        employee = instance.updated_by_employee or instance.created_by_employee
        return employee.display_name if employee else "系统"


class SupplierPurchaseSheetSerializer(serializers.ModelSerializer):
    purchase_order_number = serializers.SerializerMethodField()
    purchase_request_number = serializers.CharField(source="purchase_request.request_number", read_only=True, allow_null=True)
    production_task_number = serializers.SerializerMethodField()
    sales_order_number = serializers.SerializerMethodField()
    is_historical_unlinked = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    template_id = serializers.UUIDField(source="template_version.template_id", read_only=True)
    template_name = serializers.CharField(source="template_version.template.template_name", read_only=True)
    template_version_number = serializers.IntegerField(source="template_version.version_number", read_only=True)
    template_version_name = serializers.CharField(source="template_version.version_name", read_only=True)
    pdf_ready = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()
    line_images = serializers.SerializerMethodField()
    seal_image = serializers.SerializerMethodField()

    class Meta:
        model = SupplierPurchaseSheet
        fields = [
            "id",
            "series_id",
            "purchase_order_id",
            "purchase_order_number",
            "purchase_request_id",
            "purchase_request_number",
            "production_task_number",
            "sales_order_number",
            "is_historical_unlinked",
            "supplier_id",
            "supplier_number_snapshot",
            "supplier_name_snapshot",
            "supplier_phone_snapshot",
            "sheet_number",
            "version_number",
            "procurement_batch_number",
            "is_current",
            "template_version_id",
            "template_id",
            "template_name",
            "template_version_number",
            "template_version_name",
            "status",
            "status_display",
            "content_snapshot",
            "line_images",
            "seal_image",
            "total_amount",
            "pdf_ready",
            "published_at",
            "updated_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_purchase_order_number(self, instance):
        return instance.purchase_order.order_number if instance.purchase_order_id else None

    def get_production_task_number(self, instance):
        if instance.purchase_order_id:
            return instance.purchase_order.production_task_number_snapshot
        if instance.purchase_request_id:
            return instance.purchase_request.production_task.task_number
        return None

    def get_sales_order_number(self, instance):
        if instance.purchase_order_id:
            return instance.purchase_order.sales_order_number_snapshot
        if instance.purchase_request_id:
            task = instance.purchase_request.production_task
            return task.sales_order.order_number if task.sales_order_id else task.order_number
        return None

    def get_is_historical_unlinked(self, instance):
        if instance.purchase_order_id:
            return bool(instance.purchase_order.production_task_id and instance.purchase_order.production_task.sales_order_id is None)
        if instance.purchase_request_id:
            return instance.purchase_request.production_task.sales_order_id is None
        return True

    def get_pdf_ready(self, instance):
        return instance.pdf_file_id is not None

    def get_updated_by_name(self, instance):
        employee = instance.updated_by_employee or instance.created_by_employee
        return employee.display_name if employee else "系统"

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_line_images(self, instance):
        return [
            {
                "source_purchase_order_line_id": str(item.source_purchase_order_line_id),
                "image_file_id": str(item.image_file_id),
                "original_name": item.image_file.original_name,
            }
            for item in instance.line_images.all()
        ]

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_seal_image(self, instance):
        item = getattr(instance, "seal_image", None)
        if item is None:
            return None
        return {
            "image_file_id": str(item.image_file_id),
            "original_name": item.image_file.original_name,
        }


class SupplierPurchaseSheetUpdateSerializer(serializers.Serializer):
    content = serializers.JSONField()

    def validate_content(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("采购表内容必须是对象。")
        return value
