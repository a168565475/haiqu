from rest_framework import serializers

from .group_serializers import PurchaseBatchCreateSerializer, PurchaseGroupBomInputSerializer


class PackagingSourceSerializer(PurchaseGroupBomInputSerializer):
    production_task_id = serializers.UUIDField()
    task_number = serializers.CharField(read_only=True)
    bom_number = serializers.CharField(read_only=True)
    product_name = serializers.CharField(read_only=True)


class PackagingPrepareSerializer(serializers.Serializer):
    sources = PackagingSourceSerializer(many=True, allow_empty=False, max_length=100)

    def validate_sources(self, sources):
        if len({row["bom_id"] for row in sources}) != len(sources):
            raise serializers.ValidationError("同一份 BOM 不能重复选择。")
        return sources


class PackagingBatchSerializer(PurchaseBatchCreateSerializer):
    def validate_lines(self, lines):
        priced = []
        errors = {}
        for index, line in enumerate(lines, 1):
            if not line.get("set_pricing") and not (line["actual_purchase_quantity"] and line["unit_price"]):
                continue
            priced.append(line)
            if not line["supplier_id"] or not line["delivery_date"]:
                errors[str(index)] = f"第 {index} 行请选择供应商并填写采购交期。"
        if errors:
            raise serializers.ValidationError(errors)
        if not priced:
            raise serializers.ValidationError("请至少填写一行采购数量和单价均大于 0 的包材。")
        return super().validate_lines(priced)


class PackagingPageQuerySerializer(serializers.Serializer):
    group_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=100)
    batch_session_id = serializers.UUIDField()

    def validate_group_ids(self, ids):
        if ids is not None and len(set(ids)) != len(ids):
            raise serializers.ValidationError("采购需求不能重复。")
        return ids


class PackagingPageSaveSerializer(PackagingPageQuerySerializer):
    batch = PackagingBatchSerializer()

    def validate_batch(self, batch):
        if len({line["supplier_id"] for line in batch["lines"]}) != 1:
            raise serializers.ValidationError("每次只保存一家供应商的采购明细。")
        return batch


class PackagingPageConfirmSerializer(PackagingPageQuerySerializer):
    batch = PackagingBatchSerializer(required=False)


class PackagingPageReadSerializer(PackagingPageQuerySerializer):
    group_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=100, required=False, default=None)
