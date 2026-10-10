import json
from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.customers.models import CustomerAccount
from apps.audit.models import AuditLog
from apps.inquiries.rich_text import sanitize_rich_text
from apps.organizations.models import Employee, EmployeeStatus
from apps.products.models import ProductInformation, ProductStatus
from apps.reference_data.models import Currency, ProductColor, ProductionUnit, ReferenceStatus

from apps.sales_orders.models import SalesOrderDeliveryBatch, SalesOrderDeliveryBatchLine

from ..models import (
    DeliveryMethod,
    OrderSource,
    ProductionPriority,
    ProductionRunBatch,
    ProductionRunBatchStatus,
    ProductionTask,
    ProductionTaskStatus,
)


class ProductionTaskDetailInputSerializer(serializers.Serializer):
    client_key = serializers.RegexField(r"^[A-Za-z0-9_-]{1,64}$", required=False)
    template_key = serializers.CharField(max_length=64, required=False, allow_blank=True)
    detail_type = serializers.CharField(max_length=100, trim_whitespace=True)
    category_label = serializers.CharField(max_length=100, required=False, allow_blank=True, trim_whitespace=True)
    is_selected = serializers.BooleanField(default=False)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True, trim_whitespace=True)

class ProductionTaskProductInputSerializer(serializers.Serializer):
    client_key = serializers.RegexField(r"^[A-Za-z0-9_-]{1,64}$")
    product_id = serializers.PrimaryKeyRelatedField(
        source="product",
        queryset=ProductInformation.objects.filter(status=ProductStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    product_color_id = serializers.PrimaryKeyRelatedField(
        source="product_color",
        queryset=ProductColor.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    color_code = serializers.CharField(max_length=100, required=False, allow_blank=True, trim_whitespace=True)
    customer_product_name = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )
    customer_specification = serializers.CharField(
        max_length=300,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )
    customer_color = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )
    quantity = serializers.IntegerField(min_value=1, max_value=9223372036854775807)
    unit_id = serializers.PrimaryKeyRelatedField(
        source="unit",
        queryset=ProductionUnit.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
    )
    currency_id = serializers.PrimaryKeyRelatedField(
        source="currency",
        queryset=Currency.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
    )
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    exchange_rate = serializers.DecimalField(max_digits=20, decimal_places=3, min_value=Decimal("0.001"))
    special_requirements = serializers.CharField(
        max_length=3000,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
    )
    packaging_method = serializers.CharField(max_length=3000, required=False, allow_blank=True, trim_whitespace=True)
    retained_image_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
    )
    details = ProductionTaskDetailInputSerializer(many=True, required=False)

    def validate_details(self, value):
        keys = [item.get("client_key") for item in value if item.get("client_key")]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError("生产任务单明细的临时编号不能重复。")
        return value


class ProductionDeliveryBatchInputSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    delivery_date = serializers.DateField()
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, trim_whitespace=True)


class ProductionTaskWriteSerializer(serializers.Serializer):
    bom_sync_mode = serializers.ChoiceField(
        choices=["SYNC", "KEEP"],
        required=False,
        write_only=True,
    )
    bom_sync_token = serializers.CharField(required=False, write_only=True, trim_whitespace=False)
    contract_number_token = serializers.CharField(write_only=True, required=False)
    contract_number = serializers.RegexField(
        r"^[A-Z0-9][A-Z0-9._-]*$",
        max_length=50,
        error_messages={"invalid": "合同编号只能包含大写字母、数字、点、下划线和连字符。"},
    )
    order_source = serializers.ChoiceField(choices=OrderSource.choices)
    order_number = serializers.CharField(max_length=100, trim_whitespace=True)
    customer_account_id = serializers.PrimaryKeyRelatedField(
        source="customer_account",
        queryset=CustomerAccount.objects.filter(archived_at__isnull=True),
    )
    order_date = serializers.DateField()
    delivery_date = serializers.DateField()
    salesperson_id = serializers.PrimaryKeyRelatedField(
        source="salesperson",
        queryset=Employee.objects.filter(status=EmployeeStatus.ACTIVE, archived_at__isnull=True),
    )
    follower_ids = serializers.PrimaryKeyRelatedField(
        source="followers",
        queryset=Employee.objects.filter(status=EmployeeStatus.ACTIVE, archived_at__isnull=True),
        many=True,
        allow_empty=True,
    )
    currency_id = serializers.PrimaryKeyRelatedField(
        source="currency",
        queryset=Currency.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
    )
    includes_tax = serializers.BooleanField()
    order_tolerance_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100)
    is_repeat_order = serializers.BooleanField()
    preproduction_sample_required = serializers.BooleanField()
    delivery_method = serializers.ChoiceField(choices=DeliveryMethod.choices)
    special_requirements_html = serializers.CharField(required=False, allow_blank=True)
    freight_amount = serializers.DecimalField(
        max_digits=22,
        decimal_places=4,
        min_value=Decimal("0"),
        required=False,
        default=Decimal("0"),
    )
    other_fee_amount = serializers.DecimalField(
        max_digits=22,
        decimal_places=4,
        min_value=Decimal("0"),
        required=False,
        default=Decimal("0"),
    )
    products = ProductionTaskProductInputSerializer(many=True, allow_empty=False)
    delivery_batches = ProductionDeliveryBatchInputSerializer(many=True, required=False)

    def validate_special_requirements_html(self, value):
        return sanitize_rich_text(value)

    def validate_contract_number(self, value):
        queryset = ProductionTask.objects.filter(contract_number=value)
        current_task_id = self.context.get("current_task_id")
        if current_task_id:
            queryset = queryset.exclude(pk=current_task_id)
        if queryset.exists():
            raise serializers.ValidationError("合同编号已存在，请更换后重试。")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.context.get("require_contract_number_token") and not attrs.get("contract_number_token"):
            raise serializers.ValidationError({"contract_number_token": "请先生成合同编号。"})
        current_task = self.context.get("current_task")
        if current_task is not None and not attrs:
            raise serializers.ValidationError("请至少提交一个需要修改的字段。")

        order_date = attrs.get("order_date", getattr(current_task, "order_date", None))
        delivery_date = attrs.get("delivery_date", getattr(current_task, "delivery_date", None))
        if order_date and delivery_date and delivery_date < order_date:
            raise serializers.ValidationError({"delivery_date": "交期日期不能早于下单日期。"})
        customer = attrs.get("customer_account")
        request = self.context.get("request")
        accessible_ids = self.context.get("accessible_customer_ids")
        if (
            customer is not None
            and request is not None
            and not request.user.is_superuser
            and accessible_ids is not None
            and customer.pk not in accessible_ids
        ):
            raise serializers.ValidationError({"customer_account_id": "客户不存在或当前账号无权使用。"})
        products = attrs.get("products")
        product_keys = [item["client_key"] for item in products or []]
        if len(product_keys) != len(set(product_keys)):
            raise serializers.ValidationError({"products": "产品临时编号不能重复。"})
        detail_keys = []
        currency = attrs.get("currency", getattr(current_task, "currency", None))
        for index, item in enumerate(products or [], start=1):
            product = item.get("product")
            color = item.get("product_color")
            customer_product_name = str(item.get("customer_product_name") or "").strip()
            customer_specification = str(item.get("customer_specification") or "").strip()
            if product is None:
                if not customer_product_name:
                    raise serializers.ValidationError(
                        {"products": f"第 {index} 条未关联产品时必须填写客户产品名称。"}
                    )
                if not customer_specification:
                    raise serializers.ValidationError(
                        {"products": f"第 {index} 条未关联产品时必须填写客户规格。"}
                    )
            if not item.get("details"):
                raise serializers.ValidationError(
                    {"products": f"第 {index} 条颜色明细必须填写生产任务单明细。"}
                )
            detail_keys.extend(
                detail["client_key"] for detail in item["details"] if detail.get("client_key")
            )
            if product is not None and item["unit"].pk != product.unit_id:
                raise serializers.ValidationError(
                    {"products": f"第 {index} 条明细的单位必须使用产品生产维护单位。"}
                )
            if currency is not None and item["currency"].pk != currency.pk:
                raise serializers.ValidationError(
                    {"products": f"第 {index} 条明细的币种必须与基础信息一致。"}
                )
            if color is not None and item.get("color_code", "") != color.color_code:
                raise serializers.ValidationError(
                    {"products": f"第 {index} 条明细的色号与所选色卡、颜色不匹配。"}
                )
            if item["currency"].code == "CNY" and item["exchange_rate"] != Decimal("1"):
                raise serializers.ValidationError(
                    {"products": f"第 {index} 条明细使用 CNY 时汇率必须为 1。"}
                )
            retained_ids = item.get("retained_image_ids", [])
            if len(retained_ids) != len(set(retained_ids)):
                raise serializers.ValidationError(
                    {"products": f"第 {index} 条明细的保留图片不能重复。"}
                )
        if len(detail_keys) != len(set(detail_keys)):
            raise serializers.ValidationError({"products": "不同颜色明细的生产任务单明细临时编号不能重复。"})
        salesperson = attrs.get("salesperson", getattr(current_task, "salesperson", None))
        followers = attrs.get("followers")
        if followers is None and current_task is not None:
            followers = current_task.followers.all()
        for follower in followers or []:
            if salesperson is not None and follower.pk == salesperson.pk:
                raise serializers.ValidationError({"follower_ids": "业务员不需要重复加入跟单员。"})
        batches = attrs.get("delivery_batches")
        if batches is None and current_task is not None and "order_date" in attrs:
            batches = current_task.delivery_batches.all()
        for batch in batches or []:
            batch_delivery_date = (
                batch["delivery_date"] if isinstance(batch, dict) else batch.delivery_date
            )
            if order_date and batch_delivery_date < order_date:
                raise serializers.ValidationError({"delivery_batches": "分批交期不能早于下单日期。"})
        return attrs


class ProductionDeliveryBatchDateInputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    delivery_date = serializers.DateField()

    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = set(data) - {"id", "delivery_date"}
            if unknown:
                raise serializers.ValidationError({key: "此接口只允许修改批次日期。" for key in sorted(unknown)})
        return super().to_internal_value(data)

    def validate(self, attrs):
        # PATCH 的 partial 标记会跳过嵌套 required 检查，必须显式要求两个字段。
        missing = {key: "此字段必填。" for key in ("id", "delivery_date") if key not in attrs}
        if missing:
            raise serializers.ValidationError(missing)
        return attrs


class ProductionTaskPatchSerializer(ProductionTaskWriteSerializer):
    """生产任务精确更新契约。

    任务来源、客户、业务员、币种和费用等头字段不属于 V3 编辑页范围；
    不在这里声明可避免调用方绕过前端只读状态改写销售快照。
    """

    delivery_batch_dates = ProductionDeliveryBatchDateInputSerializer(many=True, required=False, allow_empty=False)

    allowed_field_names = {
        "bom_sync_mode",
        "bom_sync_token",
        "delivery_date",
        "follower_ids",
        "special_requirements_html",
        "products",
        "delivery_batches",
        "delivery_batch_dates",
    }

    def get_fields(self):
        fields = super().get_fields()
        return {
            name: field
            for name, field in fields.items()
            if name in self.allowed_field_names
        }

    def to_internal_value(self, data):
        unknown_fields = sorted(set(data.keys()) - self.allowed_field_names)
        if unknown_fields:
            raise serializers.ValidationError(
                {
                    field_name: "该字段不允许通过生产任务编辑接口修改。"
                    for field_name in unknown_fields
                }
            )
        return super().to_internal_value(data)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if "delivery_batch_dates" in attrs:
            if set(attrs) - {"delivery_date", "delivery_batch_dates"}:
                raise serializers.ValidationError({"delivery_batch_dates": "批次日期只能与任务交期一起修改，请单独保存其他资料。"})
            ids = [item["id"] for item in attrs["delivery_batch_dates"]]
            if len(ids) != len(set(ids)):
                raise serializers.ValidationError({"delivery_batch_dates": "批次编号不能重复。"})
        meaningful_fields = set(attrs) - {"bom_sync_mode", "bom_sync_token"}
        if not meaningful_fields:
            raise serializers.ValidationError("请至少提交一个需要修改的字段。")
        if "delivery_batches" in attrs and "products" not in attrs:
            raise serializers.ValidationError(
                {"delivery_batches": "修改生产批次时必须同时提交产品明细，以便校验数量一致性。"}
            )
        return attrs


class EmployeeBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ["id", "employee_code", "display_name"]


class ProductionTaskDetailReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    line_number = serializers.IntegerField()
    template_key = serializers.CharField()
    detail_type = serializers.CharField()
    category_label = serializers.CharField()
    is_selected = serializers.BooleanField()
    description = serializers.CharField()
    image_name = serializers.CharField(source="image_file.original_name", allow_null=True)


class ProductionTaskProductImageReadSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="image_file_id")
    name = serializers.CharField(source="image_file.original_name")
    content_type = serializers.CharField(source="image_file.content_type")
    size_bytes = serializers.IntegerField(source="image_file.size_bytes")


class ProductionTaskProductReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    line_number = serializers.IntegerField()
    product_id = serializers.UUIDField(allow_null=True)
    source_delivery_batch_line_id = serializers.UUIDField(
        source="sales_order_delivery_batch_line_id", allow_null=True
    )
    source_sales_order_line_id = serializers.UUIDField(
        source="sales_order_delivery_batch_line.sales_order_line_id", allow_null=True
    )
    product_number = serializers.CharField(source="product_number_snapshot")
    product_code = serializers.CharField(source="product_code_snapshot")
    item_number = serializers.CharField(source="item_number_snapshot")
    product_name = serializers.CharField(source="product_name_snapshot")
    specification = serializers.CharField(source="specification_snapshot")
    customer_product_name = serializers.CharField(source="customer_product_name_snapshot")
    customer_specification = serializers.CharField(source="customer_specification_snapshot")
    customer_color = serializers.CharField(source="customer_color_snapshot")
    image_name = serializers.CharField(source="image_file.original_name", allow_null=True)
    product_color_id = serializers.UUIDField(allow_null=True)
    color_card = serializers.CharField(source="color_card_snapshot")
    color_name = serializers.CharField(source="color_name_snapshot")
    color_code = serializers.CharField(source="color_code_snapshot")
    quantity = serializers.IntegerField()
    unit_id = serializers.UUIDField()
    unit_code = serializers.CharField(source="unit.unit_code")
    unit_name = serializers.CharField(source="unit.unit_name")
    currency_id = serializers.UUIDField()
    currency_code = serializers.CharField(source="currency.code")
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4)
    total_amount = serializers.DecimalField(max_digits=22, decimal_places=4)
    exchange_rate = serializers.DecimalField(max_digits=20, decimal_places=3)
    local_unit_price = serializers.SerializerMethodField()
    local_total_amount = serializers.SerializerMethodField()
    special_requirements = serializers.CharField()
    packaging_method = serializers.CharField()
    images = ProductionTaskProductImageReadSerializer(many=True)
    details = ProductionTaskDetailReadSerializer(many=True)

    @extend_schema_field(serializers.DecimalField(max_digits=22, decimal_places=4))
    def get_local_unit_price(self, instance) -> Decimal:
        return (instance.unit_price * instance.exchange_rate).quantize(Decimal("0.0001"))

    @extend_schema_field(serializers.DecimalField(max_digits=22, decimal_places=4))
    def get_local_total_amount(self, instance) -> Decimal:
        return (instance.total_amount * instance.exchange_rate).quantize(Decimal("0.0001"))


class ProductionDeliveryBatchReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    line_number = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    delivery_date = serializers.DateField()
    note = serializers.CharField()


class ProductionRunBatchReadSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ProductionRunBatch
        fields = [
            "id",
            "batch_number",
            "planned_quantity",
            "actual_quantity",
            "good_quantity",
            "status",
            "status_display",
            "started_at",
            "completed_at",
            "note",
        ]


class ProductionTaskReadSerializer(serializers.ModelSerializer):
    special_requirements_html = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display")
    order_source_display = serializers.CharField(source="get_order_source_display")
    delivery_method_display = serializers.CharField(source="get_delivery_method_display")
    customer_id = serializers.UUIDField(source="customer_account_id")
    customer_code = serializers.CharField(source="customer_account.account_code")
    customer_name = serializers.CharField(source="customer_account.account_name")
    salesperson = EmployeeBriefSerializer()
    followers = EmployeeBriefSerializer(many=True)
    currency_id = serializers.UUIDField()
    currency_code = serializers.CharField(source="currency.code")
    products = ProductionTaskProductReadSerializer(many=True)
    delivery_batches = ProductionDeliveryBatchReadSerializer(many=True)
    total_quantity = serializers.SerializerMethodField()
    product_total_amount = serializers.SerializerMethodField()
    total_amount = serializers.SerializerMethodField()
    batch_total_quantity = serializers.SerializerMethodField()
    quantity_difference = serializers.SerializerMethodField()
    production_priority_display = serializers.CharField(source="get_production_priority_display", read_only=True)
    planner = EmployeeBriefSerializer(read_only=True)
    accepted_by = EmployeeBriefSerializer(source="accepted_by_employee", read_only=True)
    start_waiver_by = EmployeeBriefSerializer(source="start_waiver_by_employee", read_only=True)
    sales_order_id = serializers.UUIDField(read_only=True, allow_null=True)
    sales_order_delivery_batch_id = serializers.UUIDField(read_only=True, allow_null=True)
    sales_order_line_id = serializers.UUIDField(read_only=True, allow_null=True)
    source_sales_order_number = serializers.CharField(source="sales_order.order_number", read_only=True, allow_null=True)
    source_delivery_batch_number = serializers.CharField(
        source="sales_order_delivery_batch.batch_number",
        read_only=True,
        allow_null=True,
    )
    is_historical_unlinked = serializers.SerializerMethodField()
    run_batches = ProductionRunBatchReadSerializer(many=True, read_only=True)
    current_boms = serializers.SerializerMethodField()
    pmc_confirmation = serializers.SerializerMethodField()
    audit_timeline = serializers.SerializerMethodField()

    class Meta:
        model = ProductionTask
        fields = [
            "id", "task_number", "contract_number", "order_source", "order_source_display", "order_number",
            "customer_id", "customer_code", "customer_name", "order_date", "delivery_date", "salesperson",
            "followers", "currency_id", "currency_code", "includes_tax", "order_tolerance_percent",
            "is_repeat_order", "preproduction_sample_required", "delivery_method", "delivery_method_display",
            "special_requirements_html", "freight_amount", "other_fee_amount",
            "product_total_amount", "total_amount",
            "status", "status_display", "status_reason", "total_quantity", "batch_total_quantity",
            "quantity_difference", "products", "delivery_batches", "created_at", "updated_at", "submitted_at",
            "sales_order_id", "sales_order_delivery_batch_id", "sales_order_line_id",
            "source_sales_order_number", "source_delivery_batch_number", "is_historical_unlinked",
            "planned_start_date", "planned_end_date", "production_priority", "production_priority_display",
            "production_batch_number", "planner", "accepted_by", "started_at", "completed_at",
            "start_waiver_reason", "start_waiver_by", "start_waiver_at", "actual_quantity",
            "actual_good_quantity", "excess_quantity", "run_batches", "current_boms",
            "pmc_confirmation", "audit_timeline",
        ]

    @extend_schema_field(serializers.CharField())
    def get_special_requirements_html(self, instance):
        value = instance.special_requirements_html
        if not value or not instance.sales_order_id or not value.lstrip().startswith("{"):
            return value
        try:
            snapshot = json.loads(value)
        except (TypeError, ValueError):
            return value
        if isinstance(snapshot, dict):
            source_order = instance.sales_order
            # 订单快照可能在确认后更新；来源报价版本在业务流程中锁定，可继续识别旧快照。
            source_quote = source_order.source_quotation_version if source_order.source_quotation_version_id else None
            if snapshot == source_order.customer_requirement_snapshot or (
                source_quote is not None and snapshot == source_quote.customer_requirement_snapshot
            ):
                return ""
        return value

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_current_boms(self, instance):
        from apps.boms.models import Bom

        latest_by_product_line = []
        seen_product_lines = set()
        queryset = Bom.objects.filter(
            production_task=instance,
            archived_at__isnull=True,
        ).select_related(
            "product_line",
            "product_line__product_color",
            "confirmed_by_employee",
        ).order_by("product_line_id", "-version_number", "-created_at", "-id")
        for bom in queryset:
            if bom.product_line_id in seen_product_lines:
                continue
            seen_product_lines.add(bom.product_line_id)
            latest_by_product_line.append(
                {
                    "id": str(bom.pk),
                    "product_line_id": str(bom.product_line_id),
                    "bom_number": bom.bom_number,
                    "version_number": bom.version_number,
                    "status": bom.status,
                    "status_display": bom.get_status_display(),
                    "product_code": bom.product_code_snapshot,
                    "product_name": bom.product_name_snapshot,
                    "color_name": bom.product_line.color_name_snapshot,
                    "color_code": bom.product_line.color_code_snapshot,
                    "order_quantity": str(bom.order_quantity),
                    "is_order_quantity_outdated": bom.order_quantity != bom.product_line.quantity,
                    "confirmed_by_name": (
                        bom.confirmed_by_employee.display_name if bom.confirmed_by_employee else ""
                    ),
                    "confirmed_at": bom.confirmed_at,
                }
            )
        return latest_by_product_line

    @staticmethod
    def _task_audit_queryset(instance):
        return AuditLog.objects.filter(
            object_type="PRODUCTION_TASK",
            object_id=instance.pk,
        ).order_by("-occurred_at", "-id")

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_pmc_confirmation(self, instance):
        event = self._task_audit_queryset(instance).filter(action="CONFIRMED").first()
        if event is None:
            return None
        return {
            "actor_employee_id": str(event.actor_employee_id) if event.actor_employee_id else None,
            "actor_name": event.actor_name_snapshot,
            "confirmed_at": event.occurred_at,
        }

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_audit_timeline(self, instance):
        action_labels = {
            "CREATED": "创建生产任务单",
            "CREATED_FROM_SALES_ORDER": "从销售订单创建生产任务单",
            "UPDATED": "修改生产任务单",
            "SUBMITTED": "提交 PMC 确认",
            "RETURNED_BY_PMC": "PMC 退回",
            "CONFIRMED": "PMC 确认",
            "SCHEDULED": "完成计划排产",
            "SCHEDULE_VOIDED": "排产作废",
            "STARTED": "开始生产（历史）",
            "COMPLETED": "完成生产",
            "COMPLETED_EXCEPTION": "异常完成生产",
            "CANCELLED": "取消生产任务单",
        }
        return [
            {
                "id": str(event.pk),
                "action": event.action,
                "action_display": action_labels.get(event.action, event.action),
                "actor_employee_id": str(event.actor_employee_id) if event.actor_employee_id else None,
                "actor_name": event.actor_name_snapshot,
                "occurred_at": event.occurred_at,
                "status": str((event.after_data or {}).get("status") or ""),
                "reason": str((event.after_data or {}).get("status_reason") or ""),
            }
            for event in self._task_audit_queryset(instance)[:50]
        ]

    def get_is_historical_unlinked(self, instance):
        return instance.sales_order_id is None

    @staticmethod
    def _sum(items, field):
        return sum((getattr(item, field) for item in items), Decimal("0"))

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_total_quantity(self, instance) -> Decimal:
        return self._sum(instance.products.all(), "quantity")

    @extend_schema_field(serializers.DecimalField(max_digits=22, decimal_places=4))
    def get_product_total_amount(self, instance) -> Decimal:
        return self._sum(instance.products.all(), "total_amount")

    @extend_schema_field(serializers.DecimalField(max_digits=22, decimal_places=4))
    def get_total_amount(self, instance) -> Decimal:
        return self.get_product_total_amount(instance) + instance.freight_amount + instance.other_fee_amount

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_batch_total_quantity(self, instance) -> Decimal:
        return self._sum(instance.delivery_batches.all(), "quantity")

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_quantity_difference(self, instance) -> Decimal:
        batches = list(instance.delivery_batches.all())
        if not batches:
            return Decimal("0")
        return self.get_total_quantity(instance) - self._sum(batches, "quantity")


class ProductionTaskListSerializer(ProductionTaskReadSerializer):
    bom_status = serializers.SerializerMethodField()
    bom_status_display = serializers.SerializerMethodField()
    purchase_status = serializers.SerializerMethodField()
    purchase_status_display = serializers.SerializerMethodField()

    class Meta(ProductionTaskReadSerializer.Meta):
        fields = [
            "id", "task_number", "contract_number", "order_source", "order_source_display", "order_number",
            "customer_id", "customer_code", "customer_name", "order_date", "delivery_date", "salesperson",
            "followers", "currency_code", "delivery_method", "delivery_method_display", "status", "status_display", "status_reason",
            "total_quantity", "total_amount", "batch_total_quantity", "quantity_difference", "products", "created_at", "updated_at",
            "sales_order_id", "source_sales_order_number", "source_delivery_batch_number", "is_historical_unlinked",
            "planned_start_date", "planned_end_date", "production_priority", "production_priority_display",
            "actual_good_quantity", "bom_status", "bom_status_display", "purchase_status",
            "purchase_status_display",
        ]

    def _bom_status_summary(self, instance):
        cached = getattr(instance, "_serialized_bom_status_summary", None)
        if cached is not None:
            return cached

        boms = getattr(instance, "_active_boms_for_status", None)
        if boms is None:
            boms = list(
                instance.boms.filter(archived_at__isnull=True).order_by(
                    "product_line_id", "-version_number", "-created_at", "-id"
                )
            )
        latest_boms = []
        seen_product_lines = set()
        for bom in boms:
            if bom.product_line_id in seen_product_lines:
                continue
            seen_product_lines.add(bom.product_line_id)
            latest_boms.append(bom)

        product_count = len(instance.products.all())
        if not latest_boms:
            summary = ("NOT_CREATED", "未建立")
        elif len(latest_boms) < product_count:
            summary = ("PARTIAL", "部分建立")
        elif any(bom.status != "VERIFIED" for bom in latest_boms):
            summary = ("PENDING_CONFIRMATION", "待确认")
        else:
            summary = ("VERIFIED", "已确认")
        instance._serialized_bom_status_summary = summary
        return summary

    def _purchase_status_summary(self, instance):
        cached = getattr(instance, "_serialized_purchase_status_summary", None)
        if cached is not None:
            return cached

        purchase_order = getattr(instance, "purchase_order", None)
        if purchase_order is not None and purchase_order.archived_at is None:
            summary = (f"ORDER_{purchase_order.status}", purchase_order.get_status_display())
            instance._serialized_purchase_status_summary = summary
            return summary

        requests = getattr(instance, "_active_purchase_requests_for_status", None)
        if requests is None:
            requests = list(instance.purchase_requests.filter(archived_at__isnull=True))
        request_statuses = {request.status for request in requests}
        if not requests:
            summary = ("NOT_STARTED", "未发起")
        elif len(request_statuses) > 1:
            summary = ("REQUEST_MIXED", "多状态")
        elif request_statuses == {"CANCELLED"}:
            summary = ("REQUEST_CANCELLED", "采购申请已取消")
        elif request_statuses == {"FULLY_ALLOCATED"}:
            summary = ("REQUEST_FULLY_ALLOCATED", "采购申请已分配")
        elif request_statuses == {"ALLOCATING"}:
            summary = ("REQUEST_ALLOCATING", "供应商分配中")
        elif request_statuses == {"SUBMITTED"}:
            summary = ("REQUEST_SUBMITTED", "采购申请已提交")
        else:
            summary = ("REQUEST_DRAFT", "采购申请草稿")
        instance._serialized_purchase_status_summary = summary
        return summary

    @extend_schema_field(serializers.CharField())
    def get_bom_status(self, instance):
        return self._bom_status_summary(instance)[0]

    @extend_schema_field(serializers.CharField())
    def get_bom_status_display(self, instance):
        return self._bom_status_summary(instance)[1]

    @extend_schema_field(serializers.CharField())
    def get_purchase_status(self, instance):
        return self._purchase_status_summary(instance)[0]

    @extend_schema_field(serializers.CharField())
    def get_purchase_status_display(self, instance):
        return self._purchase_status_summary(instance)[1]


class ProductionTaskReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class ProductionTaskSalesSourceLineSerializer(serializers.Serializer):
    delivery_batch_line_id = serializers.PrimaryKeyRelatedField(
        source="delivery_batch_line",
        queryset=SalesOrderDeliveryBatchLine.objects.select_related(
            "delivery_batch__sales_order__customer_account",
            "delivery_batch__sales_order__salesperson",
            "delivery_batch__sales_order__merchandiser",
            "sales_order_line__product__unit",
        ),
    )
    quantity = serializers.IntegerField(min_value=1)
    product_color_id = serializers.PrimaryKeyRelatedField(
        source="product_color",
        queryset=ProductColor.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    special_requirements = serializers.CharField(max_length=2000, required=False, allow_blank=True, trim_whitespace=True)
    packaging_method = serializers.CharField(max_length=2000, required=False, allow_blank=True, trim_whitespace=True)


class ProductionTaskCreateFromSalesOrderSerializer(serializers.Serializer):
    request_key = serializers.UUIDField(required=False)
    delivery_batch_line_id = serializers.PrimaryKeyRelatedField(
        source="delivery_batch_line",
        queryset=SalesOrderDeliveryBatchLine.objects.select_related(
            "delivery_batch__sales_order__customer_account",
            "delivery_batch__sales_order__salesperson",
            "delivery_batch__sales_order__merchandiser",
            "sales_order_line__product__unit",
        ),
        required=False,
    )
    quantity = serializers.IntegerField(min_value=1, required=False)
    product_color_id = serializers.PrimaryKeyRelatedField(
        source="product_color",
        queryset=ProductColor.objects.filter(status=ReferenceStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    delivery_batch_id = serializers.PrimaryKeyRelatedField(
        source="delivery_batch",
        queryset=SalesOrderDeliveryBatch.objects.select_related("sales_order"),
        required=False,
    )
    lines = ProductionTaskSalesSourceLineSerializer(many=True, required=False, allow_empty=False)
    planned_start_date = serializers.DateField(required=False, allow_null=True)
    planned_end_date = serializers.DateField(required=False, allow_null=True)
    production_priority = serializers.ChoiceField(choices=ProductionPriority.choices, default=ProductionPriority.NORMAL)
    production_batch_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    planner_id = serializers.PrimaryKeyRelatedField(
        source="planner",
        queryset=Employee.objects.filter(status=EmployeeStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        accessible_order_ids = self.context.get("accessible_sales_order_ids")
        if accessible_order_ids is None:
            return
        self.fields["delivery_batch_line_id"].queryset = (
            self.fields["delivery_batch_line_id"].queryset.filter(
                delivery_batch__sales_order_id__in=accessible_order_ids
            )
        )
        self.fields["delivery_batch_id"].queryset = self.fields["delivery_batch_id"].queryset.filter(
            sales_order_id__in=accessible_order_ids
        )
        nested_line_field = self.fields["lines"].child.fields["delivery_batch_line_id"]
        nested_line_field.queryset = nested_line_field.queryset.filter(
            delivery_batch__sales_order_id__in=accessible_order_ids
        )

    def validate(self, attrs):
        uses_legacy = any(key in attrs for key in ("delivery_batch_line", "quantity", "product_color"))
        uses_lines = any(key in attrs for key in ("delivery_batch", "lines"))
        if uses_legacy and uses_lines:
            raise serializers.ValidationError("单行兼容参数和多行参数不能同时使用。")
        if not uses_legacy and not uses_lines:
            raise serializers.ValidationError("请提交单个交付批次行，或提交 delivery_batch_id + lines。")
        if uses_legacy:
            if "delivery_batch_line" not in attrs or "quantity" not in attrs:
                raise serializers.ValidationError({"delivery_batch_line_id": "单行创建必须同时填写交付批次行和数量。"})
            source_order_id = attrs["delivery_batch_line"].delivery_batch.sales_order_id
        else:
            delivery_batch = attrs.get("delivery_batch")
            lines = attrs.get("lines")
            if delivery_batch is None or not lines:
                raise serializers.ValidationError({"lines": "多行创建必须同时填写交付批次和至少一条产品颜色明细。"})
            if len(lines) > 50:
                raise serializers.ValidationError({"lines": "一次最多创建 50 条产品颜色明细。"})
            seen_pairs = set()
            for index, item in enumerate(lines, start=1):
                source_line = item["delivery_batch_line"]
                if source_line.delivery_batch_id != delivery_batch.pk:
                    raise serializers.ValidationError({"lines": f"第 {index} 条来源不属于所选交付批次。"})
                pair = (source_line.pk, getattr(item.get("product_color"), "pk", None))
                if pair in seen_pairs:
                    raise serializers.ValidationError({"lines": f"第 {index} 条产品颜色明细重复。"})
                seen_pairs.add(pair)
            source_order_id = delivery_batch.sales_order_id
        accessible_order_ids = self.context.get("accessible_sales_order_ids")
        if accessible_order_ids is not None and source_order_id not in accessible_order_ids:
            raise serializers.ValidationError({"delivery_batch_id": "销售订单不存在或当前账号无权使用。"})
        start = attrs.get("planned_start_date")
        end = attrs.get("planned_end_date")
        if (start is None) != (end is None):
            raise serializers.ValidationError({"planned_end_date": "计划开始和计划完工日期需同时填写或同时留空。"})
        if start and end and end < start:
            raise serializers.ValidationError({"planned_end_date": "计划完工日期不能早于计划开始日期。"})
        return attrs


class ProductionTaskPmcDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["CONFIRM", "RETURN"])
    planned_start_date = serializers.DateField(required=False, allow_null=True)
    planned_end_date = serializers.DateField(required=False, allow_null=True)
    production_priority = serializers.ChoiceField(choices=ProductionPriority.choices, required=False)
    production_batch_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    planner_id = serializers.PrimaryKeyRelatedField(
        source="planner",
        queryset=Employee.objects.filter(status=EmployeeStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["decision"] == "RETURN" and not attrs.get("reason", "").strip():
            raise serializers.ValidationError({"reason": "退回业务跟单时必须填写原因。"})
        start = attrs.get("planned_start_date")
        end = attrs.get("planned_end_date")
        if start and end and end < start:
            raise serializers.ValidationError({"planned_end_date": "计划完工日期不能早于计划开始日期。"})
        return attrs


class ProductionTaskStartSerializer(serializers.Serializer):
    start_waiver_reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class ProductionRunBatchInputSerializer(serializers.Serializer):
    batch_number = serializers.CharField(max_length=100)
    planned_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
    actual_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    good_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    status = serializers.ChoiceField(choices=ProductionRunBatchStatus.choices)
    note = serializers.CharField(required=False, allow_blank=True)


class ProductionTaskCompleteSerializer(serializers.Serializer):
    actual_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    actual_good_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    run_batches = ProductionRunBatchInputSerializer(many=True, required=False)
