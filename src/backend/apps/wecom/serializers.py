from urllib.parse import urlsplit

from rest_framework import serializers


class ConfigWriteSerializer(serializers.Serializer):
    corp_id = serializers.RegexField(r"^[A-Za-z0-9_-]+$", max_length=100, required=False)
    agent_id = serializers.RegexField(r"^[1-9][0-9]{0,29}$", max_length=30, required=False)
    erp_origin = serializers.URLField(max_length=255, required=False)
    enabled = serializers.BooleanField(required=False)
    secret = serializers.CharField(max_length=512, required=False, allow_blank=True, write_only=True, trim_whitespace=True)
    callback_token = serializers.RegexField(r"^[A-Za-z0-9]{1,32}$", required=False, allow_blank=True, write_only=True)
    callback_aes_key = serializers.RegexField(r"^[A-Za-z0-9]{43}$", required=False, allow_blank=True, write_only=True)

    def validate_erp_origin(self, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise serializers.ValidationError("请填写不含路径、账号、查询参数的 HTTPS ERP 站点地址。")
        try:
            port = parsed.port
        except ValueError as exc:
            raise serializers.ValidationError("ERP 站点端口无效。") from exc
        if port not in (None, 443):
            raise serializers.ValidationError("ERP 站点必须使用 HTTPS 默认端口。")
        return f"https://{parsed.hostname.lower()}"


class ConfigSerializer(serializers.Serializer):
    corp_id = serializers.CharField()
    agent_id = serializers.CharField()
    erp_origin = serializers.CharField()
    enabled = serializers.BooleanField()
    has_secret = serializers.BooleanField()
    has_callback_token = serializers.BooleanField()
    has_callback_aes_key = serializers.BooleanField()
    encryption_ready = serializers.BooleanField()
    configuration_complete = serializers.BooleanField()
    last_check_status = serializers.ChoiceField(choices=["NOT_CHECKED", "SUCCESS", "FAILED"])
    last_check_message = serializers.CharField()
    last_checked_at = serializers.DateTimeField(allow_null=True)
    login_url = serializers.CharField()
    callback_url = serializers.CharField()
    trusted_domain = serializers.CharField()


class ConfigResponseSerializer(serializers.Serializer):
    data = ConfigSerializer()


class BindingWriteSerializer(serializers.Serializer):
    user_id = serializers.RegexField(r"^[A-Za-z0-9_.@-]{1,64}$", max_length=64)
    employee_id = serializers.UUIDField()
    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value):
        if not value:
            raise serializers.ValidationError("必须确认成员与所选员工为同一人。")
        return value


class BindingSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    user_id = serializers.CharField()
    member_name = serializers.CharField()
    employee_id = serializers.UUIDField()
    employee_code = serializers.CharField()
    employee_name = serializers.CharField()
    username = serializers.CharField()
    role_status = serializers.ChoiceField(choices=["waiting", "active", "inactive"])
    source = serializers.ChoiceField(choices=["AUTO", "MANUAL"])
    created_at = serializers.DateTimeField()


class BindingResponseSerializer(serializers.Serializer):
    data = BindingSerializer()


class PageQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class BindingQuerySerializer(PageQuerySerializer):
    search = serializers.CharField(max_length=150, allow_blank=True, default="")
    status = serializers.ChoiceField(choices=["", "waiting", "active", "inactive"], default="")


class BindingListSerializer(serializers.Serializer):
    data = BindingSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class EmployeeQuerySerializer(serializers.Serializer):
    search = serializers.CharField(max_length=150, allow_blank=True, default="")


class EmployeeOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    employee_code = serializers.CharField()
    display_name = serializers.CharField()
    username = serializers.CharField()
    etag = serializers.CharField()


class EmployeeListSerializer(serializers.Serializer):
    data = EmployeeOptionSerializer(many=True)


class AuditSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    occurred_at = serializers.DateTimeField()
    actor_name = serializers.CharField()
    action = serializers.CharField()
    user_id = serializers.CharField()
    employee_name = serializers.CharField()
    result = serializers.CharField()
    message = serializers.CharField()


class AuditListSerializer(serializers.Serializer):
    data = AuditSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
