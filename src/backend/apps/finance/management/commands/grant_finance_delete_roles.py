from .grant_finance_account_roles import Command as AccountGrantCommand


class Command(AccountGrantCommand):
    help = "仅增补四角色的对账单/收款单删除权限；默认只读，不改变既有授权。"
    permissions = ("finance.delete_receivablestatement", "finance.delete_receipt")
