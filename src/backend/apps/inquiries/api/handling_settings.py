from copy import deepcopy

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound

from apps.core.audit import write_audit_log
from apps.core.api.concurrency import require_matching_etag
from apps.customers.api.views import CustomerApiViewSetBase
from apps.workflow.models import SlaPolicy
from ..handling_time import STAGE_LABELS
from ..worktime import validate_calendar, add_work_minutes


class HandlingSettingsSerializer(serializers.Serializer):
    stage_minutes = serializers.DictField(child=serializers.IntegerField(min_value=1, max_value=527040))
    work_calendar = serializers.DictField()

    def validate_stage_minutes(self, value):
        if set(value) != set(STAGE_LABELS):
            raise serializers.ValidationError('必须提供全部八个环节的工作分钟数。')
        return value

    def validate_work_calendar(self, value):
        try:
            validate_calendar(value)
        except (ValueError, KeyError, TypeError) as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return {key: value[key] for key in ['mode', 'timezone', 'rest_saturday', 'periods']}

    def validate(self, attrs):
        if attrs['stage_minutes']['ASSIGNMENT'] > attrs['stage_minutes']['FIRST_RESPONSE']:
            raise serializers.ValidationError({'stage_minutes': '分配负责人时限不能超过首次回复时限。'})
        try:
            add_work_minutes(timezone.now(), max(attrs['stage_minutes'].values()), attrs['work_calendar'])
        except ValueError as exc:
            raise serializers.ValidationError({'work_calendar': str(exc)}) from exc
        return attrs


def settings_data(policy):
    return {'stage_minutes': {**policy.config_data.get('stage_minutes', {}),
                             'FIRST_RESPONSE': policy.response_minutes,
                             'REQUIREMENT_CONFIRMATION': policy.resolution_minutes},
            'work_calendar': deepcopy(policy.config_data.get('work_calendar'))}


class InquiryHandlingSettingsViewSet(CustomerApiViewSetBase):
    action_permission_map = {'handling_settings.GET': 'workflow.view_slapolicy', 'handling_settings.PUT': 'workflow.manage_sla_policy'}
    serializer_class = HandlingSettingsSerializer

    @extend_schema(request=HandlingSettingsSerializer, responses=HandlingSettingsSerializer)
    @action(detail=False, methods=['get', 'put'], url_path='settings')
    def handling_settings(self, request):
        with transaction.atomic():
            policies = SlaPolicy.objects.filter(target_type='INQUIRY', is_enabled=True, archived_at__isnull=True).order_by('policy_code')
            policy = (policies.select_for_update() if request.method == 'PUT' else policies).first()
            if policy is None:
                raise NotFound('尚未启用询盘处理时限规则。')
            if request.method == 'PUT':
                require_matching_etag(request, policy)
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                before = settings_data(policy)
                data = serializer.validated_data
                stages = data['stage_minutes']
                policy.response_minutes = stages['FIRST_RESPONSE']
                policy.resolution_minutes = stages['REQUIREMENT_CONFIRMATION']
                policy.config_data = {**policy.config_data, 'work_calendar': data['work_calendar'],
                                      'stage_minutes': {key: value for key, value in stages.items() if key not in ['FIRST_RESPONSE', 'REQUIREMENT_CONFIRMATION']}}
                policy.save(update_fields=['response_minutes', 'resolution_minutes', 'config_data', 'updated_at'])
                write_audit_log(object_type='SLA_POLICY', object_id=policy.pk, action='INQUIRY_HANDLING_SETTINGS_UPDATED',
                                actor_employee=self.actor_employee(), request=request, before_data=before, after_data=settings_data(policy))
            return self.response_with_etag({'data': settings_data(policy)}, policy)
