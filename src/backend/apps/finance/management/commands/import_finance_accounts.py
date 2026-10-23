import json
import sys
from uuid import UUID
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from rest_framework.exceptions import APIException

from apps.core.auth import active_employee_for
from apps.organizations.models import Employee
from apps.finance.importing import read_account_workbook, account_import_plan, apply_account_import


class Command(BaseCommand):
    help = "公司账户原表导入；默认只读预检，日志不输出账号。"

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--file")
        source.add_argument("--stdin-xlsx", action="store_true")
        parser.add_argument("--sha256", required=True)
        parser.add_argument("--database-name", required=True)
        parser.add_argument("--actor-employee-id", type=UUID)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if connection.settings_dict["NAME"] != options["database_name"]:
            raise CommandError("目标数据库名不匹配。")
        try:
            if options["stdin_xlsx"]:
                content = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
            else:
                with Path(options["file"]).open("rb") as source:
                    content = source.read(10 * 1024 * 1024 + 1)
            rows = read_account_workbook(content, options["sha256"])
            exists = "finance_account" in connection.introspection.table_names()
            plan = account_import_plan(rows, table_exists=exists)
            self.stdout.write(json.dumps({"database": connection.settings_dict["NAME"], "table_exists": exists,
                "sha256_verified": True, "rows": plan, "mode": "APPLY" if options["apply"] else "READ_ONLY"}, ensure_ascii=False))
            if any(item["action"] == "CONFLICT" for item in plan):
                raise CommandError("存在冲突，未写入。")
            if options["apply"]:
                if not exists:
                    raise CommandError("账户迁移尚未执行。")
                actor = Employee.objects.select_related("user").filter(pk=options["actor_employee_id"]).first()
                if not actor or not actor.user or active_employee_for(actor.user) != actor or not actor.user.has_perm("finance.add_financeaccount"):
                    raise CommandError("执行人必须是在职且有新增公司账户权限的真实登录员工。")
                apply_account_import(rows, actor)
                self.stdout.write("APPLIED_AND_EXACTLY_VERIFIED")
        except (OSError, APIException, ValueError) as exc:
            # 导入错误只含行号/字段，不打印原始文件内容。
            raise CommandError(str(exc)) from exc
