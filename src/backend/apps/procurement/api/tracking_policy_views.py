from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_control.management_permissions import can_manage
from apps.access_control.permissions import CanManageNotifications
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import HasActiveEmployee
from apps.material_catalog.definitions import CATEGORY_CHOICES

from ..tracking_models import PurchaseTrackingPolicy
from ..tracking_policy import policy_values, require_policy_enabled, update_tracking_policy
from .tracking_views import TrackingViewPermission


class TrackingPolicyWriteSerializer(serializers.Serializer):
    bom_timeout_days = serializers.IntegerField(min_value=0, max_value=365, allow_null=True, required=False)
    category_lead_days = serializers.DictField(
        child=serializers.IntegerField(min_value=0, max_value=365, allow_null=True), required=False,
    )

    def validate_category_lead_days(self, value):
        if set(value) - {key for key, _label in CATEGORY_CHOICES}:
            raise serializers.ValidationError("存在无效的材料分类。")
        return value

    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError("包含不支持的配置字段。")
        if not attrs:
            raise serializers.ValidationError("请提供需要修改的时间规则。")
        return attrs


class TrackingPolicyCategorySerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class TrackingPolicySerializer(serializers.Serializer):
    bom_timeout_days = serializers.IntegerField(allow_null=True)
    category_lead_days = serializers.DictField(child=serializers.IntegerField(allow_null=True))
    categories = TrackingPolicyCategorySerializer(many=True)
    etag = serializers.CharField()
    can_manage = serializers.BooleanField()


class TrackingPolicyResponseSerializer(serializers.Serializer):
    data = TrackingPolicySerializer()


def _policy_response(request, policy):
    etag = etag_for_instance(policy)
    data = {
        **policy_values(policy),
        "categories": [{"key": key, "label": label} for key, label in CATEGORY_CHOICES],
        "etag": etag,
        "can_manage": settings.ACCESS_MANAGEMENT_ENABLED and can_manage(request.user, "access_control.manage_notifications"),
    }
    return Response(TrackingPolicyResponseSerializer({"data": data}).data, headers={"ETag": etag})


@method_decorator(never_cache, name="dispatch")
@method_decorator(csrf_protect, name="dispatch")
class PurchaseTrackingPolicyView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee, TrackingViewPermission]

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.request.method == "PATCH":
            permissions.append(CanManageNotifications())
        return permissions

    @extend_schema(responses=TrackingPolicyResponseSerializer)
    def get(self, request):
        require_policy_enabled()
        return _policy_response(request, PurchaseTrackingPolicy.objects.get(key="default"))

    @extend_schema(request=TrackingPolicyWriteSerializer, responses=TrackingPolicyResponseSerializer)
    def patch(self, request):
        require_policy_enabled()
        serializer = TrackingPolicyWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _policy_response(request, update_tracking_policy(request, serializer.validated_data))
