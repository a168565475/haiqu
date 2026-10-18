from apps.access_control.sales_policy import SalesAccessSerializerMixin
from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.customers.models import CustomerAccount, CustomerEntityAddress, CustomerTransactionEntity
from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
from apps.organizations.models import Employee, EmployeeStatus
from apps.products.models import ProductInformation, ProductStatus
from apps.reference_data.models import ProductCategory, ProductColor, ProductionUnit, ReferenceStatus
from apps.quotations.models import QuotationLine, QuotationVersion

from ..models import (
    CollaborationEventStatus,
    CollaborationEventType,
    CustomerConfirmationMethod,
    DeliveryBatchStatus,
    SalesOrder,
    SalesOrderCollaborationEvent,
    SalesOrderDeliveryBatch,
    SalesOrderDeliveryBatchLine,
    SalesOrderEvidence,
    SalesOrderLine,
    SalesOrderPriceException,
    SalesOrderSource,
    SalesOrderStatus,
    SalesOrderVersion,
)
from ..presentation import specification_display


class SalesOrderEmployeeSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ["id", "employee_code", "display_name"]


class SalesOrderExchangeRatePreviewSerializer(serializers.Serializer):
    exchange_rate_record_id = serializers.UUIDField(allow_null=True)
    exchange_rate = serializers.DecimalField(max_digits=22, decimal_places=8)
    exchange_rate_snapshot = serializers.JSONField()


class SalesOrderExchangeRatePreviewResponseSerializer(serializers.Serializer):
    data = SalesOrderExchangeRatePreviewSerializer()


class PriceExceptionSerializer(serializers.ModelSerializer):
    requested_by = SalesOrderEmployeeSummarySerializer(source="requested_by_employee", read_only=True)
    decided_by = SalesOrderEmployeeSummarySerializer(source="decided_by_employee", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SalesOrderPriceException
        fields = [
            "id",
            "requested_unit_price",
            "quoted_unit_price_snapshot",
            "reason",
            "status",
            "status_display",
            "requested_by",
            "decided_by",
            "decided_at",
            "decision_note",
            "created_at",
        ]


class SalesOrderLineReadSerializer(serializers.ModelSerializer):
    specification_display = serializers.SerializerMethodField()
    source_quotation_line_id = serializers.UUIDField(read_only=True, allow_null=True)
    product_id = serializers.UUIDField(read_only=True)
    product_category_id = serializers.UUIDField(read_only=True, allow_null=True)
    product_unit_id = serializers.UUIDField(read_only=True, allow_null=True)
    product_color_id = serializers.UUIDField(read_only=True, allow_null=True)
    product_image_id = serializers.UUIDField(read_only=True, allow_null=True)
    price_exceptions = PriceExceptionSerializer(many=True, read_only=True)

    def get_specification_display(self, instance) -> str:
        return specification_display(instance)

    class Meta:
        model = SalesOrderLine
        fields = [
            "id",
            "line_number",
            "source_quotation_line_id",
            "product_id",
            "product_category_id",
            "product_unit_id",
            "product_color_id",
            "product_image_id",
            "customer_product_name_snapshot",
            "customer_specification_snapshot",
            "customer_color_snapshot",
            "product_number_snapshot",
            "product_code_snapshot",
            "item_number_snapshot",
            "product_name_snapshot",
            "specification_snapshot",
            "specification_display",
            "material_snapshot",
            "unit_code_snapshot",
            "quantity",
            "quoted_quantity_snapshot",
            "quoted_unit_price",
            "unit_price",
            "line_total",
            "unit_price_cny",
            "line_total_cny",
            "price_difference",
            "price_difference_rate",
            "lower_price_reason",
            "quality_requirements",
            "packaging_requirements",
            "shipping_mark_requirements",
            "price_exceptions",
        ]


class DeliveryBatchLineReadSerializer(serializers.ModelSerializer):
    sales_order_line_id = serializers.UUIDField(read_only=True)
    product_name = serializers.CharField(source="sales_order_line.product_name_snapshot", read_only=True)
    product_number = serializers.CharField(source="sales_order_line.product_number_snapshot", read_only=True)
    unit_code = serializers.CharField(source="sales_order_line.unit_code_snapshot", read_only=True)
    allocated_quantity = serializers.SerializerMethodField()
    maximum_quantity = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()

    class Meta:
        model = SalesOrderDeliveryBatchLine
        fields = [
            "id", "sales_order_line_id", "product_name", "product_number", "unit_code", "quantity",
            "allocated_quantity", "maximum_quantity", "remaining_quantity",
        ]

    @staticmethod
    def _allocated_quantity(line):
        direct_products = [
            product
            for product in line.production_task_products.all()
            if product.production_task.status != "CANCELLED"
        ]
        direct_task_ids = {product.production_task_id for product in direct_products}
        allocated = sum((Decimal(product.quantity) for product in direct_products), Decimal("0"))
        legacy_tasks = [
            task
            for task in line.delivery_batch.production_tasks.all()
            if task.pk not in direct_task_ids
            and task.status != "CANCELLED"
            and task.sales_order_line_id == line.sales_order_line_id
        ]
        allocated += sum(
            (
                Decimal(product.quantity)
                for task in legacy_tasks
                for product in task.products.all()
                if product.sales_order_delivery_batch_line_id is None
            ),
            Decimal("0"),
        )
        return allocated

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_allocated_quantity(self, line):
        return format(self._allocated_quantity(line), "f")

    @staticmethod
    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_maximum_quantity(line):
        tolerance = Decimal(line.delivery_batch.sales_order.order_tolerance_percent) / Decimal("100")
        return format(Decimal(line.quantity) * (Decimal("1") + tolerance), "f")

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_remaining_quantity(self, line):
        # 误差允许生产数量浮动，但不增加销售订单的待分配数量。
        return format(max(Decimal(line.quantity) - self._allocated_quantity(line), Decimal("0")), "f")


class DeliveryBatchReadSerializer(serializers.ModelSerializer):
    lines = DeliveryBatchLineReadSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    production_summary = serializers.SerializerMethodField()
    procurement_summary = serializers.SerializerMethodField()

    class Meta:
        model = SalesOrderDeliveryBatch
        fields = [
            "id",
            "line_number",
            "batch_number",
            "planned_delivery_date",
            "status",
            "status_display",
            "cancelled_at",
            "cancellation_reason",
            "notes",
            "lines",
            "production_summary",
            "procurement_summary",
        ]

    def get_production_summary(self, batch):
        relation = getattr(batch, "production_tasks", None)
        if relation is None:
            return {
                "status": "NOT_STARTED",
                "status_display": "未开始",
                "planned_quantity": "0.0000",
                "good_quantity": "0.0000",
                "gap_quantity": "0.0000",
                "orders": [],
            }
        tasks = [item for item in relation.all() if item.status != "CANCELLED"]
        planned_quantity = sum((Decimal(line.quantity) for line in batch.lines.all()), Decimal("0"))
        good_quantity = sum((Decimal(getattr(item, "actual_good_quantity", 0) or 0) for item in tasks), Decimal("0"))
        if good_quantity >= planned_quantity and planned_quantity > 0:
            status_value, status_display = "COMPLETED", "已完成"
        elif any(item.status in {"IN_PRODUCTION", "COMPLETED"} for item in tasks):
            status_value, status_display = "IN_PROGRESS", "进行中"
        else:
            status_value, status_display = "NOT_STARTED", "未开始"
        return {
            "status": status_value,
            "status_display": status_display,
            "planned_quantity": format(planned_quantity, "f"),
            "good_quantity": format(good_quantity, "f"),
            "gap_quantity": format(max(planned_quantity - good_quantity, Decimal("0")), "f"),
            "orders": [
                {
                    "id": str(item.pk),
                    "task_number": item.task_number,
                    "status": item.status,
                    "status_display": item.get_status_display(),
                    "planned_start_date": getattr(item, "planned_start_date", None),
                    "planned_end_date": getattr(item, "planned_end_date", None),
                    "actual_good_quantity": format(Decimal(getattr(item, "actual_good_quantity", 0) or 0), "f"),
                }
                for item in tasks
            ],
        }

    def get_procurement_summary(self, batch):
        relation = getattr(batch, "purchase_requests", None)
        if relation is None:
            return {"bom_confirmed": False, "request_progress": "未生成", "key_material_eta": None, "risk": ""}
        requests = list(relation.all())
        if not requests:
            return {"bom_confirmed": False, "request_progress": "未生成", "key_material_eta": None, "risk": ""}
        line_count = sum(request.lines.count() for request in requests)
        allocated_count = sum(
            1 for request in requests for line in request.lines.all() if Decimal(getattr(line, "remaining_quantity", 0)) <= 0
        )
        etas = [
            allocation.expected_arrival_date
            for request in requests
            for line in request.lines.all()
            for allocation in getattr(line, "allocations", []).all()
            if allocation.expected_arrival_date
        ]
        return {
            "bom_confirmed": all(getattr(request.bom, "status", "") == "VERIFIED" for request in requests),
            "request_progress": f"{allocated_count}/{line_count} 行已分配" if line_count else "无明细",
            "key_material_eta": max(etas) if etas else None,
            "risk": "存在未分配物料" if allocated_count < line_count else "",
        }


class SalesOrderEvidenceSerializer(serializers.ModelSerializer):
    file_id = serializers.UUIDField(source="business_file_id", read_only=True)
    file_name = serializers.CharField(source="business_file.original_name", read_only=True)

    class Meta:
        model = SalesOrderEvidence
        fields = ["id", "file_id", "file_name", "evidence_type", "caption", "created_at"]


class CollaborationEventReadSerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(source="get_event_type_display", read_only=True)
    source_type_display = serializers.CharField(source="get_source_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    recorded_by = SalesOrderEmployeeSummarySerializer(source="recorded_by_employee", read_only=True)
    delivery_batch_id = serializers.UUIDField(read_only=True, allow_null=True)
    evidence_file_name = serializers.CharField(source="evidence_file.original_name", read_only=True, allow_null=True)

    class Meta:
        model = SalesOrderCollaborationEvent
        fields = [
            "id",
            "delivery_batch_id",
            "event_type",
            "event_type_display",
            "source_type",
            "source_type_display",
            "status",
            "status_display",
            "title",
            "note",
            "quantity",
            "occurred_at",
            "evidence_file_id",
            "evidence_file_name",
            "recorded_by",
            "created_at",
        ]


class SalesOrderVersionReadSerializer(serializers.ModelSerializer):
    confirmed_by = SalesOrderEmployeeSummarySerializer(source="confirmed_by_employee", read_only=True)
    change_control = serializers.SerializerMethodField()

    class Meta:
        model = SalesOrderVersion
        fields = ["id", "version_number", "snapshot", "change_reason", "confirmed_by", "confirmed_at", "change_control"]

    def get_change_control(self, instance):
        snapshot = instance.snapshot if isinstance(instance.snapshot, dict) else {}
        value = snapshot.get("change_control")
        return value if isinstance(value, dict) else {}


class SalesOrderListSerializer(SalesAccessSerializerMixin, serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    source_type_display = serializers.CharField(source="get_source_type_display", read_only=True)
    customer_code = serializers.CharField(source="customer_account.account_code", read_only=True)
    customer_name = serializers.CharField(source="customer_account.account_name", read_only=True)
    customer_country_code = serializers.CharField(source="customer_account.primary_country_code", read_only=True)
    salesperson = SalesOrderEmployeeSummarySerializer(read_only=True)
    merchandiser = SalesOrderEmployeeSummarySerializer(read_only=True)
    has_remaining_production_capacity = serializers.SerializerMethodField()
    line_count = serializers.IntegerField(read_only=True)
    delivery_batch_count = serializers.IntegerField(read_only=True)
    next_delivery_date = serializers.DateField(read_only=True, allow_null=True)

    @extend_schema_field(serializers.BooleanField())
    def get_has_remaining_production_capacity(self, instance):
        return any(
            DeliveryBatchLineReadSerializer._allocated_quantity(line) < Decimal(line.quantity)
            for batch in instance.delivery_batches.all() if batch.status == "ACTIVE"
            for line in batch.lines.all()
        )

    class Meta:
        model = SalesOrder
        fields = [
            "allowed_permissions",
            "id",
            "order_number",
            "version_number",
            "source_type",
            "source_type_display",
            "status",
            "status_display",
            "customer_code",
            "customer_name",
            "customer_country_code",
            "customer_po_number",
            "contract_number",
            "order_date",
            "currency_code",
            "total_amount",
            "total_amount_cny",
            "salesperson",
            "merchandiser",
            "has_remaining_production_capacity",
            "line_count",
            "delivery_batch_count",
            "next_delivery_date",
            "confirmed_at",
            "updated_at",
        ]


class SalesOrderDetailSerializer(SalesOrderListSerializer):
    exchange_rate_record_id = serializers.UUIDField(read_only=True, allow_null=True)
    source_quotation_version_id = serializers.UUIDField(read_only=True, allow_null=True)
    source_quotation_number = serializers.CharField(
        source="source_quotation_version.quotation.quotation_number",
        read_only=True,
        allow_null=True,
    )
    transaction_entity_id = serializers.UUIDField(read_only=True, allow_null=True)
    transaction_entity_name = serializers.CharField(source="transaction_entity.legal_name", read_only=True, allow_null=True)
    buyer_address_id = serializers.UUIDField(read_only=True, allow_null=True)
    confirmed_by = SalesOrderEmployeeSummarySerializer(source="confirmed_by_employee", read_only=True)
    confirmation_method_display = serializers.CharField(
        source="get_confirmation_method_display",
        read_only=True,
    )
    lines = SalesOrderLineReadSerializer(many=True, read_only=True)
    delivery_batches = DeliveryBatchReadSerializer(many=True, read_only=True)
    evidence = SalesOrderEvidenceSerializer(source="evidence_links", many=True, read_only=True)
    collaboration_events = CollaborationEventReadSerializer(many=True, read_only=True)
    versions = SalesOrderVersionReadSerializer(many=True, read_only=True)
    has_production_orders = serializers.SerializerMethodField()

    def get_has_production_orders(self, instance):
        return instance.production_tasks.exclude(status="CANCELLED").exists()

    class Meta(SalesOrderListSerializer.Meta):
        fields = SalesOrderListSerializer.Meta.fields + [
            "source_quotation_version_id",
            "source_quotation_number",
            "transaction_entity_id",
            "transaction_entity_name",
            "buyer_address_id",
            "buyer_address_snapshot",
            "direct_order_reason",
            "exchange_rate",
            "exchange_rate_record_id",
            "exchange_rate_snapshot",
            "incoterm_code",
            "payment_terms",
            "deposit_required",
            "includes_tax",
            "tax_basis",
            "order_tolerance_percent",
            "preproduction_sample_required",
            "buyer_snapshot",
            "seller_snapshot",
            "terms_snapshot",
            "customer_requirement_snapshot",
            "confirmation_method",
            "confirmation_method_display",
            "customer_confirmer",
            "customer_confirmed_at",
            "confirmation_summary",
            "confirmed_by",
            "lines",
            "delivery_batches",
            "evidence",
            "collaboration_events",
            "versions",
            "has_production_orders",
        ]


class SalesOrderLineInputSerializer(serializers.Serializer):
    client_key = serializers.CharField(max_length=64)
    source_quotation_line_id = serializers.PrimaryKeyRelatedField(
        source="source_quotation_line",
        queryset=QuotationLine.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )
    product_id = serializers.PrimaryKeyRelatedField(
        source="product",
        queryset=ProductInformation.objects.filter(status=ProductStatus.ACTIVE, archived_at__isnull=True),
        write_only=True,
        required=False,
        allow_null=True,
    )
    product_category_id = serializers.PrimaryKeyRelatedField(
        source="product_category",
        queryset=ProductCategory.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
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
    product_image_id = serializers.PrimaryKeyRelatedField(
        source="product_image",
        queryset=BusinessFile.objects.filter(archived_at__isnull=True, scan_status__in=USABLE_FILE_SCAN_STATUSES),
        required=False,
        allow_null=True,
    )
    customer_product_name_snapshot = serializers.CharField(max_length=200, required=False, allow_blank=True)
    customer_specification_snapshot = serializers.CharField(max_length=500, required=False, allow_blank=True)
    customer_color_snapshot = serializers.CharField(max_length=200, required=False, allow_blank=True)
    material = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    unit_code = serializers.CharField(max_length=30, required=False, allow_blank=True)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    lower_price_reason = serializers.CharField(required=False, allow_blank=True)
    quality_requirements = serializers.CharField(required=False, allow_blank=True)
    packaging_requirements = serializers.CharField(required=False, allow_blank=True)
    shipping_mark_requirements = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        product = attrs.get("product")
        quote_line = attrs.get("source_quotation_line")
        customer_name = str(attrs.get("customer_product_name_snapshot") or "").strip()
        if product is not None:
            submitted_name = customer_name
            submitted_specification = str(attrs.get("customer_specification_snapshot") or "").strip()
            submitted_unit_code = str(attrs.get("unit_code") or "").strip().upper()
            inherited_quote_snapshot = bool(
                quote_line is not None
                and quote_line.product_id == product.pk
                and submitted_name == str(quote_line.product_description_snapshot or "").strip()
                and submitted_specification == str(quote_line.specification_snapshot or "").strip()
                and submitted_unit_code in {"", str(quote_line.unit_code or "").strip().upper()}
            )
            if submitted_name and submitted_name != product.product_name and not inherited_quote_snapshot:
                raise serializers.ValidationError(
                    {"customer_product_name_snapshot": "已关联产品的名称发生变化，请重新选择产品或解除关联后手工录入。"}
                )
            if submitted_specification and submitted_specification != (product.specification or "").strip() and not inherited_quote_snapshot:
                raise serializers.ValidationError(
                    {"customer_specification_snapshot": "已关联产品的规格发生变化，请重新选择产品或解除关联后手工录入。"}
                )
            if submitted_unit_code and submitted_unit_code != product.unit.unit_code and not inherited_quote_snapshot:
                raise serializers.ValidationError(
                    {"unit_code": "已关联产品的单位发生变化，请重新选择产品或解除关联后手工录入。"}
                )
        if product is None and not customer_name:
            source_line = attrs.get("source_quotation_line")
            if source_line is None or not str(source_line.product_description_snapshot or "").strip():
                raise serializers.ValidationError({"customer_product_name_snapshot": "请选择产品，或填写客户产品名称。"})
        if product is None:
            customer_specification = str(attrs.get("customer_specification_snapshot") or "").strip()
            source_line = attrs.get("source_quotation_line")
            if not customer_specification and (
                source_line is None or not str(source_line.specification_snapshot or "").strip()
            ):
                raise serializers.ValidationError({"customer_specification_snapshot": "未关联产品主档时必须填写规格。"})
        return attrs

class DeliveryBatchLineInputSerializer(serializers.Serializer):
    sales_order_line_client_key = serializers.CharField(max_length=64)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))


class DeliveryBatchInputSerializer(serializers.Serializer):
    client_key = serializers.CharField(max_length=64, required=False, allow_blank=False)
    planned_delivery_date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True)
    lines = DeliveryBatchLineInputSerializer(many=True, allow_empty=False)


class SalesOrderWriteSerializer(serializers.Serializer):
    source_type = serializers.ChoiceField(choices=SalesOrderSource.choices)
    source_quotation_version_id = serializers.PrimaryKeyRelatedField(
        source="source_quotation_version",
        queryset=QuotationVersion.objects.select_related("quotation").all(),
        required=False,
        allow_null=True,
        write_only=True,
    )
    customer_account_id = serializers.PrimaryKeyRelatedField(
        source="customer_account",
        queryset=CustomerAccount.objects.filter(archived_at__isnull=True),
        write_only=True,
    )
    transaction_entity_id = serializers.PrimaryKeyRelatedField(
        source="transaction_entity",
        queryset=CustomerTransactionEntity.objects.filter(archived_at__isnull=True),
        required=False,
        allow_null=True,
        write_only=True,
    )
    buyer_address_id = serializers.PrimaryKeyRelatedField(
        source="buyer_address",
        queryset=CustomerEntityAddress.objects.filter(archived_at__isnull=True),
        required=False,
        allow_null=True,
        write_only=True,
    )
    salesperson_id = serializers.PrimaryKeyRelatedField(
        source="salesperson",
        queryset=Employee.objects.filter(status=EmployeeStatus.ACTIVE, archived_at__isnull=True),
        write_only=True,
    )
    merchandiser_id = serializers.PrimaryKeyRelatedField(
        source="merchandiser",
        queryset=Employee.objects.filter(status=EmployeeStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
        write_only=True,
    )
    customer_po_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    contract_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    order_date = serializers.DateField()
    direct_order_reason = serializers.CharField(required=False, allow_blank=True)
    currency_code = serializers.CharField(max_length=3)
    exchange_rate = serializers.DecimalField(max_digits=22, decimal_places=8, read_only=True)
    exchange_rate_record_id = serializers.UUIDField(required=False, allow_null=True)
    incoterm_code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    payment_terms = serializers.CharField(required=False, allow_blank=True)
    deposit_required = serializers.BooleanField(default=False)
    includes_tax = serializers.BooleanField(default=False)
    tax_basis = serializers.CharField(max_length=200, required=False, allow_blank=True)
    order_tolerance_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, default=0)
    preproduction_sample_required = serializers.BooleanField(default=False)
    buyer_snapshot = serializers.JSONField(required=False)
    buyer_address_snapshot = serializers.JSONField(required=False)
    seller_snapshot = serializers.JSONField(required=False)
    terms_snapshot = serializers.JSONField(required=False)
    customer_requirement_snapshot = serializers.JSONField(required=False)
    confirmation_method = serializers.ChoiceField(choices=CustomerConfirmationMethod.choices, required=False, allow_blank=True)
    customer_confirmer = serializers.CharField(max_length=150, required=False, allow_blank=True)
    customer_confirmed_at = serializers.DateTimeField(required=False, allow_null=True)
    confirmation_summary = serializers.CharField(required=False, allow_blank=True)
    evidence_file_ids = serializers.PrimaryKeyRelatedField(
        source="evidence_files",
        queryset=BusinessFile.objects.filter(archived_at__isnull=True, scan_status__in=USABLE_FILE_SCAN_STATUSES),
        many=True,
        required=False,
        write_only=True,
    )
    lines = SalesOrderLineInputSerializer(many=True, allow_empty=False)
    delivery_batches = DeliveryBatchInputSerializer(many=True, required=False)

    def validate_currency_code(self, value):
        return value.strip().upper()

    def validate_incoterm_code(self, value):
        return value.strip().upper()

    def validate(self, attrs):
        lines = attrs.get("lines", [])
        keys = [item["client_key"] for item in lines]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError({"lines": "订单明细 client_key 不能重复。"})
        entity = attrs.get("transaction_entity")
        customer = attrs.get("customer_account")
        if entity and customer and entity.customer_account_id != customer.pk:
            raise serializers.ValidationError({"transaction_entity": "买方主体必须属于当前客户。"})
        address = attrs.get("buyer_address")
        if address and (entity is None or address.transaction_entity_id != entity.pk):
            raise serializers.ValidationError({"buyer_address_id": "买方地址必须属于当前买方主体。"})
        return attrs


class ConfirmedSalesOrderChangeSerializer(serializers.Serializer):
    order = SalesOrderWriteSerializer()
    change_reason = serializers.CharField(allow_blank=False)
    customer_facing_change = serializers.BooleanField(default=False)
    change_evidence_file_id = serializers.PrimaryKeyRelatedField(
        source="change_evidence_file",
        queryset=BusinessFile.objects.filter(archived_at__isnull=True, scan_status__in=USABLE_FILE_SCAN_STATUSES),
        required=False,
        allow_null=True,
    )
    pmc_impact_confirmed = serializers.BooleanField(default=False)


class CollaborationEventInputSerializer(serializers.Serializer):
    delivery_batch_id = serializers.PrimaryKeyRelatedField(
        source="delivery_batch",
        queryset=SalesOrderDeliveryBatch.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )
    event_type = serializers.ChoiceField(choices=CollaborationEventType.choices)
    status = serializers.ChoiceField(choices=CollaborationEventStatus.choices)
    title = serializers.CharField(max_length=200)
    note = serializers.CharField(required=False, allow_blank=True)
    quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=False,
        allow_null=True,
    )
    occurred_at = serializers.DateTimeField()
    evidence_file_id = serializers.PrimaryKeyRelatedField(
        source="evidence_file",
        queryset=BusinessFile.objects.filter(archived_at__isnull=True, scan_status__in=USABLE_FILE_SCAN_STATUSES),
        required=False,
        allow_null=True,
        write_only=True,
    )

    def validate(self, attrs):
        if attrs.get("event_type") == CollaborationEventType.SHIPMENT and attrs.get("status") == CollaborationEventStatus.COMPLETED:
            if attrs.get("quantity") is None:
                raise serializers.ValidationError({"quantity": "已完成的发货事项必须填写本次发货数量。"})
        return attrs


class DeliveryBatchCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000)
    evidence_file_id = serializers.PrimaryKeyRelatedField(
        source="evidence_file",
        queryset=BusinessFile.objects.filter(archived_at__isnull=True, scan_status__in=USABLE_FILE_SCAN_STATUSES),
    )


class SalesOrderCompleteSerializer(serializers.Serializer):
    exception_close = serializers.BooleanField(default=False)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def validate(self, attrs):
        if attrs.get("exception_close") and not attrs.get("reason", "").strip():
            raise serializers.ValidationError({"reason": "异常关闭销售订单必须填写原因。"})
        return attrs
