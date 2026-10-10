import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.samples.workbook_import import (
    SampleWorkbookImportError,
    build_sample_import_report,
    build_sample_workbook_import_plan,
    execute_sample_workbook_import,
    sample_import_plan_summary,
)


class Command(BaseCommand):
    help = "校验或全量替换导入历史样品 XLSX。默认只读，传入完整确认参数才会写库。"

    def add_arguments(self, parser):
        parser.add_argument("source", help="历史样品 XLSX 文件路径")
        parser.add_argument("--apply", action="store_true", help="正式执行数据库写入")
        parser.add_argument("--replace-all", action="store_true", help="删除全部现有样品后导入")
        parser.add_argument("--expect-samples", type=int, required=True, help="预期源样品数量")
        parser.add_argument("--expect-existing", type=int, help="正式替换前预期现有样品数量")
        parser.add_argument("--report-json", help="导入报告 JSON 输出路径")

    def handle(self, *args, **options):
        try:
            plan = build_sample_workbook_import_plan(options["source"])
            summary = sample_import_plan_summary(plan)
            if summary["sample_count"] != options["expect_samples"]:
                raise SampleWorkbookImportError(
                    f"源文件样品数量为 {summary['sample_count']}，与预期 {options['expect_samples']} 不一致。"
                )
            if options["apply"]:
                if not options["replace_all"]:
                    raise SampleWorkbookImportError("正式执行必须同时传入 --replace-all。")
                if options["expect_existing"] is None:
                    raise SampleWorkbookImportError("正式执行必须传入 --expect-existing。")
                result = execute_sample_workbook_import(
                    plan,
                    expected_existing=options["expect_existing"],
                )
                report = build_sample_import_report(plan, mode="apply", result=result)
            else:
                if options["replace_all"]:
                    raise SampleWorkbookImportError("只读校验不需要传入 --replace-all。")
                report = build_sample_import_report(plan, mode="dry-run")

            if options["report_json"]:
                report_path = Path(options["report_json"])
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                report["report_json"] = str(report_path)
            self.stdout.write(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
        except SampleWorkbookImportError as exc:
            raise CommandError(str(exc)) from exc
