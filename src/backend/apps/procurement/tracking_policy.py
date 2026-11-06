"""采购提醒时间规则；未启用前不读取新表，避免影响现用采购页面。"""
from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import APIException, PermissionDenied

from apps.access_control.management_permissions import can_manage
from apps.core.api.concurrency import require_matching_etag
from apps.core.audit import write_audit_log
from apps.core.auth import active_employee_for

from .tracking_models import PurchaseTrackingPolicy


class PurchaseTrackingPolicyUnavailable(APIException):
    status_code = 503
    default_detail = "采购提醒时间规则尚未启用，请先完成迁移并启用配置。"
    default_code = "purchase_tracking_policy_unavailable"


def require_policy_enabled():
    if not settings.PURCHASE_TRACKING_POLICY_ENABLED:
        raise PurchaseTrackingPolicyUnavailable()


def policy_values(policy):
    return {
        "bom_timeout_days": policy.bom_timeout_days,
        "category_lead_days": dict(policy.category_lead_days),
    }


def get_tracking_policy():
    if not settings.PURCHASE_TRACKING_POLICY_ENABLED:
        return None
    return policy_values(PurchaseTrackingPolicy.objects.get(key="default"))


@transaction.atomic
def update_tracking_policy(request, data):
    require_policy_enabled()
    if not can_manage(request.user, "access_control.manage_notifications"):
        raise PermissionDenied("需要业务通知规则管理权限。")
    policy = PurchaseTrackingPolicy.objects.select_for_update().get(key="default")
    require_matching_etag(request, policy)
    before = policy_values(policy)
    if "bom_timeout_days" in data:
        policy.bom_timeout_days = data["bom_timeout_days"]
    if "category_lead_days" in data:
        policy.category_lead_days = {**policy.category_lead_days, **data["category_lead_days"]}
    policy.updated_by_employee = active_employee_for(request.user)
    policy.full_clean()
    policy.save(update_fields=["bom_timeout_days", "category_lead_days", "updated_by_employee", "updated_at"])
    write_audit_log(
        object_type="PURCHASE_TRACKING_POLICY", object_id=policy.pk, action="RULE_UPDATE",
        actor_employee=policy.updated_by_employee, before_data=before, after_data=policy_values(policy), request=request,
    )
    # 页面查询立即使用新规则；主动提醒由现有常驻扫描读取，避免保存等待全量重算。
    return policy
