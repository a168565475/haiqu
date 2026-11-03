from types import SimpleNamespace

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.sales_orders.presentation import specification_display

from ..group_selectors import purchase_batch_display_status, purchase_group_completion_summary, purchase_group_progress
from ..models import PurchaseBatchType, PurchaseGroup, PurchaseOrderStatus
from .serializers import PurchaseOrderUpdateLineSerializer


class PurchaseGroupCreateSerializer(serializers.Serializer):
    production_task_id = serializers.UUIDField()
    bom_id = serializers.UUIDField()
    source_revision = serializers.RegexField(regex=r"^[0-9a-f]{64}$", max_length=64)


class PurchaseGroupCompleteSerializer(serializers.Serializer):
    remark = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000, trim_whitespace=True)


class PurchaseGroupCompletionSerializer(serializers.Serializer):
    can_complete = serializers.BooleanField(read_only=True)
    blocked_reason = serializers.CharField(read_only=True)


class PurchaseGroupTaskOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    task_number = serializers.CharField()
    order_number = serializers.CharField(allow_blank=True)


class PurchaseGroupFilterOptionsSerializer(serializers.Serializer):
    production_tasks = PurchaseGroupTaskOptionSerializer(many=True)


class PurchaseBatchLineSerializer(PurchaseOrderUpdateLineSerializer):
    id = None
    purchase_group_line_id = serializers.UUIDField()


class PurchaseBatchCreateSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    batch_type = serializers.ChoiceField(choices=PurchaseBatchType.choices)
    currency_id = serializers.UUIDField()
    is_mailed = serializers.BooleanField(required=False, allow_null=True, default=None)
    lines = PurchaseBatchLineSerializer(many=True, allow_empty=False, max_length=5000)

    def validate_lines(self, lines):
        keys = [line["purchase_group_line_id"] for line in lines]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError("同一材料不能在一个批次中重复。")
        for line in lines:
            if line.get("actual_bar_count") is None and line.get("actual_purchase_quantity") is None:
                raise serializers.ValidationError("所选材料必须填写实际采购数量或管材根数。")
        return lines


class PurchaseGroupProgressLineSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    line_number = serializers.IntegerField()
    source_bom_line_id_snapshot = serializers.UUIDField(allow_null=True)
    product_line_id_snapshot = serializers.UUIDField(allow_null=True)
    required_quantity = serializers.DecimalField(max_digits=22, decimal_places=4, allow_null=True)
    source_unit_text = serializers.CharField()
    source_snapshot = serializers.JSONField()
    purchased_quantity = serializers.DecimalField(max_digits=30, decimal_places=4, allow_null=True)
    accepted_quantity = serializers.DecimalField(max_digits=30, decimal_places=4, allow_null=True)
    purchased_bar_count = serializers.DecimalField(max_digits=30, decimal_places=0, allow_null=True, read_only=True)
    accepted_bar_count = serializers.DecimalField(max_digits=30, decimal_places=0, allow_null=True, read_only=True)
    in_progress_quantity = serializers.DecimalField(max_digits=30, decimal_places=4, allow_null=True, read_only=True)
    in_progress_bar_count = serializers.DecimalField(max_digits=30, decimal_places=0, allow_null=True, read_only=True)
    progress_percent = serializers.DecimalField(max_digits=38, decimal_places=4, allow_null=True)
    is_satisfied = serializers.BooleanField()
    compatibility_issues = serializers.ListField(child=serializers.CharField())


class PurchaseGroupProgressSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["PENDING", "PURCHASING", "COMPLETED", "UNKNOWN"])
    satisfied_line_count = serializers.IntegerField()
    line_count = serializers.IntegerField()
    lines = PurchaseGroupProgressLineSerializer(many=True)


class PurchaseBatchSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order_number = serializers.CharField()
    batch_number = serializers.IntegerField()
    batch_type = serializers.ChoiceField(choices=PurchaseBatchType.choices)
    status = serializers.CharField()
    display_status = serializers.SerializerMethodField()
    currency_code_snapshot = serializers.CharField()
    total_amount = serializers.DecimalField(max_digits=22, decimal_places=4, allow_null=True)

    @extend_schema_field(serializers.ChoiceField(choices=PurchaseOrderStatus.choices))
    def get_display_status(self, instance):
        return purchase_batch_display_status(instance)


class PurchaseGroupProductSerializer(serializers.Serializer):
    product_line_id = serializers.UUIDField()
    product_name = serializers.CharField(allow_blank=True)
    specification = serializers.CharField(allow_blank=True)
    material = serializers.CharField(allow_blank=True)
    color_card = serializers.CharField(allow_blank=True)
    color_name = serializers.CharField(allow_blank=True)
    color_code = serializers.CharField(allow_blank=True)
    order_quantity = serializers.CharField(allow_null=True)
    order_unit = serializers.CharField(allow_blank=True)


class PurchaseGroupSerializer(serializers.ModelSerializer):
    product = serializers.SerializerMethodField()
    order_delivery_date = serializers.DateField(source="production_task.delivery_date", read_only=True, allow_null=True)
    progress = serializers.SerializerMethodField()
    batches = PurchaseBatchSummarySerializer(many=True, read_only=True)
    display_status = serializers.SerializerMethodField()
    completion = serializers.SerializerMethodField()
    manual_completed_by_name = serializers.CharField(
        source="manual_completed_by_employee.display_name", read_only=True, default="",
    )

    class Meta:
        model = PurchaseGroup
        fields = ["id", "group_number", "production_task_id", "product_line_id_snapshot", "source_bom_id_snapshot",
                  "production_task_number_snapshot", "sales_order_number_snapshot", "customer_name_snapshot",
                  "source_revision", "compatibility_issues", "product", "order_delivery_date",
                  "progress", "batches", "display_status", "completion", "manual_completed_at",
                  "manual_completed_by_name", "manual_completion_remark", "created_at", "updated_at"]
        read_only_fields = fields

    @extend_schema_field(PurchaseGroupProgressSerializer)
    def get_progress(self, instance):
        return PurchaseGroupProgressSerializer(purchase_group_progress(instance)).data

    @extend_schema_field(serializers.ChoiceField(choices=["PENDING", "PURCHASING", "COMPLETED", "UNKNOWN"]))
    def get_display_status(self, instance):
        return "COMPLETED" if instance.manual_completed_at else purchase_group_progress(instance)["status"]

    @extend_schema_field(PurchaseGroupCompletionSerializer)
    def get_completion(self, instance):
        return purchase_group_completion_summary(instance)

    @extend_schema_field(PurchaseGroupProductSerializer(allow_null=True))
    def get_product(self, instance):
        product_id = instance.product_line_id_snapshot
        if product_id is None:
            return None
        # 仅使用本任务预取的订单产品快照，不能按第一产品或当前产品主档补历史。
        product = next((item for item in getattr(instance.production_task, "purchase_group_products", [])
                        if item.pk == product_id and item.production_task_id == instance.production_task_id), None)
        source = next((line for line in instance.lines.all()
                       if line.product_line_id_snapshot == product_id and isinstance(line.source_snapshot, dict)), None)
        if product is None and source is None:
            return None
        snapshot = source.source_snapshot if source else {}
        material = product.material_snapshot if product else ""
        color_name = product.color_name_snapshot if product else ""
        data = {
            "product_line_id": product_id,
            "product_name": snapshot.get("product_name_snapshot", product.product_name_snapshot if product else "") or "",
            "specification": specification_display(SimpleNamespace(
                specification_snapshot=snapshot.get("product_specification_snapshot", product.specification_snapshot if product else ""),
                color_snapshot=color_name, material_snapshot=material,
            )),
            "material": material,
            "color_card": product.color_card_snapshot if product else "",
            "color_name": color_name,
            "color_code": product.color_code_snapshot if product else "",
            "order_quantity": str(product.quantity) if product and product.quantity is not None else None,
            "order_unit": product.unit.unit_name if product and product.unit_id else "",
        }
        return PurchaseGroupProductSerializer(data).data
