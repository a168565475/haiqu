from rest_framework import serializers
from drf_spectacular.utils import extend_schema_serializer

from .models import ConnectionStatus


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError({'non_field_errors': ['请求包含不支持的字段。']})
        return super().to_internal_value(data)


@extend_schema_serializer(component_name='CodexEmpty')
class EmptySerializer(StrictSerializer):
    pass


@extend_schema_serializer(component_name='CodexCancel')
class CancelSerializer(StrictSerializer):
    operation_id = serializers.UUIDField()


@extend_schema_serializer(component_name='CodexChallengeQuery')
class ChallengeQuerySerializer(CancelSerializer):
    def to_internal_value(self, data):
        return super().to_internal_value(dict(data.items()))


@extend_schema_serializer(component_name='CodexModelSelection')
class ModelSerializer(StrictSerializer):
    model = serializers.CharField(max_length=200)


@extend_schema_serializer(component_name='CodexAccount')
class AccountSerializer(serializers.Serializer):
    display_name = serializers.CharField()
    plan_type = serializers.CharField()


@extend_schema_serializer(component_name='CodexVisibleModel')
class VisibleModelSerializer(serializers.Serializer):
    id = serializers.CharField()
    display_name = serializers.CharField()


@extend_schema_serializer(component_name='CodexLimitWindow')
class LimitWindowSerializer(serializers.Serializer):
    name = serializers.CharField()
    used_percent = serializers.FloatField(allow_null=True)
    window_minutes = serializers.IntegerField(allow_null=True)
    resets_at = serializers.DateTimeField(allow_null=True)


@extend_schema_serializer(component_name='CodexCredits')
class CreditsSerializer(serializers.Serializer):
    unlimited = serializers.BooleanField()
    has_credits = serializers.BooleanField()
    balance = serializers.CharField(allow_null=True, allow_blank=True)


@extend_schema_serializer(component_name='CodexRateLimits')
class RateLimitsSerializer(serializers.Serializer):
    windows = LimitWindowSerializer(many=True)
    credits = CreditsSerializer(allow_null=True)


@extend_schema_serializer(component_name='CodexOperation')
class OperationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=['login', 'switch', 'disconnect', 'refresh', 'test'])
    state = serializers.ChoiceField(choices=['QUEUED', 'RUNNING', 'CANCELING'])
    actor_id = serializers.UUIDField()
    can_cancel = serializers.BooleanField()


@extend_schema_serializer(component_name='CodexSnapshot')
class SnapshotSerializer(serializers.Serializer):
    config_generation = serializers.IntegerField()
    status = serializers.ChoiceField(choices=ConnectionStatus.values)
    selected_model = serializers.CharField(allow_blank=True)
    cli_version = serializers.CharField(allow_blank=True)
    account = AccountSerializer(allow_null=True)
    models = VisibleModelSerializer(many=True)
    rate_limits = RateLimitsSerializer(allow_null=True)
    limits_updated_at = serializers.DateTimeField(allow_null=True)
    last_checked_at = serializers.DateTimeField(allow_null=True)
    last_test_at = serializers.DateTimeField(allow_null=True)
    error_code = serializers.CharField(allow_blank=True)
    paused = serializers.BooleanField()
    operation = OperationSerializer(allow_null=True)


@extend_schema_serializer(component_name='CodexSnapshotResponse')
class SnapshotResponseSerializer(serializers.Serializer):
    data = SnapshotSerializer()


@extend_schema_serializer(component_name='CodexChallenge')
class ChallengeSerializer(serializers.Serializer):
    operation_id = serializers.UUIDField()
    verification_url = serializers.URLField()
    user_code = serializers.CharField()
    expires_at = serializers.DateTimeField()


@extend_schema_serializer(component_name='CodexChallengeResponse')
class ChallengeResponseSerializer(serializers.Serializer):
    data = ChallengeSerializer()
