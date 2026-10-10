import json

from django.core.management.base import BaseCommand, CommandError

from apps.procurement.workbook_import import (
    SupplierWorkbookError,
    import_supplier_rows,
    read_supplier_workbook,
    supplier_workbook_summary,
)


class Command(BaseCommand):
    help = "校验或导入供应商 Excel；默认只校验，不写数据库。"

    def add_arguments(self, parser):
        parser.add_argument("workbook_path", help="供应商 Excel 文件路径")
        parser.add_argument("--apply", action="store_true", help="确认后实际写入数据库")
        parser.add_argument("--expect-rows", type=int, help="确认的表格数据行数")
        parser.add_argument("--expect-existing", type=int, help="确认的数据库现有供应商数量")

    def handle(self, *args, **options):
        try:
            rows = read_supplier_workbook(options["workbook_path"])
            summary = supplier_workbook_summary(rows)
            expected_rows = options.get("expect_rows")
            if expected_rows is not None and summary["rows"] != expected_rows:
                raise SupplierWorkbookError(
                    f"表格共有 {summary['rows']} 条，与确认值 {expected_rows} 不一致。"
                )

            self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
            if not options["apply"]:
                self.stdout.write(self.style.WARNING("仅完成校验，未写入数据库。"))
                return
            if expected_rows is None or options.get("expect_existing") is None:
                raise SupplierWorkbookError(
                    "实际导入必须同时提供 --expect-rows 和 --expect-existing，避免误覆盖数据。"
                )
            result = import_supplier_rows(rows, expected_existing=options["expect_existing"])
            self.stdout.write(self.style.SUCCESS(f"供应商导入完成：{result}"))
        except SupplierWorkbookError as exc:
            raise CommandError(str(exc)) from exc
