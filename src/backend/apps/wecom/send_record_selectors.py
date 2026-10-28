from datetime import timedelta

from django.db.models import Case, CharField, F, Value, When
from django.utils import timezone

from .models import NotificationDelivery, NotificationPreviewAttempt, WeComMessageAttempt
from .notification_catalog import EVENTS


def send_records_queryset(source, employee_id, status=None):
    if source == "BUSINESS":
        queryset = NotificationDelivery.objects.filter(channel="WECOM").select_related("recipient__event")
        if status:
            queryset = queryset.filter(status=status)
    else:
        queryset = (NotificationPreviewAttempt.objects.filter(requested_by_employee_id=employee_id)
                    if source == "RULE_PREVIEW" else WeComMessageAttempt.objects.all())
        # 沿用人工试发的超时展示口径，同时保证状态筛选与展示一致；不改写原记录。
        queryset = queryset.annotate(record_status=Case(
            When(status="PROCESSING", created_at__lt=timezone.now() - timedelta(seconds=60),
                 then=Value("UNCERTAIN")),
            default=F("status"), output_field=CharField(),
        ))
        if status:
            queryset = queryset.filter(record_status=status)
    return queryset.order_by("-created_at", "-id")


def send_record_payload(record, source):
    if source == "BUSINESS":
        event = record.recipient.event
        recipient_name, event_code = record.recipient.employee_name, event.event_code
        title, body = event.rendered_title, event.rendered_body
        sent_at, attempt_count, status = record.last_attempt_at, record.attempt_count, record.status
    else:
        recipient_name = record.recipient_name
        event_code = record.event_code if source == "RULE_PREVIEW" else ""
        title = record.rendered_title if source == "RULE_PREVIEW" else record.template_name
        body = record.rendered_body
        sent_at, attempt_count, status = record.created_at, 1, record.record_status
    event_name = ("人工消息测试" if source == "MESSAGE_TEST"
                  else EVENTS.get(event_code, {}).get("display_name", event_code))
    return {
        "id": record.pk, "source": source, "recipient_name": recipient_name,
        "event_code": event_code, "event_name": event_name, "title": title, "body": body,
        "status": status, "error_code": record.error_code, "attempt_count": attempt_count,
        "created_at": record.created_at, "sent_at": sent_at, "finished_at": record.finished_at,
    }
