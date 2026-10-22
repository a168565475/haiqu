"""新版申请的产品完善输入；不要求旧表单的任务单或打样信息明细。"""
from rest_framework import serializers

from .form_serializers import SampleFormDetailSerializer, SampleFormProductSerializer
from .application_serializers import SampleApplicationSerializer


class SampleApplicationBasicSerializer(serializers.Serializer):
    """复用申请字段定义；编辑不要求重新选择或重建来源产品。"""

    def get_fields(self):
        fields = SampleApplicationSerializer().get_fields()
        names = {'customer_account_id', 'customer_contact_id', 'owner_employee_id',
                 'source_type', 'source_id', 'sample_type', 'shipping_method',
                 'delivery_batch', 'is_repeat_order', 'order_date', 'sample_due_date'}
        fields = {name: field for name, field in fields.items() if name in names}
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return fields
        from apps.customers.models import CustomerContact
        from apps.customers.selectors import accessible_customers
        customers = accessible_customers(request, 'samples.complete_sample_requirements').filter(archived_at__isnull=True)
        fields['customer_account_id'].queryset = customers
        fields['customer_contact_id'].queryset = CustomerContact.objects.filter(customer_account__in=customers, archived_at__isnull=True)
        return fields

    def validate(self, attrs):
        contact = attrs['customer_contact']
        if contact and contact.customer_account_id != attrs['customer_account'].pk:
            raise serializers.ValidationError({'customer_contact_id': '联系人必须属于当前客户。'})
        if bool(attrs['source_type']) != bool(attrs['source_id']):
            raise serializers.ValidationError({'source_id': '来源类型和来源记录必须同时填写或清空。'})
        if attrs['order_date'] and attrs['sample_due_date'] and attrs['sample_due_date'] < attrs['order_date']:
            raise serializers.ValidationError({'sample_due_date': '期望完成日期不能早于下单日期。'})
        return attrs


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
    basic = SampleApplicationBasicSerializer(required=False)

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


class SampleApplicationSourceQuerySerializer(serializers.Serializer):
    sourceType = serializers.ChoiceField(choices=['inquiry', 'quotation'])
    sourceId = serializers.UUIDField()


class SampleApplicationProductsRequestSerializer(serializers.Serializer):
    payload = SampleApplicationProductsSerializer()
    reference_image = serializers.FileField(required=False)


class SampleApplicationProductCandidateSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    product_name = serializers.CharField()
    specification = serializers.CharField()
    category_id = serializers.UUIDField()


class SampleApplicationProductOptionsSerializer(serializers.Serializer):
    data = SampleApplicationProductCandidateSerializer(many=True)
