from rest_framework import serializers

from ..models import EmailAccount, EmailAccountTestStatus
from ..services import encrypt_smtp_password


class EmailAccountSerializer(serializers.ModelSerializer):
    password_configured = serializers.SerializerMethodField()

    class Meta:
        model = EmailAccount
        fields = [
            "id",
            "display_name",
            "sender_name",
            "sender_email",
            "smtp_host",
            "smtp_port",
            "smtp_username",
            "smtp_security",
            "is_enabled",
            "is_default",
            "password_configured",
            "last_test_status",
            "last_tested_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "is_default",
            "password_configured",
            "last_test_status",
            "last_tested_at",
            "created_at",
            "updated_at",
        ]

    def get_password_configured(self, instance):
        return bool(instance.smtp_password_ciphertext)


class EmailAccountWriteSerializer(serializers.ModelSerializer):
    smtp_password = serializers.CharField(write_only=True, required=False, trim_whitespace=False, max_length=1000)

    class Meta:
        model = EmailAccount
        fields = [
            "display_name",
            "sender_name",
            "sender_email",
            "smtp_host",
            "smtp_port",
            "smtp_username",
            "smtp_password",
            "smtp_security",
            "is_enabled",
        ]

    def validate_display_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("配置名称不能为空。")
        return value

    def validate_sender_name(self, value):
        return value.strip()

    def validate_smtp_host(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("SMTP 服务器不能为空。")
        return value

    def validate_smtp_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("SMTP 用户名不能为空。")
        return value

    def validate_smtp_password(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("SMTP 授权码不能为空。")
        return value

    def validate(self, attrs):
        if self.instance is None and "smtp_password" not in attrs:
            raise serializers.ValidationError({"smtp_password": "新增邮件账户必须填写 SMTP 授权码。"})
        return attrs

    def create(self, validated_data):
        smtp_password = validated_data.pop("smtp_password")
        return EmailAccount.objects.create(
            smtp_password_ciphertext=encrypt_smtp_password(smtp_password),
            **validated_data,
        )

    def update(self, instance, validated_data):
        smtp_password = validated_data.pop("smtp_password", None)
        settings_changed = bool(validated_data) or smtp_password is not None
        if smtp_password is not None:
            instance.smtp_password_ciphertext = encrypt_smtp_password(smtp_password)
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        if not instance.is_enabled:
            instance.is_default = False
        if settings_changed:
            instance.last_test_status = EmailAccountTestStatus.NOT_TESTED
            instance.last_tested_at = None
        instance.full_clean()
        instance.save()
        return instance


class EmailAccountTestSerializer(serializers.Serializer):
    recipient = serializers.EmailField()

