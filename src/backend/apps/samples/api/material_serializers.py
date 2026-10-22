from rest_framework import serializers


class MaterialResponseSerializer(serializers.Serializer):
    data = serializers.JSONField()


class ProductionReportItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    metalwork_reported_quantity = serializers.IntegerField(min_value=0, required=False)
    cutting_reported_quantity = serializers.IntegerField(min_value=0, required=False)
    metalwork_completed = serializers.BooleanField(required=False)
    cutting_completed = serializers.BooleanField(required=False)

    def validate(self, attrs):
        from apps.access_control.resource_scopes import enabled
        if not enabled() and len(attrs) != 5:
            raise serializers.ValidationError('请提供金工和裁剪的数量及完成状态。')
        if len(attrs) == 1:
            raise serializers.ValidationError('至少提供一项报工内容。')
        for quantity_field, completed_field in (
            ('metalwork_reported_quantity', 'metalwork_completed'),
            ('cutting_reported_quantity', 'cutting_completed'),
        ):
            if attrs.get(completed_field) is True and quantity_field in attrs and attrs[quantity_field] <= 0:
                raise serializers.ValidationError({quantity_field: '完成时，报工数量必须大于 0。'})
        return attrs


class ProductionReportSerializer(serializers.Serializer):
    items = ProductionReportItemSerializer(many=True, allow_empty=False, max_length=500)


class MaterialCandidateQuerySerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=['tube', 'hardware', 'plastic', 'accessory', 'fabric', 'packaging'])
    q = serializers.CharField(max_length=100, allow_blank=True, default='')
    name = serializers.CharField(max_length=200, allow_blank=True, default='')


class MaterialLineSerializer(serializers.Serializer):
    key = serializers.UUIDField()
    category = serializers.ChoiceField(choices=['tube', 'hardware', 'plastic', 'accessory', 'fabric', 'packaging'])
    name = serializers.CharField(max_length=300, allow_blank=True)
    specification = serializers.CharField(max_length=500, allow_blank=True)
    material = serializers.CharField(max_length=500, allow_blank=True)
    color = serializers.CharField(max_length=500, allow_blank=True)
    quantity = serializers.CharField(max_length=30, allow_blank=True)
    unitId = serializers.CharField(max_length=36, allow_blank=True)
    notes = serializers.CharField(max_length=2000, allow_blank=True)
    rawMaterialId = serializers.UUIDField(required=False, allow_null=True)
    cuttingLengthMm = serializers.CharField(max_length=14, allow_blank=True, required=False, default='')
    piecesPerBar = serializers.CharField(max_length=14, allow_blank=True, required=False, default='')
    pipeInputMode = serializers.ChoiceField(choices=['TOTAL_METERS', 'LEGACY_PIECES'], required=False, allow_null=True)


class MaterialDraftSerializer(serializers.Serializer):
    lines = MaterialLineSerializer(many=True, max_length=500)
    notes = serializers.CharField(max_length=2000, allow_blank=True)


class MaterialSaveSerializer(serializers.Serializer):
    draft = MaterialDraftSerializer()
    submit = serializers.BooleanField()


class WarehouseAllocationSerializer(serializers.Serializer):
    balanceId = serializers.UUIDField()
    stockMode = serializers.ChoiceField(choices=['LEGACY', 'PUBLIC_V2'])
    quantity = serializers.CharField(max_length=30)


class WarehouseLineSerializer(serializers.Serializer):
    key = serializers.UUIDField()
    supplyQuantity = serializers.CharField(max_length=30, allow_blank=True)
    inventoryAllocations = WarehouseAllocationSerializer(many=True, max_length=200, required=False)


class WarehouseDraftSerializer(serializers.Serializer):
    lines = WarehouseLineSerializer(many=True, max_length=500)
    notes = serializers.CharField(max_length=2000, allow_blank=True)


class WarehouseSaveSerializer(serializers.Serializer):
    draft = WarehouseDraftSerializer()
    submit = serializers.BooleanField()
