from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.permissions import HasActiveEmployee
from apps.wecom.middleware import WeComExceptionReporterFilter
from apps.wecom.client import WeComError
from . import schedule, selectors, services
from apps.wecom.selectors import get_config
from .serializers import (
    CalendarQuerySerializer, CalendarResponseSerializer, DailyPageSerializer, EmptySerializer,
    MonthQuerySerializer, MonthlyPageSerializer, OverviewResponseSerializer, RawPageSerializer,
    RecordQuerySerializer, SyncRunResponseSerializer, SyncStartSerializer, VacationResponseSerializer,
)


IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)
ERROR_RESPONSES = {400: OpenApiResponse(description="参数不符合契约"),
                   403: OpenApiResponse(description="登录、有效员工、考勤权限或CSRF校验未通过"),
                   409: OpenApiResponse(description="任务或配置冲突"),
                   503: OpenApiResponse(description="尚未执行考勤数据库迁移")}


class AttendanceUnavailable(APIException):
    status_code = 503
    api_error_code = "ATTENDANCE_UNAVAILABLE"
    default_detail = "考勤模块尚未执行已审阅的数据库迁移。"


class VacationReadFailure(APIException):
    status_code = 502
    api_error_code = "ATTENDANCE_VACATION_ERROR"
    default_detail = "企业微信当前假期余额读取失败，请检查授权或稍后重试。"


@method_decorator(never_cache, name="dispatch")
class AttendanceView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee]
    sync_access = False

    def initial(self, request, *args, **kwargs):
        request._request.exception_reporter_filter = WeComExceptionReporterFilter()
        super().initial(request, *args, **kwargs)
        services.require_access(request, sync=self.sync_access)
        if not selectors.schema_is_ready():
            raise AttendanceUnavailable()


class OverviewView(AttendanceView):
    @extend_schema(parameters=[MonthQuerySerializer], responses={200: OverviewResponseSerializer, **ERROR_RESPONSES})
    def get(self, request):
        query = MonthQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(OverviewResponseSerializer({"data": selectors.overview(query.validated_data["month"])}).data)


class RecordView(AttendanceView):
    def records(self, request, kind, response_serializer):
        query = RecordQuerySerializer(data=request.query_params, context={"kind": kind})
        query.is_valid(raise_exception=True)
        return Response(response_serializer(selectors.rows(kind, query.validated_data)).data)


class MonthlyRecordsView(RecordView):
    @extend_schema(parameters=[RecordQuerySerializer], responses={200: MonthlyPageSerializer, **ERROR_RESPONSES})
    def get(self, request):
        return self.records(request, "monthly", MonthlyPageSerializer)


class DailyRecordsView(RecordView):
    @extend_schema(parameters=[RecordQuerySerializer], responses={200: DailyPageSerializer, **ERROR_RESPONSES})
    def get(self, request):
        return self.records(request, "daily", DailyPageSerializer)


class RawRecordsView(RecordView):
    @extend_schema(parameters=[RecordQuerySerializer], responses={200: RawPageSerializer, **ERROR_RESPONSES})
    def get(self, request):
        return self.records(request, "raw", RawPageSerializer)


class CalendarView(AttendanceView):
    @extend_schema(parameters=[CalendarQuerySerializer], responses={200: CalendarResponseSerializer, **ERROR_RESPONSES})
    def get(self, request):
        query = CalendarQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        payload = selectors.member_calendar(**query.validated_data)
        payload = schedule.decorate_calendar(payload, get_config().corp_id)
        return Response(CalendarResponseSerializer({"data": payload}).data)


class VacationView(AttendanceView):
    @extend_schema(parameters=[CalendarQuerySerializer], responses={200: VacationResponseSerializer,
        404: OpenApiResponse(description="当前成功快照没有此成员"),
        502: OpenApiResponse(description="企业微信假期读取失败"), **ERROR_RESPONSES})
    def get(self, request):
        query = CalendarQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            payload = services.current_vacation(request, **query.validated_data)
        except WeComError as error:
            raise VacationReadFailure(error.message) from None
        return Response(VacationResponseSerializer({"data": payload}).data)


def run_response(run):
    payload = selectors.run_payload(run)
    return Response(SyncRunResponseSerializer({"data": payload}).data, headers={"ETag": payload["etag"]})


class SyncStartView(AttendanceView):
    sync_access = True

    @extend_schema(request=SyncStartSerializer, responses={200: SyncRunResponseSerializer, **ERROR_RESPONSES})
    def post(self, request):
        query = SyncStartSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        return run_response(services.start_sync(request, **query.validated_data))


class SyncDetailView(AttendanceView):
    @extend_schema(responses={200: SyncRunResponseSerializer, **ERROR_RESPONSES})
    def get(self, request, run_id):
        return run_response(selectors.get_run(run_id))


class SyncStepView(AttendanceView):
    sync_access = True

    @extend_schema(request=EmptySerializer, parameters=[IF_MATCH], responses={200: SyncRunResponseSerializer,
        412: OpenApiResponse(description="任务版本已更新"), 428: OpenApiResponse(description="缺少If-Match"),
        429: OpenApiResponse(description="重试间隔尚未结束"), **ERROR_RESPONSES})
    def post(self, request, run_id):
        query = EmptySerializer(data=request.data)
        query.is_valid(raise_exception=True)
        return run_response(services.advance_sync(request, run_id))
