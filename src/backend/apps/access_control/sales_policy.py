"""Per-request sales authorization. No session or cross-request grant cache.

Explicit legacy grants retain their existing scope; the role projection in
auth.Group is never mistaken for a second unrestricted legacy grant.
"""
from django.conf import settings
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.organizations.models import Employee
from .catalog import IMPLIED, PERMISSION_CODES
from .models import SalesTeamMembership
from .selectors import effective_access
from .sales_operations import LEGACY_ACTION_PERMISSIONS


FOLLOW_PERMISSION = {child: parent for parent, children in IMPLIED.items() for child in children}


def enabled():
    return bool(getattr(settings, "SALES_ACCESS_ENABLED", False))


def canonical_permission(permission):
    if "." not in permission:
        matches = [code for code in (*PERMISSION_CODES, *FOLLOW_PERMISSION) if code.split(".", 1)[1] == permission]
        if len(set(matches)) != 1:
            return None
        permission = matches[0]
    return FOLLOW_PERMISSION.get(permission, permission)


def access_for(request):
    if not hasattr(request, "_sales_access_snapshot"):
        request._sales_access_snapshot = effective_access(request.user)
    return request._sales_access_snapshot


def legacy_scope_codenames(request, permission):
    original = permission
    canonical = canonical_permission(permission)
    data = access_for(request)
    if not data["active"]:
        return set()
    return {entry["permission"].split(".", 1)[1] for entry in data["legacy_sources"]
        if entry["permission"] in {original, canonical, LEGACY_ACTION_PERMISSIONS.get(canonical)}
        or ("." not in original and entry["permission"].split(".", 1)[1] == original)}


def legacy_permission(request, permission):
    """An independently assigned old permission, not a projected scoped role."""
    return bool(legacy_scope_codenames(request, permission))


def scopes(request, permission):
    permission = canonical_permission(permission)
    data = access_for(request)
    if not data["active"]:
        return frozenset()
    return frozenset(data["actions"].get(permission, {}).get("scopes", []))


def has_permission(request, permission):
    if not enabled():
        return request.user.has_perm(permission)
    data = access_for(request)
    return bool(data["active"] and (data["is_superuser"] or scopes(request, permission) or legacy_permission(request, permission)))


def action_permission(request, view):
    action = getattr(view, "action", None)
    mapping = dict(getattr(view, "action_permission_map", {}))
    if enabled():
        mapping.update(getattr(view, "sales_action_permission_map", {}))
    return mapping.get(f"{action}.{request.method}") or mapping.get(action)


def allowed_owners(request, permission):
    """Returns (all_owners, employee queryset) for this operation only."""
    data = access_for(request)
    # The actor must be active. A data owner's employment status does not erase
    # their records from an existing team; candidate pickers validate separately.
    employees = Employee.objects.all()
    if not data["active"]:
        return False, employees.none()
    granted = scopes(request, permission)
    if data["is_superuser"] or "ALL" in granted:
        return True, employees
    employee = getattr(request, "employee", None)
    if employee is None:
        return False, employees.none()
    permitted = Q(pk__in=[])
    if "OWN" in granted:
        permitted |= Q(pk=employee.pk)
    if "TEAM" in granted:
        members = SalesTeamMembership.objects.filter(
            team__manager=employee, team__is_active=True,
        ).values("employee_id")
        permitted |= Q(pk__in=members)
    return False, employees.filter(permitted)


def require_owner(request, permission, employee, *, field="owner_employee"):
    if not enabled() or legacy_permission(request, permission):
        return
    all_owners, owners = allowed_owners(request, permission)
    if not all_owners and (employee is None or not owners.filter(pk=employee.pk).exists()):
        raise PermissionDenied(f"所选负责人不在此操作允许的范围内（{field}）。")


def can_customer(request, permission, customer_id):
    if not enabled():
        return request.user.has_perm(permission)
    if not has_permission(request, permission):
        return False
    if access_for(request)["is_superuser"] or "MODULE" in scopes(request, permission):
        return True
    from apps.customers.selectors import accessible_customers
    cache = getattr(request, "_sales_customer_ids", None)
    if cache is None:
        cache = request._sales_customer_ids = {}
    if permission not in cache:
        cache[permission] = set(accessible_customers(request, permission).values_list("pk", flat=True))
    return customer_id in cache[permission]


def require_customer(request, permission, customer):
    if enabled() and not can_customer(request, permission, customer.pk):
        raise PermissionDenied("所选客户不在此操作允许的范围内。")


def current_primary_assignments():
    from django.utils import timezone
    from apps.customers.models import CustomerAssignment
    now = timezone.now()
    return CustomerAssignment.objects.filter(
        assignment_role="PRIMARY_OWNER", effective_from__lte=now,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))


def primary_owner(customer):
    assignment = current_primary_assignments().filter(customer_account=customer).select_related("employee").first()
    return assignment.employee if assignment else None


def validate_document_owner(request, customer, owner, previous_owner=None):
    if not enabled() or (previous_owner is not None and owner == previous_owner):
        return
    expected = primary_owner(customer)
    if expected is None or owner is None or owner.pk != expected.pk:
        from rest_framework.exceptions import ValidationError
        raise ValidationError({"owner_employee": "单据负责人必须与客户主负责人一致，请核对客户归属。"})


def object_permissions(request, customer_id, *, order=None):
    from .catalog import SALES_APPS, module_for
    data = access_for(request)
    candidates = set(data["actions"]) | {p["permission"] for p in data["legacy_sources"]}
    candidates.update(code for code in LEGACY_ACTION_PERMISSIONS if legacy_permission(request, code))
    result = []
    for code in sorted(candidates):
        if module_for(code) not in SALES_APPS:
            continue
        if can_customer(request, code, customer_id):
            result.append(code)
        elif order and module_for(code) == "sales_orders" and "OWN" in scopes(request, code) and order.merchandiser_id == getattr(request.employee, "pk", None):
            result.append(code)
    return result


class SalesAccessSerializerMixin(serializers.Serializer):
    """Object capabilities are hints for UI; selectors remain the security gate."""
    allowed_permissions = serializers.ListField(child=serializers.CharField(), read_only=True, required=False)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request is not None and enabled():
            if instance._meta.model_name == "customeraccount":
                customer_id = instance.pk
            elif hasattr(instance, "customer_account_id"):
                customer_id = instance.customer_account_id
            elif hasattr(instance, "quotation"):
                customer_id = instance.quotation.customer_account_id
            else:
                return data
            data["allowed_permissions"] = object_permissions(request, customer_id, order=instance if instance._meta.model_name == "salesorder" else None)
        return data
