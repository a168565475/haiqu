from rest_framework import serializers

from apps.core.api.concurrency import etag_for_instance
from apps.reference_data.models import Currency
from .models import FinanceAccount
from .selectors import account_is_referenced


class TextField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class AccountWriteSerializer(serializers.Serializer):
    account_type = TextField(max_length=80)
    code = TextField(max_length=50, required=False, allow_blank=True)
    category = TextField(max_length=80)
    name = TextField(max_length=200)
    account_number = TextField(max_length=100, trim_whitespace=False)
    currency_id = serializers.PrimaryKeyRelatedField(source="currency", queryset=Currency.objects.filter(status="ACTIVE", archived_at__isnull=True))
    status = serializers.ChoiceField(choices=FinanceAccount.Status.choices)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("请求必须是 JSON 对象。")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({field: "不支持此字段。" for field in sorted(unknown)})
        if self.partial and "code" in data:
            raise serializers.ValidationError({"code": "已有账户编码不能修改。"})
        return super().to_internal_value(data)

    def validate_account_number(self, value):
        if not value.strip():
            raise serializers.ValidationError("账户账号不能为空。")
        return value


class AccountQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=FinanceAccount.Status.choices, required=False)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False)
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False)


class AccountSerializer(serializers.ModelSerializer):
    currency_id = serializers.UUIDField(read_only=True)
    currency_code = serializers.CharField(source="currency.code", read_only=True)
    currency_name = serializers.CharField(source="currency.chinese_name", read_only=True)
    etag = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    delete_block_reason = serializers.SerializerMethodField()

    class Meta:
        model = FinanceAccount
        fields = ("id", "account_type", "code", "category", "name", "account_number", "currency_id", "currency_code",
                  "currency_name", "status", "created_at", "updated_at", "etag", "can_delete", "delete_block_reason")

    def get_etag(self, obj) -> str:
        return etag_for_instance(obj)

    def get_can_delete(self, obj) -> bool:
        if not hasattr(obj, "_finance_referenced"):
            obj._finance_referenced = account_is_referenced(obj)
        return not obj._finance_referenced

    def get_delete_block_reason(self, obj) -> str | None:
        return None if self.get_can_delete(obj) else "账户已被引用，请停用以保留历史记录。"


class AccountResponseSerializer(serializers.Serializer):
    data = AccountSerializer()
