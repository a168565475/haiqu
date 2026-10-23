from uuid import NAMESPACE_URL, uuid5

from apps.organizations.models import Employee
from .audit import write_audit_log


def login_account_id(user_id):
    # 审计对象使用稳定 UUID，账号尚未关联员工时也能保留同一份登录记录。
    return uuid5(NAMESPACE_URL, f"haiqu:auth-user:{user_id}")


def record_successful_login(request, user, method):
    """在登录事务内记录；不记录密码、企微授权码或会话凭据。"""
    employee = Employee.objects.filter(user_id=user.pk).first()
    write_audit_log(object_type="AUTH_ACCOUNT", object_id=login_account_id(user.pk),
                    action="LOGIN_SUCCESS", actor_employee=employee, request=request,
                    after_data={"user_id": user.pk, "username": user.get_username(), "method": method})
