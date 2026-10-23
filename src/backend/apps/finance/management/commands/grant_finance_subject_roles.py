from .grant_finance_account_roles import Command as AccountGrantCommand


class Command(AccountGrantCommand):
    help = "仅增补四角色的四个科目MODULE权限；默认只读，不撤销账户权限或改变员工角色。"
    permissions = tuple(f"finance.{action}_accountingsubject" for action in ("view", "add", "change", "delete"))
