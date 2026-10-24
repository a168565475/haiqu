from datetime import timedelta
from uuid import uuid4

from django.core import signing
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404

from apps.access_control.management_permissions import can_manage, require_wecom_manager
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.auth import active_employee_for
from .client import WeComClient, WeComError, WeComSendUncertain
from .message_serializers import validate_plain_text
from .message_cards import build_preview_card
from .models import NotificationPreviewAttempt, NotificationRule, WeComBinding, WeComConfig
from .notification_catalog import get_event
from .notification_preview_selectors import schema_ready
from .notification_selectors import rule_etag
from .notification_services import _hash, _lock_key
from .selectors import config_etag, configuration_complete
from .services import _locked_employee_and_user, require_etag


PREVIEW_SALT = "wecom.notification-preview.v1"
PREVIEW_SECONDS = 600


def require_preview_manager(request):
    if not can_manage(request.user, "access_control.manage_notifications"):
        raise PermissionDenied("需要业务通知规则管理权限。")
    return require_wecom_manager(request)


def require_preview_schema():
    if not schema_ready():
        raise Conflict("预览试发尚未启用，请联系管理员完成数据库升级。")


def signed_preview(request, event_code, draft, source_etag, preview):
    actor = active_employee_for(request.user)
    message_type, card, blocked_reason = "template_card", None, ""
    config = WeComConfig.objects.first()
    try:
        card = build_preview_card(preview["title"], preview["body"], config.erp_origin + "/" if config else "")
    except ValueError as exc:
        blocked_reason = str(exc)
    payload = {"actor": str(actor.pk), "event": event_code, "preview_id": str(uuid4()),
               "rule_etag": source_etag, "catalog_hash": _hash(get_event(event_code)),
               "draft_hash": _hash(draft), "title": preview["title"], "body": preview["body"],
               "message_type": message_type, "template_card": card}
    return {**preview, "message_type": message_type, "template_card": card,
            "send_blocked_reason": blocked_reason,
            "preview_token": signing.dumps(payload, salt=PREVIEW_SALT, compress=True),
            "preview_id": payload["preview_id"],
            "expires_at": (timezone.now() + timedelta(seconds=PREVIEW_SECONDS)).isoformat()}


def _decode(token, *, max_age=None):
    try:
        return signing.loads(token, salt=PREVIEW_SALT, max_age=max_age)
    except signing.SignatureExpired:
        raise ValidationError({"preview_token": "预览已过期，请重新生成预览。"}) from None
    except signing.BadSignature:
        raise ValidationError({"preview_token": "预览凭证无效，请重新生成预览。"}) from None


def _audit(request, attempt):
    # 审计只记录状态与尝试ID，不复制预览正文或企微身份凭据。
    write_audit_log(object_type="WECOM_NOTIFICATION_PREVIEW", object_id=attempt.pk,
        action="PREVIEW_" + attempt.status, actor_employee=attempt.requested_by_employee,
        after_data={"preview_id": str(attempt.preview_id), "event_code": attempt.event_code,
                    "status": attempt.status, "error_code": attempt.error_code}, request=request)


@sensitive_variables()
def prepare_attempt(request, event_code, data):
    actor = require_preview_manager(request)
    require_preview_schema()
    payload = _decode(data["preview_token"])
    if payload["actor"] != str(actor.pk) or payload["event"] != event_code:
        raise PermissionDenied("该预览不属于当前操作者或事件。")
    if _hash(data["draft"]) != payload["draft_hash"]:
        raise Conflict("内容已修改，请重新生成预览后发送。")
    request_hash = _hash([data["preview_token"], str(data["binding_id"]), data["config_etag"]])
    with transaction.atomic():
        _lock_key("notification-preview:" + payload["preview_id"])
        existing = NotificationPreviewAttempt.objects.filter(preview_id=payload["preview_id"]).first()
        if existing:
            if existing.requested_by_employee_id != actor.pk or existing.request_hash != request_hash:
                raise Conflict("本次预览已用于其他接收人或配置，请查询原发送结果。")
            return existing, None, None
        _decode(data["preview_token"], max_age=PREVIEW_SECONDS)
        if payload["catalog_hash"] != _hash(get_event(event_code)):
            raise Conflict("通知事件定义已变化，请重新生成预览。")
        _lock_key("notification-rule:" + event_code)
        rule = NotificationRule.objects.filter(event_code=event_code).first()
        require_etag(payload["rule_etag"], rule_etag(rule))
        config = WeComConfig.objects.select_for_update().first()
        if config is None or not config.enabled or not configuration_complete(config):
            raise Conflict("请先配置并启用企业微信应用。")
        require_etag(data["config_etag"], config_etag(config))
        binding = get_object_or_404(WeComBinding.objects.select_for_update(), pk=data["binding_id"])
        employee, user = _locked_employee_and_user(binding.employee_id)
        if (binding.corp_id != config.corp_id or employee.status != "ACTIVE" or employee.archived_at is not None
                or user is None or not user.is_active):
            raise Conflict("接收人的绑定、员工或账号状态已变化，请重新选择。")
        content = f'{payload["title"]}\n\n{payload["body"]}'
        validate_plain_text(payload["title"])
        validate_plain_text(payload["body"])
        if len(payload["title"]) > 200 or len(content.encode("utf-8")) > 2048:
            raise ValidationError({"preview_token": "预览内容超过消息长度限制。"})
        if payload.get("message_type") != "template_card":
            raise Conflict("试发样式已更新，请重新生成卡片预览。")
        try:
            current_card = build_preview_card(payload["title"], payload["body"], config.erp_origin + "/")
        except ValueError as exc:
            raise ValidationError({"preview_token": str(exc)}) from None
        card = payload.get("template_card")
        if card != current_card:
            raise Conflict("卡片内容或 ERP 地址已变化，请重新生成预览。")
        payload_hash = _hash([config.corp_id, config.agent_id, binding.user_id.lower(), "template_card", card])
        # 配置行锁串行化同应用的首发检查，不会在持锁时调用网络。
        pending = NotificationPreviewAttempt.objects.filter(payload_hash=payload_hash, status__in=["PROCESSING", "UNCERTAIN"]).first()
        if pending and pending.requested_by_employee_id == actor.pk:
            # 关闭弹窗后以同样内容重新操作，只找回本人的原尝试，不再次外发。
            return pending, None, None
        if pending:
            raise Conflict("相同消息仍在处理中或结果待核对，请勿重复发送。")
        client = WeComClient(config)
        attempt = NotificationPreviewAttempt.objects.create(preview_id=payload["preview_id"], event_code=event_code,
            requested_by_employee=actor, binding=binding, request_hash=request_hash, payload_hash=payload_hash,
            recipient_name=employee.display_name, corp_id=config.corp_id, agent_id=config.agent_id,
            user_id=binding.user_id, rendered_title=payload["title"], rendered_body=payload["body"])
        _audit(request, attempt)
    return attempt, client, card


@sensitive_variables()
def send_preview(request, event_code, data):
    if connection.in_atomic_block:
        raise RuntimeError("预览外发只能在数据库事务外执行。")
    attempt, client, card = prepare_attempt(request, event_code, data)
    if client is None:
        return attempt
    status, msgid, error_code = "ACCEPTED", "", ""
    try:
        result = client.send_text_notice(attempt.user_id, title=card["main_title"]["title"],
            body=card["sub_title_text"], url=card["card_action"]["url"])
        msgid = result["msgid"]
    except WeComSendUncertain:
        status, error_code = "UNCERTAIN", "SEND_UNCERTAIN"
    except WeComError as exc:
        status, error_code = "FAILED", exc.code
    try:
        with transaction.atomic():
            attempt = NotificationPreviewAttempt.objects.select_for_update().get(pk=attempt.pk)
            attempt.status, attempt.msgid, attempt.error_code = status, msgid, error_code
            attempt.finished_at = timezone.now()
            attempt.save(update_fields=["status", "msgid", "error_code", "finished_at", "updated_at"])
            _audit(request, attempt)
        return attempt
    except DatabaseError:
        NotificationPreviewAttempt.objects.filter(pk=attempt.pk, status="PROCESSING").update(
            status="UNCERTAIN", error_code="LOCAL_SAVE_FAILED", finished_at=timezone.now())
        raise
