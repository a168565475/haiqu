from decimal import Decimal

from rest_framework import serializers

from apps.core.api.concurrency import etag_for_instance
from ..cost_models import ProductionTaskExpense


class ProductionTaskExpenseWriteSerializer(serializers.Serializer):
    expense_type = serializers.ChoiceField(choices=ProductionTaskExpense.ExpenseType.choices)
    description = serializers.CharField(max_length=100, allow_blank=False)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal('0.01'))
    occurred_on = serializers.DateField()
    remark = serializers.CharField(max_length=500, allow_blank=True, default='')
    client_request_id = serializers.UUIDField()


class ProductionTaskExpensePatchSerializer(ProductionTaskExpenseWriteSerializer):
    client_request_id = None

    def validate(self, attrs):
        if 'client_request_id' in self.initial_data:
            raise serializers.ValidationError({'client_request_id': '创建请求编号不可修改。'})
        if not attrs:
            raise serializers.ValidationError('请提供要修改的费用字段。')
        return attrs


class ProductionTaskExpenseReadSerializer(serializers.ModelSerializer):
    etag = serializers.SerializerMethodField()

    class Meta:
        model = ProductionTaskExpense
        fields = ['id', 'expense_type', 'description', 'amount', 'occurred_on', 'remark', 'etag']

    def get_etag(self, instance) -> str:
        return etag_for_instance(instance)


class ProductionTaskExpenseResponseSerializer(serializers.Serializer):
    data = ProductionTaskExpenseReadSerializer()


class ProductionTaskExpenseListResponseSerializer(serializers.Serializer):
    data = ProductionTaskExpenseReadSerializer(many=True)
