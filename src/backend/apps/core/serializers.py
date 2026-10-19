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


class AuthenticationStateSerializer(serializers.Serializer):
    authenticated = serializers.BooleanField()
    user = AuthUserSerializer(allow_null=True)


class HealthResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    service = serializers.CharField()
    database = serializers.CharField()
    redis = serializers.CharField()
    errors = serializers.DictField(required=False)
