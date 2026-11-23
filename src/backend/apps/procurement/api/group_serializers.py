from types import SimpleNamespace

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.sales_orders.presentation import specification_display

from ..group_selectors import (
    purchase_batch_display_status, purchase_group_batch_numbers, purchase_group_completion_summary,
    purchase_group_deletion_summary, purchase_group_progress,
)
from ..models import PurchaseBatchType, PurchaseGroup, PurchaseOrderStatus
from .serializers import PurchaseOrderUpdateLineSerializer


class PurchaseGroupBomInputSerializer(serializers.Serializer):
    bom_id = serializers.UUIDField()
    source_revision = serializers.RegexField(regex=r"^[0-9a-f]{64}$", max_length=64)


class PurchaseGroupCreateSerializer(serializers.Serializer):
    production_task_id = serializers.UUIDField()
    bom_id = serializers.UUIDField(required=False)
    source_revision = serializers.RegexField(regex=r"^[0-9a-f]{64}$", max_length=64, required=False)
    sources = PurchaseGroupBomInputSerializer(many=True, allow_empty=False, required=False)

    def validate(self, attrs):
        if "sources" in attrs:
            if "bom_id" in attrs or "source_revision" in attrs:
                raise serializers.ValidationError({"sources": "请仅使用一种 BOM 来源填写方式。"})
            ids = [entry["bom_id"] for entry in attrs["sources"]]
            if len(set(ids)) != len(ids):
                raise serializers.ValidationError({"sources": "同一份 BOM 不能重复选择。"})
        elif "bom_id" not in attrs or "source_revision" not in attrs:
            raise serializers.ValidationError({"sources": "请选择产品 BOM，并重新读取对应的来源版本。"})
        return attrs


class PurchaseGroupCompleteSerializer(serializers.Serializer):
    remark = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000, trim_whitespace=True)


class PurchaseGroupCompletionSerializer(serializers.Serializer):
    can_complete = serializers.BooleanField(read_only=True)
    blocked_reason = serializers.CharField(read_only=True)


class PurchaseGroupDeletionSerializer(serializers.Serializer):
    can_delete = serializers.BooleanField(read_only=True)
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
    actual_purchase_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=0,
                                                        required=False, allow_null=True, default=None)


class PurchaseBatchCreateSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    batch_session_id = serializers.UUIDField(required=False)
    batch_type = serializers.ChoiceField(choices=PurchaseBatchType.choices)
    currency_id = serializers.UUIDField()
    lines = PurchaseBatchLineSerializer(many=True, allow_empty=False, max_length=5000)

    def validate_lines(self, lines):
        keys = [line["purchase_group_line_id"] for line in lines]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError("同一材料不能在一个批次中重复。")
        for line in lines:
            if not line.get("set_pricing") and line.get("unit_price") == 0:
                continue
            if line.get("actual_bar_count") is None and line.get("actual_purchase_quantity") is None:
                raise serializers.ValidationError("所选材料必须填写实际采购数量或管材根数。")
        return lines


class PurchaseBatchReadySerializer(PurchaseBatchCreateSerializer):
    def validate_lines(self, lines):
        lines = super().validate_lines(lines)
        for line in lines:
            if not line["supplier_id"]:
                raise serializers.ValidationError("请选择本次采购的供应商。")
            if line["actual_purchase_quantity"] == 0 or (
                not line.get("set_pricing") and not line["unit_price"]
            ):
                raise serializers.ValidationError("采购数量和单价必须大于 0。")
            if not line["delivery_date"]:
                raise serializers.ValidationError("请填写本次采购明细的交期。")
        return lines


class PurchaseSupplierBatchSubmitSerializer(PurchaseBatchReadySerializer):
    save_as_draft = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if attrs.get("save_as_draft") and not attrs.get("batch_session_id"):
            raise serializers.ValidationError({"batch_session_id": "请重新打开新增采购批次页面。"})
        return attrs

    def validate_lines(self, lines):
        lines = super().validate_lines(lines)
        if len({line["supplier_id"] for line in lines}) != 1:
            raise serializers.ValidationError("每次只提交同一家供应商的采购明细。")
        return lines


class PurchaseBatchPageConfirmSerializer(serializers.Serializer):
    batch_session_id = serializers.UUIDField()
    additional = PurchaseBatchReadySerializer(required=False)


class PurchaseGroupProgressLineSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    line_number = serializers.IntegerField()
    source_bom_line_id_snapshot = serializers.UUIDField(allow_null=True)
    product_line_id_snapshot = serializers.UUIDField(allow_null=True)
    required_quantity = serializers.DecimalField(max_digits=22, decimal_places=4, allow_null=True)
    source_unit_text = serializers.CharField()
    source_snapshot = serializers.JSONField()
    purchased_quantity = serializers.DecimalField(max_digits=30, decimal_places=4, allow_null=True)
    planned_purchase_quantity = serializers.DecimalField(max_digits=30, decimal_places=4, allow_null=True, read_only=True)
    remaining_purchase_quantity = serializers.DecimalField(max_digits=30, decimal_places=4, allow_null=True, read_only=True)
    accepted_quantity = serializers.DecimalField(max_digits=30, decimal_places=4, allow_null=True)
    purchased_bar_count = serializers.DecimalField(max_digits=30, decimal_places=0, allow_null=True, read_only=True)
    accepted_bar_count = serializers.DecimalField(max_digits=30, decimal_places=0, allow_null=True, read_only=True)
    receipt_quantity_mode = serializers.CharField(allow_null=True, read_only=True)
    in_progress_quantity = serializers.DecimalField(max_digits=30, decimal_places=4, allow_null=True, read_only=True)
    in_progress_bar_count = serializers.DecimalField(max_digits=30, decimal_places=0, allow_null=True, read_only=True)
    progress_percent = serializers.DecimalField(max_digits=38, decimal_places=4, allow_null=True)
    is_satisfied = serializers.BooleanField()
    compatibility_issues = serializers.ListField(child=serializers.CharField())

    def to_representation(self, instance):
        result = super().to_representation(instance)
        snapshot = result["source_snapshot"]
        if snapshot.get("source_contributions"):
            result["source_snapshot"] = {
                **{key: value for key, value in snapshot.items() if key != "external_source_snapshots"},
                "source_contributions": [
                    {key: value for key, value in row.items() if key != "source_snapshot"}
                    for row in snapshot["source_contributions"]
                ],
            }
        return result


class PurchaseGroupProgressSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["PENDING", "PURCHASING", "COMPLETED", "UNKNOWN"])
    satisfied_line_count = serializers.IntegerField()
    line_count = serializers.IntegerField()
    lines = PurchaseGroupProgressLineSerializer(many=True)
    external_supply_line_ids = serializers.ListField(child=serializers.UUIDField(), read_only=True)


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


class PurchaseGroupBatchPageQuerySerializer(serializers.Serializer):
    batch_session_id = serializers.UUIDField(required=False)


class PurchaseBatchPageDraftSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order_number = serializers.CharField()
    suppliers = serializers.ListField(child=serializers.CharField())
    line_count = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=22, decimal_places=4, allow_null=True)


class PurchaseGroupBatchPageSerializer(serializers.Serializer):
    current_batch_number = serializers.IntegerField(allow_null=True)
    next_batch_number = serializers.IntegerField()
    submitted_line_ids = serializers.ListField(child=serializers.UUIDField())
    draft_orders = PurchaseBatchPageDraftSerializer(many=True, required=False)


class PurchaseGroupSerializer(serializers.ModelSerializer):
    product = serializers.SerializerMethodField()
    products = serializers.SerializerMethodField()
    combined_into_group_id = serializers.SerializerMethodField()
    order_delivery_date = serializers.DateField(source="production_task.delivery_date", read_only=True, allow_null=True)
    progress = serializers.SerializerMethodField()
    batches = PurchaseBatchSummarySerializer(many=True, read_only=True)
    batch_page = serializers.SerializerMethodField()
    display_status = serializers.SerializerMethodField()
    completion = serializers.SerializerMethodField()
    deletion = serializers.SerializerMethodField()
    manual_completed_by_name = serializers.CharField(
        source="manual_completed_by_employee.display_name", read_only=True, default="",
    )

    class Meta:
        model = PurchaseGroup
        fields = ["id", "group_number", "production_task_id", "product_line_id_snapshot", "source_bom_id_snapshot",
                  "production_task_number_snapshot", "sales_order_number_snapshot", "customer_name_snapshot",
                  "source_revision", "compatibility_issues", "product", "products", "combined_into_group_id", "order_delivery_date",
                  "progress", "batches", "batch_page", "display_status", "completion", "deletion", "manual_completed_at",
                  "manual_completed_by_name", "manual_completion_remark", "created_at", "updated_at"]
        read_only_fields = fields

    @extend_schema_field(PurchaseGroupProgressSerializer)
    def get_progress(self, instance):
        return PurchaseGroupProgressSerializer(self._progress(instance)).data

    @extend_schema_field(PurchaseGroupBatchPageSerializer(allow_null=True))
    def get_batch_page(self, instance):
        session_id = self.context.get("batch_session_id")
        if not session_id:
            return None
        current_batch, next_batch = purchase_group_batch_numbers(instance.pk, session_id)
        orders = [order for order in instance.batches.all() if order.batch_session_id == session_id]
        saved_lines = {line.purchase_group_line_id for order in orders
                       for line in order.lines.all() if line.purchase_group_line_id}
        drafts = [{
            "id": order.pk, "order_number": order.order_number,
            "suppliers": sorted({line.supplier_name_snapshot for line in order.lines.all() if line.supplier_name_snapshot}),
            "line_count": len(order.lines.all()), "total_amount": order.total_amount,
        } for order in orders if order.status == PurchaseOrderStatus.DRAFT]
        page = {
            "current_batch_number": current_batch,
            "next_batch_number": next_batch,
            "submitted_line_ids": sorted(saved_lines),
        }
        if drafts:
            page["draft_orders"] = drafts
        return PurchaseGroupBatchPageSerializer(page).data

    def _progress(self, instance):
        # 列表逐单序列化，仅复用当前单据的计算结果。
        if getattr(self, "_progress_group", None) is not instance:
            self._current_progress = purchase_group_progress(instance)
            self._progress_group = instance
        return self._current_progress

    @extend_schema_field(serializers.ChoiceField(choices=["PENDING", "PURCHASING", "COMPLETED", "UNKNOWN"]))
    def get_display_status(self, instance):
        return "COMPLETED" if instance.manual_completed_at else self._progress(instance)["status"]

    @extend_schema_field(PurchaseGroupCompletionSerializer)
    def get_completion(self, instance):
        return purchase_group_completion_summary(instance, progress=self._progress(instance))

    @extend_schema_field(PurchaseGroupDeletionSerializer)
    def get_deletion(self, instance):
        return purchase_group_deletion_summary(instance)

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_combined_into_group_id(self, instance):
        return next((link.purchase_group_id for link in instance.combined_into_sources.all()), None)

    @extend_schema_field(PurchaseGroupProductSerializer(allow_null=True))
    def get_product(self, instance):
        return self._product(instance, instance.product_line_id_snapshot)

    @extend_schema_field(PurchaseGroupProductSerializer(many=True))
    def get_products(self, instance):
        if instance.product_line_id_snapshot is not None:
            product = self.get_product(instance)
            return [product] if product else []
        selected = {source.product_line_id_snapshot for source in instance.bom_sources.all()}
        return [self._product(instance, product.pk) for product in instance.production_task.purchase_group_products
                if product.pk in selected]

    def _product(self, instance, product_id):
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
