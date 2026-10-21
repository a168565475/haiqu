from datetime import date
from collections.abc import Mapping

from rest_framework import serializers

from .schedule import month_days


class ScheduleStrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, Mapping) and set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["请求包含不支持的字段。"]})
        return super().to_internal_value(data)


class ScheduleQuerySerializer(ScheduleStrictSerializer):
    month = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])$", max_length=7)

    def validate_month(self, value):
        try:
            return date.fromisoformat(value + "-01")
        except ValueError:
            raise serializers.ValidationError("月份格式应为 YYYY-MM。") from None


class SchedulePeriodSerializer(ScheduleStrictSerializer):
    start_sec = serializers.IntegerField(min_value=0, max_value=86399)
    end_sec = serializers.IntegerField(min_value=1, max_value=86399)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["start_sec"] >= attrs["end_sec"]:
            raise serializers.ValidationError("下班须晚于上班，当前不支持跨日时段。")
        return attrs


class ScheduleDaySerializer(ScheduleStrictSerializer):
    date = serializers.DateField()
    kind = serializers.ChoiceField(choices=["WORK", "REST", "UNSET"])
    periods = SchedulePeriodSerializer(many=True, max_length=8)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        periods = attrs["periods"]
        if (attrs["kind"] == "WORK") != bool(periods):
            raise serializers.ValidationError("工作日须填写时段；休息或未设置日期不能填写时段。")
        if any(left["end_sec"] > right["start_sec"] for left, right in zip(periods, periods[1:])):
            raise serializers.ValidationError("时段须按时间排列且不能重叠。")
        return attrs


class ScheduleWriteSerializer(ScheduleStrictSerializer):
    days = ScheduleDaySerializer(many=True, min_length=28, max_length=31)
    import_token = serializers.CharField(max_length=8192, allow_null=True, required=False, default=None)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        expected = month_days(self.context["month"])
        received = [day["date"] for day in attrs["days"]]
        if len(received) != len(set(received)) or set(received) != set(expected):
            raise serializers.ValidationError({"days": "必须包含所选月份的每个日期，不能重复或混入其他月份。"})
        attrs["days"] = [{**day, "date": day["date"].isoformat()} for day in sorted(attrs["days"], key=lambda item: item["date"])]
        return attrs


class ScheduleSourceSerializer(serializers.Serializer):
    rule_id = serializers.IntegerField()
    rule_name = serializers.CharField()
    fetched_at = serializers.DateTimeField()
    warnings = serializers.ListField(child=serializers.CharField())


class ScheduleSerializer(serializers.Serializer):
    month = serializers.CharField()
    configured = serializers.BooleanField()
    days = ScheduleDaySerializer(many=True)
    source = ScheduleSourceSerializer(allow_null=True)
    import_token = serializers.CharField(allow_null=True)
    etag = serializers.CharField()


class ScheduleResponseSerializer(serializers.Serializer):
    data = ScheduleSerializer()


class RuleOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    type = serializers.IntegerField()
    can_import = serializers.BooleanField()
    reason = serializers.CharField(allow_blank=True)
    days = ScheduleDaySerializer(many=True)
    warnings = serializers.ListField(child=serializers.CharField())
    import_token = serializers.CharField(allow_null=True)


class RulesSerializer(serializers.Serializer):
    rules = RuleOptionSerializer(many=True)
    fetched_at = serializers.DateTimeField()


class RulesResponseSerializer(serializers.Serializer):
    data = RulesSerializer()
