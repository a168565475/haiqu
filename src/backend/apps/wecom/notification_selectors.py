from apps.core.api.concurrency import etag_for_instance
from apps.access_control.models import RoleActionGrant
from apps.organizations.models import RoleProfile
from .models import NotificationDelivery, NotificationRecipient, NotificationRule
from .notification_access import EVENT_OBJECT_PERMISSIONS, UNAVAILABLE_EVENT_OBJECTS, event_object_accessible
from .notification_catalog import RECIPIENT_SCOPES, all_events, get_event


def rule_etag(rule):
    return etag_for_instance(rule) if rule else '"notification-rule-unsaved"'


def roles_queryset():
    return RoleProfile.objects.filter(archived_at__isnull=True).order_by("role_code")


def rules_queryset():
    return NotificationRule.objects.order_by("event_code").prefetch_related("updated_by_employee")


def _role_payload(role):
    return {"role_code": role.role_code, "display_name": role.display_name, "archived": role.archived_at is not None}


def rule_warnings(event_code, role_codes):
    if event_code in UNAVAILABLE_EVENT_OBJECTS:
        return [UNAVAILABLE_EVENT_OBJECTS[event_code]]
    required = set(EVENT_OBJECT_PERMISSIONS[event_code])
    warnings = (["旧单BOM事件保留用于兼容；生产确认链请配置“任务BOM全部确认”，不会自动复制旧规则。"]
                if event_code == "BOM_CONFIRMED" else [])
    for code in role_codes:
        grants = RoleActionGrant.objects.filter(role__role_code=code).select_related("permission__content_type")
        actual = {f"{row.permission.content_type.app_label}.{row.permission.codename}" for row in grants}
        if not required & actual:
            warnings.append(f"角色 {code} 没有该事件所需动作授权，角色配置不会自动授予权限。")
    return warnings


def rule_payload(rule):
    event = get_event(rule.event_code)
    roles = list(roles_queryset().filter(role_code__in=rule.recipient_role_codes))
    return {
        "event_code": rule.event_code,
        "display_name": event["display_name"],
        "name": rule.name,
        "title_template": rule.title_template,
        "body_template": rule.body_template,
        "allowed_variables": event["allowed_variables"],
        "required_variables": event["required_variables"],
        "supported_scopes": event["supported_scopes"],
        "scope_labels": RECIPIENT_SCOPES,
        "recipient_role_codes": list(rule.recipient_role_codes),
        "recipient_roles": [_role_payload(role) for role in roles],
        "recipient_scope": rule.recipient_scope,
        "enabled": rule.enabled,
        "version": rule.version,
        "updated_at": rule.updated_at,
        "updated_by": rule.updated_by_employee.display_name if rule.updated_by_employee_id else "",
        "etag": rule_etag(rule),
        "target_key": event["target_key"],
        "warnings": rule_warnings(rule.event_code, rule.recipient_role_codes),
    }


def default_rule_payload(event):
    return {
        "event_code": event["event_code"], "display_name": event["display_name"],
        "name": event["display_name"], "title_template": event["default_title"],
        "body_template": event["default_body"], "allowed_variables": event["allowed_variables"],
        "required_variables": event["required_variables"], "supported_scopes": event["supported_scopes"],
        "scope_labels": RECIPIENT_SCOPES, "recipient_role_codes": event["default_role_codes"],
        "recipient_roles": [], "recipient_scope": event["supported_scopes"][0],
        "enabled": event["enabled_by_default"], "version": 0, "updated_at": None,
        "updated_by": "", "etag": '"notification-rule-unsaved"', "target_key": event["target_key"],
        "warnings": ["尚未保存配置；新事件将记录为配置缺失，保存后才生效。", *rule_warnings(event["event_code"], event["default_role_codes"])],
    }


def all_rule_payloads():
    rules = {rule.event_code: rule for rule in rules_queryset()}
    return [rule_payload(rules[event["event_code"]]) if event["event_code"] in rules else default_rule_payload(event)
            for event in all_events()]


def inbox_queryset(employee_id):
    return NotificationRecipient.objects.filter(employee_id=employee_id).select_related("event").prefetch_related("deliveries").order_by("-created_at", "-id")


def delivery_statuses(recipient):
    return {delivery.channel: {"status": delivery.status, "error_code": delivery.error_code}
            for delivery in recipient.deliveries.all()}


def content_accessible(recipient, user):
    if recipient.event.status == "STALE":
        return False
    return event_object_accessible(recipient.event.event_code, recipient.event.object_id, user,
                                   role_codes=recipient.role_codes, object_version=recipient.event.object_version)


def target_accessible(recipient, user):
    return recipient.event.target is not None and content_accessible(recipient, user)


def recipient_payload(recipient, user):
    accessible = content_accessible(recipient, user)
    event = get_event(recipient.event.event_code)
    if accessible:
        title, body, target = recipient.event.rendered_title, recipient.event.rendered_body, recipient.event.target
    else:
        title, body, target = "通知内容不可访问", "该业务内容当前不可访问。", None
        from .workshop_notifications import WORKSHOP_EVENTS, current_workshop_object
        if recipient.event.event_code in WORKSHOP_EVENTS and current_workshop_object(
            recipient.event.event_code, recipient.event.object_id, recipient.event.object_version,
        ) is None:
            title, body = "通知已过期", "该业务状态、版本或记录已变化，请从业务列表查看当前资料。"
        from .workshop_change_notifications import CHANGE_EVENTS, current_change_object
        if recipient.event.event_code in CHANGE_EVENTS and current_change_object(
            recipient.event.event_code, recipient.event.object_id, recipient.event.object_version,
        ) is None:
            title, body = "通知已过期", "原记录或历史凭证已变化，请查看当前业务记录。"
        if recipient.event.event_code == "PRODUCTION_TASK_BOMS_CONFIRMED":
            from apps.boms.notification_events import bom_event_is_current
            if not bom_event_is_current(recipient.event):
                title, body = "通知已过期", "任务BOM版本或确认状态已变化，请从BOM列表查看当前资料。"
        from apps.samples.notification_events import SAMPLE_EVENTS, current_sample_object
        if recipient.event.event_code in SAMPLE_EVENTS and current_sample_object(
            recipient.event.event_code, recipient.event.object_id, recipient.event.object_version,
        ) is None:
            title, body = "通知已过期", "打样状态、版本或材料可领条件已变化，请查看当前业务资料。"
    return {
        "id": recipient.pk, "event_code": recipient.event.event_code, "event_name": event["display_name"],
        "title": title, "body": body, "created_at": recipient.created_at, "read_at": recipient.read_at,
        "target": target, "target_accessible": accessible and target is not None, "channel_status": delivery_statuses(recipient),
    }


def unread_count(employee_id):
    return NotificationRecipient.objects.filter(employee_id=employee_id, read_at__isnull=True).count()


def delivery_queryset():
    return NotificationDelivery.objects.select_related("recipient__event", "recipient__employee").order_by("created_at")
