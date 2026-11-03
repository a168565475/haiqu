from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(
        max_length=150,
        trim_whitespace=True,
        error_messages={
            "blank": "请输入用户名",
            "max_length": "用户名不能超过 150 个字符",
            "required": "请输入用户名",
        },
    )
    password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
        error_messages={
            "blank": "请输入密码",
            "max_length": "密码不能超过 128 个字符",
            "required": "请输入密码",
        },
    )


class EmployeeSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    employee_code = serializers.CharField()
    display_name = serializers.CharField()
    status = serializers.CharField()


class AuthUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    display_name = serializers.CharField()
    is_superuser = serializers.BooleanField()
    employee = EmployeeSummarySerializer(allow_null=True)
    permissions = serializers.ListField(child=serializers.CharField())
    data_scope = serializers.CharField()
    effective_access = serializers.DictField(required=False)
    sales_access_enabled = serializers.BooleanField(required=False)
    module_access_enabled = serializers.BooleanField(required=False)
    waiting_for_role = serializers.BooleanField()


class AccountSwitchStateSerializer(serializers.Serializer):
    active = serializers.BooleanField()
    can_return = serializers.BooleanField()
    identity_version = serializers.CharField()


class AuthenticationStateSerializer(serializers.Serializer):
    authenticated = serializers.BooleanField()
    user = AuthUserSerializer(allow_null=True)
    account_switch = AccountSwitchStateSerializer(required=False)


class SwitchAccountSerializer(serializers.Serializer):
    employee_id = serializers.UUIDField()

    def to_internal_value(self, data):
        if (not isinstance(data, dict) or set(data) - {"employee_id"}
                or ("employee_id" in data and not isinstance(data["employee_id"], str))):
            raise serializers.ValidationError({"non_field_errors": ["只接受字符串员工标识 employee_id。"]})
        return super().to_internal_value(data)


class ReturnAdminSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or data:
            raise serializers.ValidationError({"non_field_errors": ["返回管理员不接受账号标识或其他字段。"]})
        return {}


class SwitchTargetQuerySerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, max_length=100)
    department_id = serializers.UUIDField(required=False)
    role_id = serializers.UUIDField(required=False)


class SwitchTargetChoiceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class SwitchTargetSerializer(serializers.Serializer):
    employee_id = serializers.UUIDField()
    user_id = serializers.IntegerField()
    username = serializers.CharField()
    employee_code = serializers.CharField()
    display_name = serializers.CharField()
    departments = SwitchTargetChoiceSerializer(many=True)
    roles = SwitchTargetChoiceSerializer(many=True)


class SwitchTargetsResponseSerializer(serializers.Serializer):
    results = SwitchTargetSerializer(many=True)
    identity_version = serializers.CharField()
    departments = SwitchTargetChoiceSerializer(many=True)
    roles = SwitchTargetChoiceSerializer(many=True)
    has_more = serializers.BooleanField()


class HealthResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    service = serializers.CharField()
    database = serializers.CharField()
    redis = serializers.CharField()
    errors = serializers.DictField(required=False)
