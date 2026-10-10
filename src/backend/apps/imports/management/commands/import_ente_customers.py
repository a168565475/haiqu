from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from apps.imports.ente_customer_import import (
    ImportValidationError,
    build_import_plan,
    dump_summary,
    execute_import,
    execute_sync,
    plan_summary,
)


class Command(BaseCommand):
    help = "校验或导入恩特 ERP 客户详细资料。默认只读校验，传入 --apply 才会写入。"

    def add_arguments(self, parser):
        parser.add_argument("source", help="恩特 ERP 客户详细资料 XLSX 文件路径")
        parser.add_argument("--apply", action="store_true", help="通过全部校验后正式导入")
        parser.add_argument("--sync", action="store_true", help="重读并重映射已导入的恩特客户，不创建重复客户")
        parser.add_argument("--expect-customers", type=int)
        parser.add_argument("--expect-contacts", type=int)

    def handle(self, *args, **options):
        try:
            plan = build_import_plan(options["source"])
            if options["expect_customers"] is not None and plan["customer_count"] != options["expect_customers"]:
                raise ImportValidationError(
                    f"客户数量为 {plan['customer_count']}，与预期 {options['expect_customers']} 不一致。"
                )
            if options["expect_contacts"] is not None and plan["contact_count"] != options["expect_contacts"]:
                raise ImportValidationError(
                    f"联系人数量为 {plan['contact_count']}，与预期 {options['expect_contacts']} 不一致。"
                )
            if options["apply"] and options["sync"]:
                raise ImportValidationError("--apply 与 --sync 不能同时使用。")
            if options["apply"]:
                result = execute_import(plan)
                self.stdout.write(dump_summary({"mode": "apply", **result}))
            elif options["sync"]:
                result = execute_sync(plan)
                self.stdout.write(dump_summary({"mode": "sync", **result}))
            else:
                self.stdout.write(dump_summary({"mode": "dry-run", **plan_summary(plan)}))
        except (ImportValidationError, ValidationError) as exc:
            raise CommandError(str(exc)) from exc
