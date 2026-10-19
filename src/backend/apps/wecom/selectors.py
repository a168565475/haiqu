from urllib.parse import urlsplit

from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Exists, OuterRef, Q
from django.views.decorators.debug import sensitive_variables

from apps.access_control.selectors import current_assignments
from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee
from .credentials import CredentialError, decrypt_secret, encryption_ready
from .models import WeComBinding, WeComConfig


def schema_is_ready():
    # 新代码会先进入开发容器；未执行本模块迁移时，保留原账号的登录行为。
    return MigrationRecorder.Migration.objects.filter(app="wecom", name="0001_initial").exists()


def waiting_for_role(user):
    if not user or not user.is_authenticated or not schema_is_ready():
        return False
    employee = Employee.objects.filter(user_id=user.pk, wecom_binding__created_account=True).first()
    return bool(employee and not current_assignments(employee).exists())


def get_config():
    return WeComConfig.objects.first() or WeComConfig()


def config_etag(config):
    return '"wecom-unconfigured"' if config._state.adding else etag_for_instance(config)


def configuration_complete(config):
    if not (config.corp_id and config.agent_id and config.erp_origin and config.secret_ciphertext and encryption_ready()):
        return False
    try:
        return bool(decrypt_secret(config.secret_ciphertext))
    except CredentialError:
        return False


def config_snapshot(config):
    """仅保存配置状态的审计快照，不包含明文或密文。"""
    return {
        "corp_id": config.corp_id, "agent_id": config.agent_id, "erp_origin": config.erp_origin,
        "enabled": config.enabled, "has_secret": bool(config.secret_ciphertext),
        "has_callback_token": bool(config.callback_token_ciphertext),
        "has_callback_aes_key": bool(config.callback_aes_key_ciphertext),
        "encryption_ready": encryption_ready(), "configuration_complete": configuration_complete(config),
        "last_check_status": config.last_check_status, "last_check_message": config.last_check_message,
        "last_checked_at": config.last_checked_at,
        "login_url": config.erp_origin + "/api/auth/wecom/start/",
        "callback_url": config.erp_origin + "/api/auth/wecom/callback/",
        "trusted_domain": urlsplit(config.erp_origin).netloc,
    }


@sensitive_variables()
def config_payload(config):
    """仅供已通过管理员权限校验的配置响应使用。"""
    payload = {**config_snapshot(config), "credential_read_errors": []}
    for field in ("secret", "callback_token", "callback_aes_key"):
        ciphertext = getattr(config, field + "_ciphertext")
        try:
            payload[field] = decrypt_secret(ciphertext) if ciphertext else ""
        except CredentialError:
            payload[field] = None
            payload["credential_read_errors"].append(field)
    return payload


def bindings_queryset(search="", status=""):
    roles = current_assignments(OuterRef("employee_id"))
    queryset = WeComBinding.objects.select_related("employee__user").annotate(has_role=Exists(roles))
    active = Q(employee__status="ACTIVE", employee__archived_at__isnull=True, employee__user__is_active=True)
    waiting = Q(created_account=True, has_role=False)
    if status == "inactive":
        queryset = queryset.exclude(active)
    elif status == "waiting":
        queryset = queryset.filter(active & waiting)
    elif status == "active":
        queryset = queryset.filter(active).exclude(waiting)
    if search:
        queryset = queryset.filter(Q(user_id__icontains=search) | Q(member_name__icontains=search)
                                   | Q(employee__display_name__icontains=search) | Q(employee__employee_code__icontains=search))
    return queryset


def binding_payload(binding):
    employee, user = binding.employee, binding.employee.user
    inactive = employee.status != "ACTIVE" or employee.archived_at is not None or user is None or not user.is_active
    has_role = binding.has_role if hasattr(binding, "has_role") else current_assignments(employee).exists()
    role_status = "inactive" if inactive else "waiting" if binding.created_account and not has_role else "active"
    return {
        "id": binding.pk, "user_id": binding.user_id, "member_name": binding.member_name,
        "employee_id": employee.pk, "employee_code": employee.employee_code, "employee_name": employee.display_name,
        "username": user.get_username() if user else "", "role_status": role_status,
        "source": binding.source, "created_at": binding.created_at,
    }


def employee_options(search=""):
    queryset = Employee.objects.filter(status="ACTIVE", archived_at__isnull=True, wecom_binding__isnull=True).filter(
        Q(user__isnull=True) | Q(user__is_active=True)).select_related("user")
    if search:
        queryset = queryset.filter(Q(employee_code__icontains=search) | Q(display_name__icontains=search) | Q(user__username__icontains=search))
    return [{"id": employee.pk, "employee_code": employee.employee_code, "display_name": employee.display_name,
             "username": employee.user.get_username() if employee.user_id else "", "etag": etag_for_instance(employee)}
            for employee in queryset[:50]]


def audits_queryset():
    return AuditLog.objects.filter(object_type="WECOM").order_by("-occurred_at", "-id")


def audit_payload(audit):
    return {"id": audit.pk, "occurred_at": audit.occurred_at, "actor_name": audit.actor_name_snapshot,
            "action": audit.action, "user_id": audit.after_data.get("user_id", ""),
            "employee_name": audit.after_data.get("employee_name", ""),
            "result": audit.after_data.get("result", "SUCCESS"), "message": audit.after_data.get("message", "")}
