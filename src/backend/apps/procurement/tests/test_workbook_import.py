from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase
from openpyxl import Workbook

from ..models import Supplier
from ..workbook_import import (
    SupplierWorkbookError,
    import_supplier_rows,
    read_supplier_workbook,
    supplier_workbook_summary,
)


class SupplierWorkbookImportTests(TestCase):
    headers = [
        "供应商编号",
        "供应商类型",
        "供应商类别",
        "供应商名称",
        "付款周期",
        "备注",
        "供应商类别-文本",
        "联系电话",
        "是否禁用",
        "提交人",
        "提交时间",
        "更新时间",
    ]

    def create_workbook(self, directory, *, supplier_type="材料供应商"):
        path = Path(directory) / "供应商信息.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "供应商信息"
        sheet.append(self.headers)
        sheet.append(
            [
                "GYS00265",
                supplier_type,
                "五金,辅料",
                "测试供应商",
                "月结",
                "测试备注",
                "五金,辅料",
                "13858933222",
                "禁用",
                "测试员工",
                "2026-05-18 13:59:54",
                "2026-05-18 14:00:50",
            ]
        )
        workbook.save(path)
        workbook.close()
        return path

    def test_read_summary_and_import_are_consistent(self):
        with TemporaryDirectory() as directory:
            rows = read_supplier_workbook(self.create_workbook(directory))

        summary = supplier_workbook_summary(rows)
        self.assertEqual(summary["rows"], 1)
        self.assertEqual(summary["maximum_number"], "GYS00265")
        self.assertEqual(summary["next_number"], "GYS00266")
        self.assertEqual(summary["type_counts"], {"材料供应商": 1})
        self.assertEqual(summary["category_counts"], {"五金": 1, "辅料": 1})
        self.assertEqual(summary["monthly_count"], 1)
        self.assertEqual(summary["disabled_count"], 1)

        result = import_supplier_rows(rows, expected_existing=0)
        supplier = Supplier.objects.get(supplier_number="GYS00265")
        self.assertEqual(result, {"created": 1, "updated": 0, "total": 1})
        self.assertEqual(supplier.supplier_categories, ["HARDWARE", "AUXILIARY"])
        self.assertTrue(supplier.is_disabled)

    def test_unknown_supplier_type_is_rejected(self):
        with TemporaryDirectory() as directory:
            path = self.create_workbook(directory, supplier_type="未知供应商")
            with self.assertRaisesMessage(SupplierWorkbookError, "不支持的值"):
                read_supplier_workbook(path)

    def test_existing_count_guard_stops_import(self):
        with TemporaryDirectory() as directory:
            rows = read_supplier_workbook(self.create_workbook(directory))
        with self.assertRaisesMessage(SupplierWorkbookError, "与确认值 1 不一致"):
            import_supplier_rows(rows, expected_existing=1)
