from .grant_finance_account_roles import Command as AccountGrantCommand


class Command(AccountGrantCommand):
    help = "仅增补四角色的收款查看、新增、作废MODULE权限；默认只读，不改变员工关系。"
    permissions = tuple(f"finance.{action}_receipt" for action in ("view", "add", "void"))
