from datetime import timedelta

from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Q
from django.utils import timezone

from .models import WeComBinding, WeComConfig
from .selectors import config_etag, configuration_complete


PREVIEW_MIGRATION = "0006_notification_preview_attempt"


def schema_ready():
    return MigrationRecorder.Migration.objects.filter(app="wecom", name=PREVIEW_MIGRATION).exists()


def recipient_options(search="", page=1):
    ready = schema_ready()
    config = WeComConfig.objects.first()
    available = ready and config is not None and config.enabled and configuration_complete(config)
    message = ("预览试发尚未启用，请联系管理员完成数据库升级。" if not ready else
               "请先配置并启用企业微信应用。" if not available else "")
    rows, count = [], 0
    if available:
        queryset = WeComBinding.objects.filter(corp_id=config.corp_id, employee__status="ACTIVE",
            employee__archived_at__isnull=True, employee__user__is_active=True).select_related("employee")
        if search:
            queryset = queryset.filter(Q(employee__display_name__icontains=search) | Q(employee__employee_code__icontains=search))
        queryset = queryset.order_by("employee__employee_code", "id")
        count = queryset.count()
        rows = [{"binding_id": str(row.pk), "employee_code": row.employee.employee_code,
                 "employee_name": row.employee.display_name} for row in queryset[(page - 1) * 50:page * 50]]
        if not count:
            message = "没有符合条件的已绑定员工。"
    return {"data": rows, "count": count, "page": page, "page_size": 50,
            "available": bool(available), "schema_ready": ready, "message": message,
            "config_etag": config_etag(config) if config else ""}


def attempt_payload(attempt):
    status = attempt.status
    if status == "PROCESSING" and attempt.created_at < timezone.now() - timedelta(seconds=60):
        status = "UNCERTAIN"
    messages = {
        "PROCESSING": "正在提交企业微信，请查询本次结果，勿重复发送。",
        "ACCEPTED": "企业微信已受理，不代表员工已读。",
        "FAILED": "企业微信发送明确失败，请核对配置和接收人。",
        "UNCERTAIN": "发送结果待核对，请先查看企业微信，勿重复发送。",
    }
    return {"id": str(attempt.pk), "preview_id": str(attempt.preview_id), "status": status,
            "message": messages[status], "recipient_name": attempt.recipient_name,
            "created_at": attempt.created_at, "finished_at": attempt.finished_at}
