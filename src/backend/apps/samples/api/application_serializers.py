from decimal import Decimal

from rest_framework import serializers
from apps.organizations.selectors import active_department_employees
from apps.customers.models import CustomerAccount, CustomerContact
from apps.customers.selectors import accessible_customers
from apps.organizations.models import Employee
from apps.products.models import ProductInformation, ProductStatus
from ..models import SampleDeliveryBatch, SampleShippingMethod, SampleType


class SampleApplicationSerializer(serializers.Serializer):
    customer_account_id = serializers.PrimaryKeyRelatedField(source="customer_account", queryset=CustomerAccount.objects.none())
    customer_contact_id = serializers.PrimaryKeyRelatedField(source="customer_contact", queryset=CustomerContact.objects.none(), allow_null=True)
    owner_employee_id = serializers.PrimaryKeyRelatedField(source="owner_employee", queryset=active_department_employees("DEPT_BUSINESS"))
    source_type = serializers.ChoiceField(choices=["inquiry", "quotation"], allow_null=True)
    source_id = serializers.UUIDField(allow_null=True)
    source_product_id = serializers.UUIDField(allow_null=True)
    product_id = serializers.PrimaryKeyRelatedField(
        source="product",
        queryset=ProductInformation.objects.filter(status=ProductStatus.ACTIVE, archived_at__isnull=True),
        required=False,
        allow_null=True,
    )
    sample_type = serializers.ChoiceField(choices=SampleType.choices)
    shipping_method = serializers.ChoiceField(choices=SampleShippingMethod.choices)
    delivery_batch = serializers.ChoiceField(choices=SampleDeliveryBatch.choices)
    is_repeat_order = serializers.BooleanField()
    order_date = serializers.DateField(allow_null=True)
    sample_due_date = serializers.DateField(allow_null=True)
    product_name = serializers.CharField(max_length=500)
    specification = serializers.CharField(max_length=2000, allow_blank=True)
    purpose = serializers.CharField(max_length=2000, allow_blank=True)
    quantity = serializers.IntegerField(min_value=1, max_value=2147483647)
    length_cm = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), allow_null=True)
    armrest_width_cm = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), allow_null=True)
    seat_width_cm = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), allow_null=True)
    back_height_cm = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), allow_null=True)
    seat_height_cm = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), allow_null=True)
    idempotency_key = serializers.UUIDField()
    remove_reference_image = serializers.BooleanField(default=False)
    source_reference_image_id = serializers.UUIDField(required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return
        customers = accessible_customers(request, 'add_samplerequest').filter(archived_at__isnull=True)
        self.fields['customer_account_id'].queryset = customers
        self.fields['customer_contact_id'].queryset = CustomerContact.objects.filter(customer_account__in=customers, archived_at__isnull=True)

    def validate(self, attrs):
        contact = attrs.get('customer_contact')
        if contact and contact.customer_account_id != attrs['customer_account'].pk:
            raise serializers.ValidationError({'customer_contact_id': '联系人必须属于当前客户。'})
        if bool(attrs['source_type']) != bool(attrs['source_id']) or bool(attrs['source_id']) != bool(attrs['source_product_id']):
            raise serializers.ValidationError({'source_id': '来源类型、来源记录和来源产品必须同时填写。'})
        if attrs['order_date'] and attrs['sample_due_date'] and attrs['sample_due_date'] < attrs['order_date']:
            raise serializers.ValidationError({'sample_due_date': '期望完成日期不能早于下单日期。'})
        return attrs


class SampleApplicationReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=['approve', 'return'])
    note = serializers.CharField(max_length=500, allow_blank=True)

    def validate(self, attrs):
        if attrs['decision'] == 'return' and not attrs['note'].strip():
            raise serializers.ValidationError({'note': '退回时请填写需要业务员补充的内容。'})
        return attrs


class SampleApplicationRequestSerializer(serializers.Serializer):
    payload = SampleApplicationSerializer()
    reference_image = serializers.FileField(required=False)
