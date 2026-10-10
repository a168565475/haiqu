import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from rest_framework.exceptions import APIException

from apps.inventory.public_stock_activation import (PublicStockActivationError,
    apply_public_stock_activation, build_public_stock_activation_manifest)


class Command(BaseCommand):
    help = "公共库存首次启用。默认只读一致快照；显式应用须绑定现场摘要、维护会话、具名授权和目标。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--actor-employee")
        parser.add_argument("--backup-evidence")
        parser.add_argument("--retention-evidence")
        parser.add_argument("--authorization")
        parser.add_argument("--request-id")
        parser.add_argument("--expected-control-id")
        parser.add_argument("--expected-manifest-sha256")
        parser.add_argument("--expected-host")
        parser.add_argument("--expected-database")
        parser.add_argument("--expected-system-identifier")
        parser.add_argument("--output", help="新建 JSON 证据文件，禁止覆盖")

    def handle(self, *args, **options):
        output_path = Path(options["output"]) if options.get("output") else None
        if output_path is not None and output_path.exists():
            raise CommandError("输出文件已存在，禁止覆盖已有证据。")
        apply_keys = ("authorization", "request_id", "expected_control_id", "expected_manifest_sha256",
                      "expected_host", "expected_database", "expected_system_identifier")
        if options["apply"] and not all(options.get(key) for key in (*apply_keys, "actor_employee", "backup_evidence")):
            raise CommandError("启用须提供有效管理员、备份、具名授权、请求、维护会话、已审摘要和完整三项目标。")
        if not options["apply"] and any(options.get(key) for key in apply_keys):
            raise CommandError("授权及预期参数只用于 --apply；预检请省略。")
        try:
            arguments = {"actor_employee": options.get("actor_employee"),
                "backup_evidence_path": options.get("backup_evidence"),
                "retention_evidence_path": options.get("retention_evidence")}
            if options["apply"]:
                result = apply_public_stock_activation(**arguments, authorization_path=options["authorization"],
                    request_id=options["request_id"], expected_control_id=options["expected_control_id"],
                    expected_manifest_sha256=options["expected_manifest_sha256"], expected_target={
                        "host": options["expected_host"], "database": options["expected_database"],
                        "system_identifier": options["expected_system_identifier"]})
            else:
                result = build_public_stock_activation_manifest(**arguments)
            content = json.dumps(result, ensure_ascii=False, indent=2, default=str)
            if output_path:
                with output_path.open("x", encoding="utf-8") as output:
                    output.write(content + "\n")
            else:
                self.stdout.write(content)
        except PublicStockActivationError as error:
            if error.report is not None:
                self.stderr.write(json.dumps(error.report, ensure_ascii=False, indent=2, default=str))
            raise CommandError(str(error)) from error
        except (APIException, DatabaseError) as error:
            raise CommandError(f"启用事务失败或等待锁超时；保持原状态，请核对审计后决定是否重放原请求：{error}") from error
        except OSError as error:
            raise CommandError(f"证据文件读写失败；如执行过应用，先核对控制状态及审计，不能换新请求重试：{error}") from error
