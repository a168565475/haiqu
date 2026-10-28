from rest_framework import serializers

from .models import NotificationDelivery, WeComMessageAttempt
from .notification_serializers import NotificationQuerySerializer


SEND_RECORD_SOURCES = (
    ("BUSINESS", "自动业务通知"),
    ("RULE_PREVIEW", "规则卡片试发"),
    ("MESSAGE_TEST", "人工消息测试"),
)


class SendRecordQuerySerializer(NotificationQuerySerializer):
    source = serializers.ChoiceField(choices=SEND_RECORD_SOURCES, default="BUSINESS")
    status = serializers.ChoiceField(choices=NotificationDelivery.Status.choices, required=False)

    def validate(self, attrs):
        if (attrs["source"] != "BUSINESS" and "status" in attrs
                and attrs["status"] not in WeComMessageAttempt.Status.values):
            raise serializers.ValidationError({"status": "人工发送记录不支持该状态。"})
        return attrs


class SendRecordSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    source = serializers.ChoiceField(choices=SEND_RECORD_SOURCES)
    recipient_name = serializers.CharField()
    event_code = serializers.CharField(allow_blank=True)
    event_name = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    body = serializers.CharField(allow_blank=True, help_text="已保存的通知内容快照。")
    status = serializers.ChoiceField(choices=NotificationDelivery.Status.choices)
    error_code = serializers.CharField(allow_blank=True)
    attempt_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    sent_at = serializers.DateTimeField(allow_null=True,
        help_text="自动通知为最近发送尝试时间，尚未尝试则为空；人工发送为请求创建时间。")
    finished_at = serializers.DateTimeField(allow_null=True)


class SendRecordListSerializer(serializers.Serializer):
    data = SendRecordSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
