"""新版申请的产品完善输入；不要求旧表单的任务单或打样信息明细。"""
from rest_framework import serializers

from .form_serializers import SampleFormDetailSerializer, SampleFormProductSerializer


class ApplicationProductDetailSerializer(SampleFormDetailSerializer):
    id = serializers.UUIDField()
    sample_quantity = serializers.IntegerField(min_value=1, max_value=2147483647)

    def get_fields(self):
        fields = super().get_fields()
        for name in ('cutting_reported_quantity', 'metalwork_reported_quantity', 'cutting_completed', 'metalwork_completed'):
            fields.pop(name)
        return fields

    def validate(self, attrs):
        # 此入口不接收报工字段；数量与已有报工的关系在锁定申请后核对。
        return attrs


class ApplicationProductSerializer(SampleFormProductSerializer):
    id = serializers.UUIDField()
    details = ApplicationProductDetailSerializer(many=True, min_length=1, max_length=200)

    def get_fields(self):
        fields = super().get_fields()
        for name in ('client_key', 'source_inquiry_item_id', 'source_quotation_line_id', 'sampling_details'):
            fields.pop(name)
        return fields


class SampleApplicationProductsSerializer(serializers.Serializer):
    products = ApplicationProductSerializer(many=True, min_length=1, max_length=50)
    purpose = serializers.CharField(max_length=2000, allow_blank=True)

    def validate_products(self, products):
        ids = [product['id'] for product in products]
        detail_ids = [detail['id'] for product in products for detail in product['details']]
        if len(ids) != len(set(ids)) or len(detail_ids) != len(set(detail_ids)):
            raise serializers.ValidationError('产品或颜色明细不能重复。')
        if len(detail_ids) > 200:
            raise serializers.ValidationError('单张样品申请最多包含 200 条颜色明细。')
        return products


class SampleApplicationProductQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')


class SampleApplicationProductCandidateSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    product_name = serializers.CharField()
    specification = serializers.CharField()
    category_id = serializers.UUIDField()


class SampleApplicationProductOptionsSerializer(serializers.Serializer):
    data = SampleApplicationProductCandidateSerializer(many=True)
