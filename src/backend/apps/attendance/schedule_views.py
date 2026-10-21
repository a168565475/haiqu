from django.views.decorators.debug import sensitive_variables
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from apps.core.api.exceptions import Conflict
from apps.wecom.client import WeComError
from apps.wecom.selectors import get_config
from . import schedule, services
from .client import AttendanceClient
from .schedule_serializers import (
    RulesResponseSerializer, ScheduleQuerySerializer, ScheduleResponseSerializer, ScheduleWriteSerializer,
)
from .views import AttendanceView, ERROR_RESPONSES, IF_MATCH


class RuleReadFailure(APIException):
    status_code = 502
    api_error_code = "ATTENDANCE_RULE_ERROR"
    default_detail = "企业微信打卡规则读取失败，请检查打卡接口授权或稍后重试。"


def period_query(request):
    query = ScheduleQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    return query.validated_data["month"]


def schedule_response(payload):
    return Response(ScheduleResponseSerializer({"data": payload}).data, headers={"ETag": payload["etag"]})


class ScheduleView(AttendanceView):
    @extend_schema(parameters=[ScheduleQuerySerializer], responses={200: ScheduleResponseSerializer, **ERROR_RESPONSES})
    def get(self, request):
        month = period_query(request)
        return schedule_response(schedule.get_schedule(get_config().corp_id, month))

    @extend_schema(parameters=[ScheduleQuerySerializer, IF_MATCH], request=ScheduleWriteSerializer,
                   responses={200: ScheduleResponseSerializer, 412: OpenApiResponse(description="安排已被其他人修改"),
                              428: OpenApiResponse(description="缺少If-Match"), **ERROR_RESPONSES})
    def put(self, request):
        schedule.require_schedule_access(request)
        month = period_query(request)
        data = ScheduleWriteSerializer(data=request.data, context={"month": month})
        data.is_valid(raise_exception=True)
        config = get_config()
        if config._state.adding:
            raise Conflict("请先保存企业微信企业配置，再设置月度安排。")
        return schedule_response(schedule.save_schedule(request, config.corp_id, month, data.validated_data))


class RulesView(AttendanceView):
    @extend_schema(parameters=[ScheduleQuerySerializer], responses={200: RulesResponseSerializer,
                   502: OpenApiResponse(description="企业微信规则接口读取失败"), **ERROR_RESPONSES})
    @sensitive_variables()
    def get(self, request):
        schedule.require_schedule_access(request)
        month = period_query(request)
        config = get_config()
        if not services.valid_configuration(config):
            raise Conflict("企业微信应用未启用或配置不完整，请联系管理员。")
        version = services.configuration_version(config)
        try:
            groups = AttendanceClient(config).get_rules()
        except WeComError as error:
            # 客户端 message 仅来自固定错误表，不使用企微原始 errmsg。
            raise RuleReadFailure(error.message) from None
        schedule.require_schedule_access(request)
        if services.configuration_version(get_config()) != version:
            raise Conflict("读取期间企业微信配置已变化，请重新读取规则。")
        return Response(RulesResponseSerializer({"data": schedule.rule_options(groups, month, config.corp_id)}).data)
