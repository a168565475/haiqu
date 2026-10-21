import hashlib
import json

from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404

from apps.access_control.management_permissions import require_wecom_manager as require_manager
from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired, require_matching_etag
from apps.core.api.exceptions import Conflict
from .client import WeComClient, WeComError, WeComSendUncertain
from .message_selectors import STATUS_MESSAGES, template_etag
from .message_serializers import TEMPLATE_VARIABLE
from .models import WeComBinding, WeComConfig, WeComMessageAttempt, WeComMessageTemplate
from .selectors import configuration_complete
from .services import _constraint_name, _locked_employee_and_user, audit, require_etag


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


@transaction.atomic
def update_template(request, data):
    actor = require_manager(request)
    template = WeComMessageTemplate.objects.select_for_update().first()
    require_etag(request.headers.get("If-Match"), template_etag(template))
    before = {"name": template.name, "body": template.body} if template else None
    template = template or WeComMessageTemplate()
    template.name, template.body, template.updated_by_employee = data["name"], data["body"], actor
    try:
        with transaction.atomic():
            template.save()
    except IntegrityError as exc:
        if _constraint_name(exc) == "wecom_msg_template_singleton_uniq":
            raise PreconditionFailed() from None
        raise
    audit(request, template, "MESSAGE_TEMPLATE_UPDATE", actor=actor, before=before,
          after={"name": template.name, "body": template.body}, message="已保存企业微信通用消息模板。")
    return template


def _existing_attempt(key, request_hash):
    attempt = WeComMessageAttempt.objects.filter(idempotency_key=key).first()
    if attempt and attempt.request_hash != request_hash:
        raise Conflict("本次请求标识已用于其他内容，请刷新发送记录后重新操作。")
    return attempt


@sensitive_variables()
def _prepare_attempt(request, data):
    actor = require_manager(request)
    etag = request.headers.get("If-Match")
    if not etag:
        raise PreconditionRequired()
    request_hash = _hash([str(data["binding_id"]), data["message_content"], etag])
    attempt = _existing_attempt(data["idempotency_key"], request_hash)
    if attempt:
        return attempt, None
    with transaction.atomic():
        # 配置行使并发首尝试串行；仅持有短事务，外部发送在提交记录后执行。
        config = WeComConfig.objects.select_for_update().first()
        if config is None or not configuration_complete(config):
            raise Conflict("请先保存可用的企业微信应用配置。")
        template = WeComMessageTemplate.objects.select_for_update().first()
        attempt = _existing_attempt(data["idempotency_key"], request_hash)
        if attempt:
            return attempt, None
        if template is None:
            raise Conflict("请先保存通用消息模板，再发送测试消息。")
        require_matching_etag(request, template)
        binding = get_object_or_404(WeComBinding.objects.select_for_update(), pk=data["binding_id"])
        employee, user = _locked_employee_and_user(binding.employee_id)
        if (binding.corp_id != config.corp_id or employee.status != "ACTIVE" or employee.archived_at is not None
                or user is None or not user.is_active):
            raise Conflict("接收人的企业微信绑定、员工或账号状态不可用。")
        values = {"接收人": employee.display_name, "消息内容": data["message_content"],
                  "发送时间": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S"), "系统地址": config.erp_origin}
        # 单次替换，用户填写的消息内容不会被再次解释为模板变量。
        body = TEMPLATE_VARIABLE.sub(lambda match: values[match.group(1)], template.body)
        if not body.strip() or len(body.encode("utf-8")) > 2048:
            raise ValidationError({"message_content": "替换变量后的完整正文不能超过 2048 个 UTF-8 字节。"})
        payload_hash = _hash([config.corp_id, config.agent_id, binding.user_id.lower(), employee.display_name,
                              template.body, data["message_content"], config.erp_origin])
        if WeComMessageAttempt.objects.filter(payload_hash=payload_hash, status__in=["PROCESSING", "UNCERTAIN"]).exists():
            raise Conflict("相同消息仍在处理中或结果待核对，请查看原发送记录，勿重复发送。")
        client = WeComClient(config)
        attempt = WeComMessageAttempt.objects.create(template=template, binding=binding, requested_by_employee=actor,
            idempotency_key=data["idempotency_key"], request_hash=request_hash, payload_hash=payload_hash,
            template_name=template.name, recipient_name=employee.display_name, corp_id=config.corp_id,
            agent_id=config.agent_id, user_id=binding.user_id, rendered_body=body)
        audit(request, attempt, "MESSAGE_PROCESSING", actor=actor, user_id=attempt.user_id,
              employee_name=attempt.recipient_name, result="PROCESSING", message=STATUS_MESSAGES["PROCESSING"])
    return attempt, client


@transaction.atomic
def finish_attempt(request, attempt, status, *, msgid="", error_code=""):
    attempt = WeComMessageAttempt.objects.select_for_update().get(pk=attempt.pk)
    attempt.status, attempt.msgid, attempt.error_code = status, msgid, error_code
    attempt.finished_at = timezone.now()
    attempt.save(update_fields=["status", "msgid", "error_code", "finished_at", "updated_at"])
    audit(request, attempt, "MESSAGE_" + status, actor=attempt.requested_by_employee, user_id=attempt.user_id,
          employee_name=attempt.recipient_name, result=status, message=STATUS_MESSAGES[status])
    return attempt


@sensitive_variables()
def send_test_message(request, data):
    attempt, client = _prepare_attempt(request, data)
    if client is None:
        return attempt
    status, msgid, error_code = "ACCEPTED", "", ""
    try:
        result = client.send_text(attempt.user_id, attempt.rendered_body)
        msgid = result["msgid"]
    except WeComSendUncertain:
        status, error_code = "UNCERTAIN", "SEND_UNCERTAIN"
    except WeComError as exc:
        status, error_code = "FAILED", exc.code
    try:
        return finish_attempt(request, attempt, status, msgid=msgid, error_code=error_code)
    except DatabaseError:
        # 接口可能已经接受消息；记录失败不能触发第二次发送，且保留原数据库错误。
        WeComMessageAttempt.objects.filter(pk=attempt.pk, status="PROCESSING").update(
            status="UNCERTAIN", error_code="LOCAL_SAVE_FAILED", finished_at=timezone.now())
        raise
