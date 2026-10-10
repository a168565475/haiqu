import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.inventory.public_stock_preview import PublicStockPreviewError, preview_public_stock
from apps.organizations.models import Employee


class Command(BaseCommand):
    help = "公共库存预检，默认只读。--apply-isolated 仅允许固定独立数据库期初预演。"

    def add_arguments(self, parser):
        parser.add_argument("--apply-isolated", action="store_true")
        parser.add_argument("--actor-employee", help="隔离写入时必须指定现有员工 UUID")
        parser.add_argument("--output", help="可选 JSON 证据路径，已存在文件不会覆盖")

    def handle(self, *args, **options):
        target = Path(options["output"]) if options.get("output") else None
        if target is not None and target.exists():
            raise CommandError("输出文件已存在，禁止覆盖已有证据。")
        actor = None
        if options["apply_isolated"]:
            if not options.get("actor_employee"):
                raise CommandError("隔离预演需要 --actor-employee。")
            try:
                actor = Employee.objects.get(pk=options["actor_employee"], archived_at__isnull=True, status="ACTIVE")
            except (Employee.DoesNotExist, ValidationError, ValueError) as error:
                raise CommandError("操作员工不存在或已停用。") from error
        elif options.get("actor_employee"):
            raise CommandError("只读预检不接受操作员工参数。")
        try:
            result = preview_public_stock(apply_isolated=options["apply_isolated"], actor_employee=actor)
            content = json.dumps(result, ensure_ascii=False, indent=2, default=str)
            if target is not None:
                with target.open("x", encoding="utf-8") as output:
                    output.write(content + "\n")
            else:
                self.stdout.write(content)
        except PublicStockPreviewError as error:
            if error.report is not None:
                self.stderr.write(json.dumps(error.report, ensure_ascii=False, indent=2, default=str))
            raise CommandError(str(error)) from error
        except OSError as error:
            raise CommandError(f"证据输出失败；如已执行隔离写入，请先检查期初审计再重跑：{error}") from error
