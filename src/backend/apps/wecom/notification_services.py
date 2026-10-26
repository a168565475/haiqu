import hashlib
import json
from collections import OrderedDict
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404

from apps.access_control.management_permissions import can_manage
from apps.access_control.selectors import effective_access
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.auth import active_employee_for
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from .client import WeComClient, WeComError, WeComSendUncertain
from .message_serializers import validate_plain_text
from .models import NotificationDelivery, NotificationEvent, NotificationRecipient, NotificationRule, WeComBinding, WeComConfig
from .notification_access import EVENT_OBJECT_PERMISSIONS, UNAVAILABLE_EVENT_OBJECTS, event_object_accessible, plan_workshop_ids
from .notification_catalog import RECIPIENT_SCOPES, VARIABLE, current_body_template, get_event, target_for
from .notification_selectors import rule_etag, rule_warnings
from .selectors import configuration_complete
from .services import require_etag


RULE_FIELDS = ("name", "title_template", "body_template", "recipient_role_codes", "recipient_scope", "enabled")


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _lock_key(key):
    # PostgreSQL事务锁覆盖尚未创建的键，事务结束自动释放。
    lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])


def _template_names(text, allowed):
    validate_plain_text(text)
    names = set(VARIABLE.findall(text))
    remainder = VARIABLE.sub("", text)
    if "{" in remainder or "}" in remainder:
        raise ValidationError({"template": "模板变量格式无效，请使用 {{变量名}}。"})
    unknown = sorted(names - set(allowed))
    if unknown:
        raise ValidationError({"template": f"模板包含未允许的变量：{', '.join(unknown)}。"})
    return names


def _render(text, allowed, context):
    names = _template_names(text, allowed)
    if any(name not in context or context[name] is None or str(context[name]).strip() == "" for name in names):
        raise ValidationError({"context": "事件缺少模板变量或变量为空。"})
    return VARIABLE.sub(lambda match: str(context[match.group(1)]), text)


def _validate_rule(event, data):
    validate_plain_text(data["name"])
    if len(data["name"]) > 100 or len(data["title_template"]) > 200 or len(data["body_template"]) > 8192:
        raise ValidationError({"template": "模板长度超出限制。"})
    if data["recipient_scope"] not in event["supported_scopes"]:
        raise ValidationError({"recipient_scope": "该事件不支持所选接收范围。"})
    codes = list(data["recipient_role_codes"])
    if len(codes) != len(set(codes)):
        raise ValidationError({"recipient_role_codes": "接收角色不可重复。"})
    if RoleProfile.objects.filter(role_code__in=codes, archived_at__isnull=True).count() != len(codes):
        raise ValidationError({"recipient_role_codes": "包含不存在或已停用角色。"})
    if data["enabled"] and not codes:
        raise ValidationError({"recipient_role_codes": "启用规则必须至少选择一个接收角色。"})
    if data["enabled"] and event["event_code"] == "SUPPLIER_PURCHASE_SHEET_PUBLISHED":
        raise ValidationError({"enabled": "供应商采购表发布已确定不通知，不能启用。"})
    names = _template_names(data["title_template"], event["allowed_variables"])
    names |= _template_names(data["body_template"], event["allowed_variables"])
    missing = sorted(set(event["required_variables"]) - names)
    if missing:
        raise ValidationError({"template": f"模板缺少必要变量：{', '.join(missing)}。"})
    minimum_title = VARIABLE.sub("x", data["title_template"])
    minimum_body = VARIABLE.sub("x", data["body_template"])
    if len(f"{minimum_title}\n\n{minimum_body}".encode()) > 2048:
        raise ValidationError({"template": "模板固定文字已超过企业微信2048字节上限，请缩短后保存。"})


@transaction.atomic
def update_rule(request, event_code, data):
    if not can_manage(request.user, "access_control.manage_notifications"):
        raise PermissionDenied("需要业务通知规则管理权限。")
    actor = active_employee_for(request.user)
    event = get_event(event_code)
    _lock_key("notification-rule:" + event_code)
    rule = NotificationRule.objects.select_for_update().filter(event_code=event_code).first()
    require_etag(request.headers.get("If-Match"), rule_etag(rule))
    _validate_rule(event, data)
    before = {**{field: getattr(rule, field) for field in RULE_FIELDS}, "version": rule.version} if rule else None
    if rule is None:
        rule = NotificationRule(event_code=event_code, version=1)
    else:
        rule.version += 1
    for field in RULE_FIELDS:
        setattr(rule, field, data[field])
    rule.allowed_variables = event["allowed_variables"]
    rule.updated_by_employee = actor
    rule.save()
    write_audit_log(object_type="WECOM_NOTIFICATION", object_id=rule.pk, action="RULE_UPDATE",
        actor_employee=actor, before_data=before,
        after_data={**{field: getattr(rule, field) for field in RULE_FIELDS}, "version": rule.version}, request=request)
    return rule


def preview_rule(event_code, data, variables):
    event = get_event(event_code)
    _validate_rule(event, data)
    if set(variables) - set(event["allowed_variables"]):
        raise ValidationError({"variables": "示例变量不在该事件允许清单中。"})
    variables = _validated_context(event, variables)
    title = _render(data["title_template"], event["allowed_variables"], variables)
    body = _render(current_body_template(event_code, data["body_template"]), event["allowed_variables"], variables)
    if len(title) > 200 or len(f"{title}\n\n{body}".encode()) > 2048:
        raise ValidationError({"template": "完整企业微信消息不能超过2048个UTF-8字节。"})
    return {"event_code": event_code, "title": title, "body": body,
        "recipient_scope": data["recipient_scope"], "scope_label": RECIPIENT_SCOPES[data["recipient_scope"]],
        "recipient_role_codes": list(data["recipient_role_codes"]), "will_send": False,
        "warnings": rule_warnings(event_code, data["recipient_role_codes"]),
        "recipient_note": "仅预览范围；实际接收人须结合真实业务对象及当前授权解析，不代表已找到接收人。"}


def _eligible_employees(event, rule, context, object_id, *, employee_id=None):
    now = timezone.now()
    workshop_ids = set()
    if rule.recipient_scope == "WORKSHOP":
        workshop_ids = (plan_workshop_ids(object_id) if event["event_code"] == "PRODUCTION_PLAN_CREATED"
                        else {str(context["workshop_id"])} if context.get("workshop_id") else set())
    assignments = EmployeeRoleAssignment.objects.filter(
        role_profile__role_code__in=rule.recipient_role_codes, role_profile__archived_at__isnull=True,
        employee__status="ACTIVE", employee__archived_at__isnull=True, employee__user__is_active=True,
        effective_from__lte=now,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now)).select_related("employee__user", "role_profile")
    if employee_id:
        assignments = assignments.filter(employee_id=employee_id)
    candidates = OrderedDict()
    for assignment in assignments:
        employee = assignment.employee
        candidates.setdefault(employee.pk, {"employee": employee, "roles": []})["roles"].append(assignment.role_profile.role_code)
    # 超级管理员也可能是实际提交人；回执只给该人，不扩展按角色发送的范围。
    submitter_id = context.get("submitter_id")
    if rule.recipient_scope == "SUBMITTER" and submitter_id and (
        employee_id is None or str(employee_id) == str(submitter_id)
    ):
        submitter = Employee.objects.select_related("user").filter(
            pk=submitter_id, status="ACTIVE", archived_at__isnull=True,
            user__is_active=True, user__is_superuser=True,
        ).first()
        if submitter is not None:
            candidates.setdefault(submitter.pk, {"employee": submitter, "roles": []})
    selected = []
    # 同一次解析中按员工检查一次，仍保留该员工全部命中的接收角色。
    for item in candidates.values():
        employee = item["employee"]
        if rule.recipient_scope == "SUBMITTER" and str(employee.pk) != str(context.get("submitter_id") or ""):
            continue
        if rule.recipient_scope == "WORKSHOP":
            if not workshop_ids:
                continue
            access = effective_access(employee.user)
            allowed = False
            for code in EVENT_OBJECT_PERMISSIONS[event["event_code"]]:
                entry = access["actions"].get(code, {})
                allowed |= bool(set(entry.get("scopes", [])) & {"MODULE", "ALL"} or any(
                    source.get("scope") == "WORKSHOP" and workshop_ids.intersection(source.get("resource_ids", []))
                    for source in entry.get("sources", [])
                ))
            if not allowed:
                continue
        if not event_object_accessible(event["event_code"], object_id, employee.user,
                                       object_version=context.get("object_version")):
            continue
        selected.append(item)
    return selected


def _validated_context(event, context):
    if not isinstance(context, dict):
        raise ValidationError({"context": "业务事件上下文必须是对象。"})
    allowed = set(event["allowed_variables"]) | {"submitter_id", "workshop_id"}
    if event["event_code"] == "PRODUCTION_TASK_BOMS_CONFIRMED":
        allowed.add("bom_versions")
    if set(context) - allowed:
        raise ValidationError({"context": "事件上下文包含未登记字段。"})
    values = {}
    for key, value in context.items():
        if key == "bom_versions":
            from apps.boms.notification_events import validated_bom_snapshot
            values[key] = validated_bom_snapshot(value)
            continue
        if not isinstance(value, (str, int, float, UUID)) or isinstance(value, bool):
            raise ValidationError({"context": "事件变量必须是文本、数字或UUID。"})
        text = str(value)
        if len(text) > 2000:
            raise ValidationError({"context": "事件变量过长。"})
        if text:
            validate_plain_text(text)
        if key.endswith("_id"):
            try:
                text = str(UUID(text))
            except ValueError:
                raise ValidationError({"context": "关系ID必须是有效UUID。"}) from None
        values[key] = text
    return values


@transaction.atomic
def register_business_event(*, event_code, idempotency_key, object_type, object_id=None, object_version="", context=None):
    """业务成功事务内登记；只落库，不触发外部发送。调用方传入后端业务事实。"""
    event = get_event(event_code)
    if not isinstance(idempotency_key, (str, UUID)) or not isinstance(object_type, str) or not isinstance(object_version, (str, int)):
        raise ValidationError("事件键、对象类型或版本格式无效。")
    key = str(idempotency_key)
    if not key.strip() or len(key) > 180 or not object_type.strip() or len(object_type) > 100 or len(str(object_version)) > 80:
        raise ValidationError("事件键、对象类型或版本无效。")
    try:
        object_id = str(UUID(str(object_id)))
    except (TypeError, ValueError):
        raise ValidationError("事件必须引用真实业务对象UUID。") from None
    context = _validated_context(event, context or {})
    if "object_version" in context and context["object_version"] != str(object_version):
        raise ValidationError({"context": "模板对象版本与事件版本不一致。"})
    context["object_version"] = str(object_version)
    request_hash = _hash([event_code, object_type, object_id, str(object_version), context])
    _lock_key("notification-event:" + key)
    existing = NotificationEvent.objects.filter(idempotency_key=key).first()
    if existing:
        if existing.context.get("_request_hash") != request_hash:
            raise Conflict("同一业务事件键已用于不同对象、版本或内容。")
        return existing
    if event_code == "PRODUCTION_TASK_BOMS_CONFIRMED":
        from apps.boms.notification_events import current_task_bom_snapshot, snapshot_version
        actual = current_task_bom_snapshot(object_id)
        if (actual is None or actual != context.get("bom_versions") or snapshot_version(actual) != str(object_version)
                or context.get("product_count") != str(len(actual)) or object_type != "production_tasks.ProductionTask"):
            raise Conflict("任务最新BOM确认组合已变化，请刷新后重试。")
    from apps.samples.notification_events import SAMPLE_EVENTS, current_sample_object, sample_for_event
    if event_code in SAMPLE_EVENTS:
        obj = current_sample_object(event_code, object_id, object_version)
        if obj is None or object_type != obj._meta.label:
            raise Conflict("打样事件对象、状态或版本已变化，请刷新后重试。")
        sample, _ = sample_for_event(event_code, object_id)
        actual_submitter = str(sample.requested_by_employee_id) if sample.requested_by_employee_id else None
        if context.get('submitter_id') != actual_submitter:
            raise Conflict("打样事件必须使用本单真实原申请人关系。")
    from apps.inventory.notification_events import INVENTORY_EVENTS, current_inventory_object, inventory_event_submitter_id
    if event_code in INVENTORY_EVENTS:
        obj = current_inventory_object(event_code, object_id, object_version)
        if obj is None or object_type != obj._meta.label:
            raise Conflict("入出库事件必须引用当前真实成功单据及对应版本。")
        if event_code in {"INTERNAL_SEMI_RECEIPT_CONFIRMED", "ASSEMBLY_FINISHED_RECEIPT_CONFIRMED"}:
            actual_submitter = inventory_event_submitter_id(event_code, obj)
            if context.get("submitter_id") != actual_submitter:
                raise Conflict("入库完成通知必须使用原提交人关系。")
    context["_request_hash"] = request_hash
    rule = NotificationRule.objects.filter(event_code=event_code).first()
    recipients = []
    title, body = "", ""
    if rule is None:
        status = "CONFIG_MISSING"
    elif not rule.enabled:
        status = "DISABLED"
    elif event_code in UNAVAILABLE_EVENT_OBJECTS:
        status = "NOT_READY"
    else:
        title = _render(rule.title_template, event["allowed_variables"], context)
        body = _render(current_body_template(event_code, rule.body_template), event["allowed_variables"], context)
        if len(title) > 200 or len(f"{title}\n\n{body}".encode()) > 2048:
            raise ValidationError("渲染后的完整消息超出标题或企业微信2048字节限制。")
        recipients = _eligible_employees(event, rule, context, object_id)
        status = "CREATED" if recipients else "NO_RECIPIENT"
    notification = NotificationEvent.objects.create(
        event_code=event_code, idempotency_key=key, object_type=object_type, object_id=object_id,
        object_version=str(object_version), context=context, rule_version=rule.version if rule else 0,
        template_name=rule.name if rule else "", rendered_title=title, rendered_body=body,
        target=target_for(event_code, object_id), status=status,
    )
    config = WeComConfig.objects.first()
    bindings = dict(WeComBinding.objects.filter(
        employee_id__in=[item["employee"].pk for item in recipients],
    ).order_by().values_list("employee_id", "user_id")) if recipients else {}
    recipient_rows = []
    for item in recipients:
        employee = item["employee"]
        recipient_rows.append(NotificationRecipient(
            event=notification, employee=employee, employee_name=employee.display_name,
            role_codes=sorted(set(item["roles"])), scope=rule.recipient_scope,
            eligibility_snapshot={"required_permissions": list(EVENT_OBJECT_PERMISSIONS[event_code]),
                                  "corp_id": config.corp_id if config else "", "agent_id": config.agent_id if config else ""},
        ))
    # UUID 在构造时生成；两类批量写入仍由外层事件事务保证全部成功或回滚。
    NotificationRecipient.objects.bulk_create(recipient_rows, batch_size=500)
    deliveries = []
    for recipient in recipient_rows:
        employee = recipient.employee
        deliveries.append(NotificationDelivery(recipient=recipient, channel="IN_APP",
            idempotency_key=f"{notification.pk}:{employee.pk}:IN_APP", status="ACCEPTED", finished_at=timezone.now()))
        admin_in_app_only = _admin_uses_in_app_only(employee)
        deliveries.append(NotificationDelivery(recipient=recipient, channel="WECOM",
            idempotency_key=f"{notification.pk}:{employee.pk}:WECOM", user_id_snapshot=bindings.get(employee.pk, ""),
            status="SKIPPED" if admin_in_app_only else "PENDING",
            error_code="ADMIN_IN_APP_ONLY" if admin_in_app_only else "",
            finished_at=timezone.now() if admin_in_app_only else None))
    NotificationDelivery.objects.bulk_create(deliveries, batch_size=500)
    return notification


def _admin_uses_in_app_only(employee):
    return employee.user.is_superuser and employee.user.get_username() == "admin"


def _fail_delivery(delivery, code):
    delivery.status, delivery.error_code, delivery.finished_at = "FAILED", code, timezone.now()
    delivery.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
    return delivery


def process_delivery(delivery, *, allow_uncertain=False, allow_failed=False, defer_unconfigured=False):
    if connection.in_atomic_block:
        raise RuntimeError("外部通知只能在业务事务提交后执行。")
    allowed = {"PENDING"} | ({"UNCERTAIN"} if allow_uncertain else set()) | ({"FAILED"} if allow_failed else set())
    with transaction.atomic():
        locked = NotificationDelivery.objects.select_for_update().select_related("recipient__event").get(pk=delivery.pk)
        if locked.attempt_count != delivery.attempt_count:
            return locked
        if locked.channel != "WECOM" or locked.status not in allowed:
            return locked
        recipient, event = locked.recipient, locked.recipient.event
        if event.status == "STALE":
            return _fail_delivery(locked, "EVENT_STALE")
        employee = Employee.objects.select_related("user").filter(pk=recipient.employee_id,
            status="ACTIVE", archived_at__isnull=True, user__is_active=True).first()
        if employee is None:
            return _fail_delivery(locked, "RECIPIENT_INACTIVE")
        snapshot = SimpleNamespace(recipient_role_codes=recipient.role_codes, recipient_scope=recipient.scope)
        if not _eligible_employees(get_event(event.event_code), snapshot, event.context, event.object_id, employee_id=employee.pk):
            return _fail_delivery(locked, "RECIPIENT_NOT_ELIGIBLE")
        if _admin_uses_in_app_only(employee):
            locked.status, locked.error_code, locked.finished_at = "SKIPPED", "ADMIN_IN_APP_ONLY", timezone.now()
            locked.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
            return locked
        binding = WeComBinding.objects.filter(employee=employee).first()
        if binding is None:
            return _fail_delivery(locked, "NO_WECOM_BINDING")
        config = WeComConfig.objects.first()
        if config is None or not config.enabled or not configuration_complete(config):
            # 常驻进程等待管理员补齐配置；不把尚未尝试发送的正常队列转成失败。
            if defer_unconfigured and locked.status == "PENDING":
                return locked
            return _fail_delivery(locked, "CONFIGURATION_ERROR")
        if binding.corp_id != config.corp_id:
            return _fail_delivery(locked, "CORPORATION_MISMATCH")
        original = recipient.eligibility_snapshot
        if (original.get("corp_id") and original["corp_id"] != config.corp_id
                or original.get("agent_id") and str(original["agent_id"]) != str(config.agent_id)
                or locked.user_id_snapshot and locked.user_id_snapshot != binding.user_id):
            return _fail_delivery(locked, "BINDING_OR_APPLICATION_CHANGED")
        locked.status, locked.error_code = "PROCESSING", ""
        locked.attempt_count += 1
        attempt_number = locked.attempt_count
        locked.last_attempt_at = timezone.now()
        locked.user_id_snapshot = binding.user_id
        locked.save(update_fields=["status", "error_code", "attempt_count", "last_attempt_at", "user_id_snapshot", "updated_at"])
    try:
        body = event.rendered_body
        definition = get_event(event.event_code)
        # 未投递的旧默认快照只调整排版；自定义正文、历史快照及站内记录不重写。
        if all(event.context.get(name) is not None and str(event.context[name]).strip()
               for name in VARIABLE.findall(definition["legacy_default_body"])):
            legacy = _render(definition["legacy_default_body"], definition["allowed_variables"], event.context)
            if body == legacy:
                body = _render(definition["default_body"], definition["allowed_variables"], event.context)
        result = WeComClient(config).send_text_notice(binding.user_id, title=event.rendered_title,
            body=body, url=f"{config.erp_origin}/?notification={recipient.pk}", preview=False)
        status, error_code, msgid = "ACCEPTED", "", result["msgid"]
    except WeComSendUncertain:
        status, error_code, msgid = "UNCERTAIN", "SEND_UNCERTAIN", ""
    except WeComError as exc:
        status, error_code, msgid = "FAILED", exc.code, ""
    with transaction.atomic():
        locked = NotificationDelivery.objects.select_for_update().get(pk=locked.pk)
        # 超时回收之后的迟到响应不会覆盖核对状态。
        if locked.status == "PROCESSING" and locked.attempt_count == attempt_number:
            locked.status, locked.error_code, locked.msgid, locked.finished_at = status, error_code, msgid, timezone.now()
            locked.save(update_fields=["status", "error_code", "msgid", "finished_at", "updated_at"])
    return locked


def recover_abandoned_deliveries():
    """超过五分钟仍PROCESSING只转结果待核对，绝不自动重发。"""
    return NotificationDelivery.objects.filter(channel="WECOM", status="PROCESSING",
        last_attempt_at__lt=timezone.now() - timedelta(minutes=5)).update(
            status="UNCERTAIN", error_code="PROCESS_INTERRUPTED", finished_at=timezone.now(), updated_at=timezone.now())


@transaction.atomic
def mark_read(employee_id, recipient_id):
    recipient = get_object_or_404(NotificationRecipient.objects.select_for_update(), pk=recipient_id, employee_id=employee_id)
    if recipient.read_at is None:
        recipient.read_at = timezone.now()
        recipient.save(update_fields=["read_at", "updated_at"])
    return recipient
