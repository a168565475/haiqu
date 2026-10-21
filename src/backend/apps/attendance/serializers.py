from django.utils import timezone
from rest_framework import serializers

from .schedule_serializers import ScheduleDaySerializer
from .source import BEIJING, month_dates


class StrictSerializer(serializers.Serializer):
    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError("请求包含不支持的字段。")
        return attrs


class MonthQuerySerializer(StrictSerializer):
    month = serializers.CharField(max_length=7)

    def validate_month(self, value):
        try:
            first, _ = month_dates(value)
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from None
        if first > timezone.now().astimezone(BEIJING).date().replace(day=1):
            raise serializers.ValidationError("不能查询或同步尚未开始的月份。")
        return value


class RecordQuerySerializer(MonthQuerySerializer):
    search = serializers.CharField(max_length=150, required=False, allow_blank=True)
    department = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    user_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    binding = serializers.ChoiceField(choices=["BOUND", "UNBOUND"], required=False)
    status = serializers.ChoiceField(choices=["RETURNED", "NOT_RETURNED"], required=False)
    date = serializers.DateField(required=False)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        kind = self.context.get("kind")
        if attrs.get("date") and (kind == "monthly" or attrs["date"].strftime("%Y-%m") != attrs["month"]):
            raise serializers.ValidationError({"date": "日期仅用于日报或明细，且必须属于当前月份。"})
        if attrs.get("status") and kind != "monthly":
            raise serializers.ValidationError({"status": "返回状态筛选仅适用于全员月报。"})
        return attrs


class CalendarQuerySerializer(MonthQuerySerializer):
    user_id = serializers.CharField(max_length=64)


class SyncStartSerializer(MonthQuerySerializer):
    idempotency_key = serializers.UUIDField()


class EmptySerializer(StrictSerializer):
    pass


class SyncRunSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    month = serializers.CharField()
    status = serializers.ChoiceField(choices=["PENDING", "RUNNING", "FAILED", "SUCCESS", "INVALIDATED"])
    phase = serializers.CharField()
    completed_steps = serializers.IntegerField()
    total_steps = serializers.IntegerField()
    scanned_members = serializers.IntegerField()
    error_code = serializers.CharField(allow_blank=True)
    error_message = serializers.CharField(allow_blank=True)
    can_retry = serializers.BooleanField()
    etag = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class SyncRunResponseSerializer(serializers.Serializer):
    data = SyncRunSerializer()


class OverviewSerializer(serializers.Serializer):
    month = serializers.CharField()
    corp_id = serializers.CharField()
    has_data = serializers.BooleanField()
    last_synced_at = serializers.DateTimeField(allow_null=True)
    scanned_members = serializers.IntegerField()
    attendance_members = serializers.IntegerField()
    raw_count = serializers.IntegerField()
    daily_count = serializers.IntegerField()
    monthly_count = serializers.IntegerField()
    source_start = serializers.DateField(allow_null=True)
    source_end = serializers.DateField(allow_null=True)
    departments = serializers.ListField(child=serializers.CharField())
    current_run = SyncRunSerializer(allow_null=True)
    history_notice = serializers.CharField()


class OverviewResponseSerializer(serializers.Serializer):
    data = OverviewSerializer()


class ExceptionSerializer(serializers.Serializer):
    type = serializers.IntegerField()
    count = serializers.IntegerField(allow_null=True)


class AbsenceItemSerializer(serializers.Serializer):
    type = serializers.IntegerField()
    vacation_id = serializers.IntegerField(allow_null=True)
    count = serializers.IntegerField(allow_null=True)
    duration = serializers.IntegerField(allow_null=True)
    time_type = serializers.IntegerField(allow_null=True)
    name = serializers.CharField(allow_null=True, allow_blank=True)


class DailyOvertimeSerializer(serializers.Serializer):
    ot_status = serializers.IntegerField(allow_null=True)
    ot_duration = serializers.IntegerField(allow_null=True)
    exception_duration = serializers.ListField(child=serializers.IntegerField(), allow_null=True)
    workday_over_as_vacation = serializers.IntegerField(allow_null=True)
    workday_over_as_money = serializers.IntegerField(allow_null=True)
    restday_over_as_vacation = serializers.IntegerField(allow_null=True)
    restday_over_as_money = serializers.IntegerField(allow_null=True)
    holiday_over_as_vacation = serializers.IntegerField(allow_null=True)
    holiday_over_as_money = serializers.IntegerField(allow_null=True)


class MonthlyOvertimeSerializer(serializers.Serializer):
    workday_over_sec = serializers.IntegerField(allow_null=True)
    restdays_over_sec = serializers.IntegerField(allow_null=True)
    holidays_over_sec = serializers.IntegerField(allow_null=True)
    workdays_over_as_vacation = serializers.IntegerField(allow_null=True)
    workdays_over_as_money = serializers.IntegerField(allow_null=True)
    restdays_over_as_vacation = serializers.IntegerField(allow_null=True)
    restdays_over_as_money = serializers.IntegerField(allow_null=True)
    holidays_over_as_vacation = serializers.IntegerField(allow_null=True)
    holidays_over_as_money = serializers.IntegerField(allow_null=True)


class MonthlyRowSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    department_name = serializers.CharField(allow_blank=True)
    employee_id = serializers.UUIDField(allow_null=True)
    employee_name = serializers.CharField(allow_null=True)
    record_status = serializers.ChoiceField(choices=["RETURNED", "NOT_RETURNED"])
    work_days = serializers.IntegerField(allow_null=True)
    standard_work_sec = serializers.IntegerField(allow_null=True)
    regular_work_sec = serializers.IntegerField(allow_null=True)
    late_count = serializers.IntegerField(allow_null=True)
    early_count = serializers.IntegerField(allow_null=True)
    missing_count = serializers.IntegerField(allow_null=True)
    sp_items = AbsenceItemSerializer(many=True, allow_null=True)
    overwork_info = MonthlyOvertimeSerializer(allow_null=True)


class RawRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    date = serializers.DateField()
    user_id = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    department_name = serializers.CharField(allow_blank=True)
    checkin_time = serializers.DateTimeField()
    checkin_type = serializers.CharField(allow_blank=True)
    group_name = serializers.CharField(allow_blank=True)
    exceptions = serializers.ListField(child=serializers.CharField())


class DailyRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    date = serializers.DateField()
    user_id = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    department_name = serializers.CharField(allow_blank=True)
    group_name = serializers.CharField(allow_blank=True)
    schedule_name = serializers.CharField(allow_blank=True)
    checkin_count = serializers.IntegerField(allow_null=True)
    standard_work_sec = serializers.IntegerField(allow_null=True)
    regular_work_sec = serializers.IntegerField(allow_null=True)
    exceptions = ExceptionSerializer(many=True, allow_null=True)
    sp_items = AbsenceItemSerializer(many=True, allow_null=True)
    ot_info = DailyOvertimeSerializer(allow_null=True)


class PageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class MonthlyPageSerializer(PageSerializer):
    data = MonthlyRowSerializer(many=True)


class DailyPageSerializer(PageSerializer):
    data = DailyRowSerializer(many=True)


class RawPageSerializer(PageSerializer):
    data = RawRowSerializer(many=True)


class CalendarSourceSummarySerializer(serializers.Serializer):
    record_id = serializers.UUIDField(allow_null=True)
    sp_items = AbsenceItemSerializer(many=True, allow_null=True)
    ot_info = DailyOvertimeSerializer(allow_null=True)


class CalendarDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    report_returned = serializers.BooleanField()
    checkin_count = serializers.IntegerField(allow_null=True)
    states = serializers.ListField(child=serializers.CharField())
    exceptions = ExceptionSerializer(many=True, allow_null=True)
    raw = RawRowSerializer(many=True)
    schedule = ScheduleDaySerializer(allow_null=True)
    source_summaries = CalendarSourceSummarySerializer(many=True)


class CalendarSerializer(serializers.Serializer):
    month = serializers.CharField()
    user_id = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    days = CalendarDaySerializer(many=True)


class CalendarResponseSerializer(serializers.Serializer):
    data = CalendarSerializer()


class VacationItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(allow_null=True, allow_blank=True)
    time_attr = serializers.IntegerField(allow_null=True)
    duration_type = serializers.IntegerField(allow_null=True)
    quota_type = serializers.IntegerField(allow_null=True)
    perday_duration = serializers.IntegerField(allow_null=True)
    assignduration = serializers.IntegerField(allow_null=True)
    real_assignduration = serializers.IntegerField(allow_null=True)
    usedduration = serializers.IntegerField(allow_null=True)
    leftduration = serializers.IntegerField(allow_null=True)


class VacationSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    fetched_at = serializers.DateTimeField()
    is_current = serializers.BooleanField()
    items = VacationItemSerializer(many=True)


class VacationResponseSerializer(serializers.Serializer):
    data = VacationSerializer()
