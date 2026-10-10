from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.organizations.models import Employee
from .services import audit, require_manager


def checked_employee(request, pk):
    require_manager(request)
    employee = get_object_or_404(Employee.objects.select_for_update(no_key=True), pk=pk)
    require_matching_etag(request, employee)
    if employee.archived_at or employee.status != "ACTIVE":
        raise Conflict("请先确认员工处于在职状态。")
    return employee


def checked_password(user, password):
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise ValidationError({"password": exc.messages}) from exc


def account_snapshot(user):
    return {"username": user.username, "is_active": user.is_active}


def ordinary_account(employee):
    if employee.user_id is None:
        raise Conflict("此员工尚未创建登录账号。")
    user = get_user_model().objects.select_for_update().get(pk=employee.user_id)
    if user.is_superuser or user.is_staff or user.username == "admin":
        raise Conflict("管理账号受保护，请使用专门的管理员维护流程。")
    return user


@transaction.atomic
def create_account(request, pk, data):
    employee = checked_employee(request, pk)
    if employee.user_id is not None:
        raise Conflict("该员工已关联账号，不能重复创建。")
    user = get_user_model()(username=data["username"], is_active=True)
    checked_password(user, data["password"])
    user.set_password(data["password"])
    try:
        with transaction.atomic():
            user.save()
    except IntegrityError as exc:
        raise Conflict("登录账号已存在，请换一个账号。") from exc
    employee.user = user
    employee.save(update_fields=["user", "updated_at"])
    audit(request, employee, "ACCOUNT_CREATE", {}, account_snapshot(user), "ACCESS_EMPLOYEE")
    return employee


@transaction.atomic
def set_account_status(request, pk, is_active):
    employee = checked_employee(request, pk)
    user = ordinary_account(employee)
    before = account_snapshot(user)
    user.is_active = is_active
    user.save(update_fields=["is_active"])
    if not is_active:
        # Re-enabling must never revive a session issued before suspension.
        session_keys = [session.session_key for session in Session.objects.filter(
            expire_date__gt=timezone.now()).iterator()
            if session.get_decoded().get("_auth_user_id") == str(user.pk)]
        Session.objects.filter(session_key__in=session_keys).delete()
    employee.save(update_fields=["updated_at"])
    audit(request, employee, "ACCOUNT_STATUS", before, account_snapshot(user), "ACCESS_EMPLOYEE")
    return employee


@transaction.atomic
def reset_password(request, pk, password):
    employee = checked_employee(request, pk)
    user = ordinary_account(employee)
    checked_password(user, password)
    user.set_password(password)
    user.save(update_fields=["password"])
    # Django session authentication hash revokes pre-existing sessions on next use.
    employee.save(update_fields=["updated_at"])
    audit(request, employee, "ACCOUNT_PASSWORD_RESET", {}, {"password_reset": True}, "ACCESS_EMPLOYEE")
    return employee
