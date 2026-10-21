"""显式ERP管理动作；只接受有效角色授权，不继承旧直授或MODULE开关。"""
from apps.core.auth import active_employee_for


MANAGEMENT_OPERATIONS = (
    ('manage_access', '管理角色与授权', 'access_control'),
    ('manage_accounts', '管理员工账号', 'access_control'),
    ('manage_wecom', '管理企业微信', 'access_control'),
    ('manage_notifications', '管理业务通知规则', 'access_control'),
)


def can_manage(user, code):
    if active_employee_for(user) is None:
        return False
    if user.is_superuser and user.get_username() == 'admin':
        return True
    from .selectors import effective_access
    sources = effective_access(user)['actions'].get(code, {}).get('sources', [])
    return any(source['type'] == 'ROLE' and source.get('scope') == 'MODULE' for source in sources)


def require_wecom_manager(request):
    from .services import require_manager
    return require_manager(request, 'access_control.manage_wecom')
