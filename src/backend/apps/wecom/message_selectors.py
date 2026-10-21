from datetime import timedelta

from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from apps.core.api.concurrency import etag_for_instance
from .models import WeComMessageAttempt, WeComMessageTemplate


DEFAULT_NAME = "通用通知"
DEFAULT_BODY = "{{接收人}}，你好：\n\n{{消息内容}}\n\n发送时间：{{发送时间}}\n系统地址：{{系统地址}}"
STATUS_MESSAGES = {
    "PROCESSING": "正在提交企业微信，请稍后刷新发送记录。",
    "ACCEPTED": "企业微信已接受消息，请在企业微信中查看。",
    "FAILED": "消息未发送，请检查应用配置或接收人后重新发送。",
    "UNCERTAIN": "发送结果待核对，请先查看企业微信，勿重复发送。",
}
FAILURE_MESSAGES = {
    "RECIPIENT_REJECTED": "接收人不在应用可见范围内、不存在，或缺少接口许可。",
    "CONFIGURATION_ERROR": "应用配置不可用，请核对凭据、应用权限和服务器可信 IP。",
    "UPSTREAM_UNAVAILABLE": "提交消息前无法取得有效调用凭证，消息未发送。",
    "MESSAGE_REJECTED": "企业微信明确拒绝了消息，请检查应用配置、接收人和发送限制。",
}


def schema_is_ready():
    return MigrationRecorder.Migration.objects.filter(app="wecom", name="0002_message_template_and_attempt").exists()


def get_template():
    return WeComMessageTemplate.objects.first()


def template_etag(template):
    return etag_for_instance(template) if template else '"wecom-message-template-unsaved"'


def template_payload(template):
    return {"name": template.name if template else DEFAULT_NAME, "body": template.body if template else DEFAULT_BODY,
            "is_saved": template is not None, "updated_at": template.updated_at if template else None}


def attempts_queryset(idempotency_key=None):
    queryset = WeComMessageAttempt.objects.all()
    return queryset.filter(idempotency_key=idempotency_key) if idempotency_key else queryset


def attempt_payload(attempt):
    status = attempt.status
    # 工作进程可能在外部接口已接受后退出；超时只改变展示，不将它认定为失败或允许重发。
    if status == "PROCESSING" and attempt.created_at < timezone.now() - timedelta(seconds=60):
        status = "UNCERTAIN"
    message = STATUS_MESSAGES[status]
    if status == "FAILED":
        message = FAILURE_MESSAGES.get(attempt.error_code, message)
    return {"id": attempt.pk, "idempotency_key": attempt.idempotency_key, "template_name": attempt.template_name,
            "recipient_name": attempt.recipient_name, "user_id": attempt.user_id, "status": status,
            "message": message, "created_at": attempt.created_at, "finished_at": attempt.finished_at}
