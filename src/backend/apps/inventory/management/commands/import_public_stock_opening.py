import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.inventory.public_stock_opening import (
    PublicStockOpeningError,
    apply_public_stock_opening,
    build_public_stock_opening_manifest,
)
from apps.inventory.stock_services import InventoryStockValidationError


class Command(BaseCommand):
    help = "正式公共库存期初工具。默认只读清单；--apply 须明确清单 SHA、目标、备份证据和维护停写状态。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--actor-employee", help="关联有效管理员账号的在职员工 UUID")
        parser.add_argument("--backup-evidence", help="备份及恢复验证证据 JSON 的路径")
        parser.add_argument("--expected-manifest-sha256")
        parser.add_argument("--expected-host")
        parser.add_argument("--expected-database")
        parser.add_argument("--expected-system-identifier")
        parser.add_argument("--output", help="JSON 审阅清单或执行回执路径；禁止覆盖")

    def handle(self, *args, **options):
        output_path = Path(options["output"]) if options.get("output") else None
        if output_path is not None and output_path.exists():
            raise CommandError("输出文件已存在，禁止覆盖已有证据。")
        expected_keys = ("expected_manifest_sha256", "expected_host", "expected_database", "expected_system_identifier")
        if options["apply"] and not all(options.get(key) for key in (*expected_keys, "actor_employee", "backup_evidence")):
            raise CommandError("执行必须提供员工、备份证据、已审清单 SHA、预期主机、预期库名和预期集群标识。")
        if not options["apply"] and any(options.get(key) for key in expected_keys):
            raise CommandError("预期清单和目标参数仅用于 --apply；只读预检请省略。")
        try:
            arguments = {"actor_employee": options.get("actor_employee"),
                         "backup_evidence_path": options.get("backup_evidence")}
            if options["apply"]:
                result = apply_public_stock_opening(
                    **arguments, expected_manifest_sha256=options["expected_manifest_sha256"],
                    expected_target={"host": options["expected_host"], "database": options["expected_database"],
                                     "system_identifier": options["expected_system_identifier"]})
            else:
                result = build_public_stock_opening_manifest(**arguments)
            content = json.dumps(result, ensure_ascii=False, indent=2, default=str)
            if output_path is not None:
                with output_path.open("x", encoding="utf-8") as output:
                    output.write(content + "\n")
            else:
                self.stdout.write(content)
        except PublicStockOpeningError as error:
            if error.report is not None:
                self.stderr.write(json.dumps(error.report, ensure_ascii=False, indent=2, default=str))
            raise CommandError(str(error)) from error
        except InventoryStockValidationError as error:
            raise CommandError(str(error)) from error
        except OSError as error:
            raise CommandError(f"证据文件读写失败；如已执行导入，请先核对正式期初审计后再用原清单重跑：{error}") from error
