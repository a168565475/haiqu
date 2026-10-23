from .grant_finance_account_roles import Command as AccountGrantCommand


class Command(AccountGrantCommand):
    help = "仅增补四角色的对账查看、新增、编辑、作废MODULE权限；默认只读，不改变员工关系。"
    permissions = tuple(f"finance.{action}_receivablestatement" for action in ("view", "add", "change", "void"))
