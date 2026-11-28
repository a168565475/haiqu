from rest_framework import serializers

from ..delivery_reminders import FOLLOW_UP_FILTERS, PRIORITY


class ReminderFilter(serializers.Serializer):
    follow_up = serializers.ChoiceField(choices=FOLLOW_UP_FILTERS, default="ALL")
    owner = serializers.CharField(max_length=150, allow_blank=True, default="")


class DeliveryReminderSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=tuple(PRIORITY))
    label = serializers.CharField()
    due = serializers.DateField(allow_null=True)
    quantity = serializers.CharField(allow_null=True)
    unit = serializers.CharField()
    action = serializers.CharField()
    owner = serializers.CharField()
    reference = serializers.CharField()
    reason = serializers.CharField()
    shared = serializers.BooleanField()
