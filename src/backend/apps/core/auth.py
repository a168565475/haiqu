from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Group
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.utils import timezone

from apps.organizations.models import EmployeeStatus


def active_employee_for(user):
    if not user or not user.is_authenticated or not user.is_active:
        return None

    try:
        employee = user.employee_profile
    except ObjectDoesNotExist:
        return None

    if employee.status != EmployeeStatus.ACTIVE or employee.archived_at is not None:
        return None
    return employee


def can_access_erp(user):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return active_employee_for(user) is not None


class ErpModelBackend(ModelBackend):
    def get_group_permissions(self, user_obj, obj=None):
        permissions = set(super().get_group_permissions(user_obj, obj))
        if obj is not None or not can_access_erp(user_obj) or user_obj.is_superuser:
            return permissions

        cache_name = "_erp_role_perm_cache"
        if not hasattr(user_obj, cache_name):
            now = timezone.now()
            role_groups = Group.objects.filter(
                role_profile__archived_at__isnull=True,
                role_profile__employee_assignments__employee__user=user_obj,
                role_profile__employee_assignments__effective_from__lte=now,
            ).filter(
                Q(role_profile__employee_assignments__effective_to__isnull=True)
                | Q(role_profile__employee_assignments__effective_to__gt=now)
            )
            role_permissions = {
                f"{app_label}.{codename}"
                for app_label, codename in role_groups.values_list(
                    "permissions__content_type__app_label",
                    "permissions__codename",
                )
                if app_label and codename
            }
            setattr(user_obj, cache_name, role_permissions)

        return permissions | getattr(user_obj, cache_name)

    def has_perm(self, user_obj, perm, obj=None):
        if not can_access_erp(user_obj):
            return False
        return super().has_perm(user_obj, perm, obj)
