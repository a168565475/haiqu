import re

from rest_framework import serializers

from .serializers import PageQuerySerializer


TEMPLATE_VARIABLE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
ALLOWED_VARIABLES = {"接收人", "消息内容", "发送时间", "系统地址"}


def validate_plain_text(value):
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise serializers.ValidationError("正文含无效字符。") from None
    if not value.strip() or any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise serializers.ValidationError("请填写有效文本，不能包含控制字符。")
    return value


class MessageTemplateWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50)
    body = serializers.CharField(max_length=8192, trim_whitespace=False)

    def validate_body(self, value):
        validate_plain_text(value)
        if any(match.group(1) not in ALLOWED_VARIABLES for match in TEMPLATE_VARIABLE.finditer(value)):
            raise serializers.ValidationError("仅支持接收人、消息内容、发送时间和系统地址四个模板变量。")
        remainder = TEMPLATE_VARIABLE.sub("", value)
        if "{{" in remainder or "}}" in remainder:
            raise serializers.ValidationError("模板变量格式无效，请使用 {{变量名}}。")
        return value

    def validate(self, attrs):
        if set(self.initial_data) - {"name", "body"}:
            raise serializers.ValidationError("模板只接收名称和正文。")
        return attrs


class MessageTemplateSerializer(serializers.Serializer):
    name = serializers.CharField()
    body = serializers.CharField()
    is_saved = serializers.BooleanField()
    updated_at = serializers.DateTimeField(allow_null=True)


class MessageTemplateResponseSerializer(serializers.Serializer):
    data = MessageTemplateSerializer()


class MessageTestSerializer(serializers.Serializer):
    binding_id = serializers.UUIDField()
    message_content = serializers.CharField(max_length=2048, trim_whitespace=False)
    idempotency_key = serializers.UUIDField()

    def validate_message_content(self, value):
        return validate_plain_text(value)

    def validate(self, attrs):
        if set(self.initial_data) - {"binding_id", "message_content", "idempotency_key"}:
            raise serializers.ValidationError("测试发送只接收已绑定员工、测试内容和本次请求标识。")
        return attrs


class MessageAttemptSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    idempotency_key = serializers.UUIDField()
    template_name = serializers.CharField()
    recipient_name = serializers.CharField()
    user_id = serializers.CharField()
    status = serializers.ChoiceField(choices=["PROCESSING", "ACCEPTED", "FAILED", "UNCERTAIN"])
    message = serializers.CharField()
    created_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)


class MessageAttemptResponseSerializer(serializers.Serializer):
    data = MessageAttemptSerializer()


class MessageAttemptQuerySerializer(PageQuerySerializer):
    idempotency_key = serializers.UUIDField(required=False)


class MessageAttemptListSerializer(serializers.Serializer):
    data = MessageAttemptSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
