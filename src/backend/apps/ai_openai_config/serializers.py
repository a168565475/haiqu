from rest_framework import serializers

from .crypto import encrypt_key, key_metadata
from .models import OpenAIKeyConfig


class OpenAIKeyConfigSerializer(serializers.ModelSerializer):
    key_configured = serializers.SerializerMethodField()

    class Meta:
        model = OpenAIKeyConfig
        fields = [
            "id", "label", "provider", "model", "document_reasoning_effort", "material_reasoning_effort", "base_url",
            "key_configured", "key_last4", "key_fingerprint", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "key_configured", "key_last4", "key_fingerprint", "created_at", "updated_at",
        ]

    def get_key_configured(self, instance):
        return bool(instance.key_ciphertext)


class OpenAIKeyConfigWriteSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False, trim_whitespace=False, max_length=500)

    class Meta:
        model = OpenAIKeyConfig
        fields = ["label", "provider", "model", "document_reasoning_effort", "material_reasoning_effort", "base_url", "api_key"]

    def validate_label(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Key 标签不能为空。")
        return value

    def validate_provider(self, value):
        value = value.strip().lower()
        if not value:
            raise serializers.ValidationError("服务商不能为空。")
        return value

    def validate_model(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("模型不能为空。")
        return value

    def validate_base_url(self, value):
        return value.strip()

    def validate(self, attrs):
        if self.instance is None and not attrs.get("api_key"):
            raise serializers.ValidationError({"api_key": "新增配置必须填写 API Key。"})
        return attrs

    def create(self, validated_data):
        api_key = validated_data.pop("api_key")
        key_last4, fingerprint = key_metadata(api_key)
        return OpenAIKeyConfig.objects.create(
            key_ciphertext=encrypt_key(api_key),
            key_last4=key_last4,
            key_fingerprint=fingerprint,
            **validated_data,
        )

    def update(self, instance, validated_data):
        api_key = validated_data.pop("api_key", None)
        if api_key is not None:
            instance.key_ciphertext = encrypt_key(api_key)
            instance.key_last4, instance.key_fingerprint = key_metadata(api_key)
        for name, value in validated_data.items():
            setattr(instance, name, value)
        instance.full_clean()
        instance.save()
        return instance

