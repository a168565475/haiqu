from rest_framework import serializers

from .message_serializers import validate_plain_text
from .models import NotificationDelivery


class NotificationRuleWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    title_template = serializers.CharField(max_length=200, trim_whitespace=False)
    body_template = serializers.CharField(max_length=8192, trim_whitespace=False)
    recipient_role_codes = serializers.ListField(child=serializers.CharField(max_length=50), allow_empty=True)
    recipient_scope = serializers.CharField(max_length=20)
    enabled = serializers.BooleanField()

    def validate_name(self, value):
        return validate_plain_text(value)

    def validate_title_template(self, value):
        return validate_plain_text(value)

    def validate_body_template(self, value):
        return validate_plain_text(value)

    def validate_recipient_role_codes(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("接收角色不可重复。")
        return value

    def validate(self, attrs):
        if set(self.initial_data) - {"name", "title_template", "body_template", "recipient_role_codes", "recipient_scope", "enabled"}:
            raise serializers.ValidationError("通知规则只接收名称、标题、正文、角色、范围和启用状态。")
        return attrs


class NotificationRoleSerializer(serializers.Serializer):
    role_code = serializers.CharField()
    display_name = serializers.CharField()
    archived = serializers.BooleanField()


class NotificationRuleSerializer(serializers.Serializer):
    event_code = serializers.CharField()
    display_name = serializers.CharField()
    name = serializers.CharField()
    title_template = serializers.CharField()
    body_template = serializers.CharField()
    allowed_variables = serializers.ListField(child=serializers.CharField())
    required_variables = serializers.ListField(child=serializers.CharField())
    supported_scopes = serializers.ListField(child=serializers.CharField())
    scope_labels = serializers.DictField()
    recipient_role_codes = serializers.ListField(child=serializers.CharField())
    recipient_roles = NotificationRoleSerializer(many=True)
    recipient_scope = serializers.CharField()
    enabled = serializers.BooleanField()
    version = serializers.IntegerField()
    updated_at = serializers.DateTimeField(allow_null=True)
    updated_by = serializers.CharField(allow_blank=True)
    etag = serializers.CharField()
    target_key = serializers.CharField()
    warnings = serializers.ListField(child=serializers.CharField())


class NotificationRuleListSerializer(serializers.Serializer):
    data = NotificationRuleSerializer(many=True)
    roles = NotificationRoleSerializer(many=True)


class NotificationRuleResponseSerializer(serializers.Serializer):
    data = NotificationRuleSerializer()


class NotificationPreviewSerializer(serializers.Serializer):
    variables = serializers.DictField(child=serializers.CharField(allow_blank=True))
    name = serializers.CharField(max_length=100, required=False)
    title_template = serializers.CharField(max_length=200, trim_whitespace=False, required=False)
    body_template = serializers.CharField(max_length=8192, trim_whitespace=False, required=False)
    recipient_role_codes = serializers.ListField(child=serializers.CharField(max_length=50), required=False)
    recipient_scope = serializers.CharField(max_length=20, required=False)
    enabled = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if set(self.initial_data) - {
            "variables", "name", "title_template", "body_template", "recipient_role_codes", "recipient_scope", "enabled",
        }:
            raise serializers.ValidationError("预览只接收规则字段和示例变量。")
        return attrs


class NotificationPreviewResponseSerializer(serializers.Serializer):
    data = serializers.DictField()


class NotificationItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    event_code = serializers.CharField()
    event_name = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    created_at = serializers.DateTimeField()
    read_at = serializers.DateTimeField(allow_null=True)
    target = serializers.DictField(allow_null=True)
    target_accessible = serializers.BooleanField()
    channel_status = serializers.DictField()


class NotificationListSerializer(serializers.Serializer):
    data = NotificationItemSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class NotificationUnreadSerializer(serializers.Serializer):
    unread_count = serializers.IntegerField()


class NotificationReadSerializer(serializers.Serializer):
    data = NotificationItemSerializer()


class NotificationQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=50, default=20)


class NotificationDeliveryQuerySerializer(NotificationQuerySerializer):
    status = serializers.ChoiceField(choices=NotificationDelivery.Status.choices, required=False)


class NotificationDeliverySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    event_code = serializers.CharField()
    channel = serializers.CharField()
    status = serializers.CharField()
    error_code = serializers.CharField(allow_blank=True)
    attempt_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    last_attempt_at = serializers.DateTimeField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)


class NotificationDeliveryListSerializer(serializers.Serializer):
    data = NotificationDeliverySerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
