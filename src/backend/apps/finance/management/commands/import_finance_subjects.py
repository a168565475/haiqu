import json
import sys
from pathlib import Path
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from rest_framework.exceptions import APIException

from apps.core.auth import active_employee_for
from apps.organizations.models import Employee
from apps.finance.subject_importing import read_subject_workbook, subject_import_plan, apply_subject_import


class Command(BaseCommand):
    help = "三级科目完整路径导入；默认只读预检，不覆盖同路径不同状态。"

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
            paths = read_subject_workbook(content, options["sha256"])
            exists = "finance_accounting_subject" in connection.introspection.table_names()
            plan = subject_import_plan(paths, table_exists=exists)
            self.stdout.write(json.dumps({"database": connection.settings_dict["NAME"], "table_exists": exists,
                "sha256_verified": True, "mode": "APPLY" if options["apply"] else "READ_ONLY", **plan}, ensure_ascii=False))
            if any(item["action"] == "CONFLICT" for item in plan["nodes"]):
                raise CommandError("存在冲突，未写入。")
            if options["apply"]:
                if not exists:
                    raise CommandError("科目迁移尚未执行。")
                actor = Employee.objects.select_related("user").filter(pk=options["actor_employee_id"]).first()
                if not actor or not actor.user or active_employee_for(actor.user) != actor or not actor.user.has_perm("finance.add_accountingsubject"):
                    raise CommandError("执行人必须是在职且有新增科目权限的真实员工。")
                apply_subject_import(paths, actor)
                self.stdout.write("APPLIED_AND_EXACTLY_VERIFIED")
        except (OSError, APIException, ValueError) as exc:
            raise CommandError(str(exc)) from exc
