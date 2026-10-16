import importlib
import importlib.util
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO, StringIO
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from openpyxl import Workbook
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.products.models import ProductInformation


HEADERS = ["类型", "产品编码", "类别", "品名", "规格", "单位", "货号", "仓库号", "仓库名称", "规模"]


def workbook_bytes(rows, *, headers=None, sheet="产品信息"):
    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet(sheet)
    worksheet.append(HEADERS if headers is None else headers)
    for row in rows:
        worksheet.append(row)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


class ProductCatalogPreflightTests(SimpleTestCase):
    def test_parse_preserves_complete_category_and_name_including_outer_spaces(self):
        importing = importlib.import_module("apps.product_catalog.importing")
        source = workbook_bytes([
            ["成品", None, "  折叠 椅  ", " 完整椅名（白色款） ", "/", "张", "ITEM 01", None, None, "常规"],
        ])
        row = importing.preflight_product_catalog(source, filename="原文名称.xlsx")["rows"][0]
        self.assertEqual(row["category"], "  折叠 椅  ")
        self.assertEqual(row["name"], " 完整椅名（白色款） ")
        self.assertEqual(row["raw_fields"]["类别"], "  折叠 椅  ")
        self.assertEqual(row["raw_fields"]["品名"], " 完整椅名（白色款） ")

    def test_parse_retains_source_row_numbers_nulls_slashes_and_internal_spaces(self):
        module = "apps.product_catalog.importing"
        self.assertIsNotNone(importlib.util.find_spec(module), "尚未实现独立产品来源导入")
        importing = importlib.import_module(module)
        source = workbook_bytes([
            ["成品", None, "椅", "完整椅名（白色款）", "/", "/", "ITEM 01", None, None, "常规"],
            [None] * 10,
            ["成品", " C  01 ", "椅", "完整椅名（白色款）", "100 / 50", "张", "ITEM 01", None, None, "定制"],
        ])
        result = importing.preflight_product_catalog(source, filename="内存来源.xlsx")
        self.assertEqual([row["row"] for row in result["rows"]], [2, 4])
        self.assertEqual(result["rows"][0]["data"], {"product_code": "", "item_number": "ITEM 01", "specification": "", "unit": "", "scale": "常规"})
        self.assertEqual(result["rows"][1]["data"]["product_code"], " C  01 ")
        self.assertEqual(result["rows"][1]["data"]["specification"], "100 / 50")
        self.assertEqual(result["rows"][0]["raw_fields"]["规格"], "/")
        self.assertIsNone(result["rows"][0]["raw_fields"]["产品编码"])


class ProductCatalogImportTests(TestCase):
    def setUp(self):
        module = "apps.product_catalog.importing"
        self.assertIsNotNone(importlib.util.find_spec(module), "尚未实现独立产品来源导入")
        self.importing = importlib.import_module(module)
        self.Category = apps.get_model("product_catalog", "ProductCatalogCategory")
        self.Name = apps.get_model("product_catalog", "ProductCatalogName")
        self.Product = apps.get_model("product_catalog", "ProductCatalog")
        self.Color = apps.get_model("product_catalog", "ProductCatalogColor")
        self.Import = apps.get_model("product_catalog", "ProductCatalogImport")
        self.user = get_user_model().objects.create_superuser(username="product_importer", password="CatalogTest123!", email="")
        self.employee = Employee.objects.create(user=self.user, employee_code="PRODUCT_IMPORTER", display_name="导入测试员")
        self.filename = "产品导入测试.xlsx"
        self.rows = [
            ["成品", "  C  001  ", "折叠椅", "完整月亮椅（白色款）", "100 / 50", "张", "ITEM 001", None, None, "定制"],
            ["成品", None, "折叠椅", "完整月亮椅（白色款）", "/", "/", "ITEM 001", "W", "仓", "常规"],
            [None] * 10,
            ["成品", None, "折叠椅", "完整月亮椅（白色款）", "/", "/", "ITEM 001", "W", "仓", "常规"],
            ["成品", "D002", "其他椅", "完整月亮椅（白色款）", "200", "套", "ITEM 001", "W", "仓", "常规"],
        ]
        self.source = workbook_bytes(self.rows)

    def run_import(self, source=None, **kwargs):
        return self.importing.import_product_catalog(
            self.source if source is None else source,
            filename=kwargs.pop("filename", self.filename),
            **kwargs,
        )

    def counts(self):
        return tuple(model.objects.count() for model in (
            self.Category, self.Name, self.Product, self.Color, self.Import, AuditLog, ProductInformation,
        ))

    def apply(self, **kwargs):
        return self.run_import(apply=True, actor=self.user, **kwargs)

    def test_preflight_is_read_only_and_preserves_actual_source_rows(self):
        before = self.counts()
        result = self.run_import()
        self.assertEqual(self.counts(), before)
        self.assertEqual((result["total_rows"], result["category_count"], result["name_count"], result["blank_codes"]), (4, 2, 2, 2))
        self.assertEqual((result["created"], result["existing"]), (0, 0))
        self.assertEqual(result["pending"], 4)
        parsed = self.importing.preflight_product_catalog(self.source, filename=self.filename)
        self.assertEqual([row["row"] for row in parsed["rows"]], [2, 3, 5, 6])

    def test_apply_maps_verbatim_fields_keeps_identical_rows_and_saves_source_bytes(self):
        legacy = list(ProductInformation.objects.values_list("id", "updated_at"))
        result = self.apply()
        self.assertEqual((result["created"], result["existing"]), (4, 0))
        self.assertEqual((self.Category.objects.count(), self.Name.objects.count(), self.Product.objects.count()), (2, 2, 4))
        first = self.Product.objects.get(source_row=2)
        empty = self.Product.objects.get(source_row=3)
        duplicate = self.Product.objects.get(source_row=5)
        self.assertEqual((first.product_code, first.item_number, first.specification, first.unit, first.scale), ("  C  001  ", "ITEM 001", "100 / 50", "张", "定制"))
        self.assertEqual((empty.product_code, empty.specification, empty.unit, empty.scale), ("", "", "", "常规"))
        self.assertEqual(first.name.name, "完整月亮椅（白色款）")
        self.assertNotEqual(empty.pk, duplicate.pk)
        self.assertEqual(empty.source_raw_fields, duplicate.source_raw_fields)
        self.assertEqual(empty.source_raw_fields["规格"], "/")
        self.assertIsNone(empty.source_raw_fields["产品编码"])
        self.assertIsNone(first.source_raw_fields["仓库名称"])
        self.assertEqual(list(self.Color.objects.values_list("value", flat=True)), ["无颜色"] * 4)
        batch = self.Import.objects.get()
        self.assertEqual(bytes(batch.source_bytes), self.source)
        self.assertEqual((batch.filename, batch.sha256, batch.sheet, batch.row_count), (self.filename, sha256(self.source).hexdigest(), "产品信息", 4))
        self.assertEqual(first.source_import_id, batch.pk)
        audits = AuditLog.objects.filter(object_type="PRODUCT_CATALOG", action="CREATED")
        self.assertEqual(audits.count(), 4)
        self.assertEqual(set(audits.values_list("actor_employee_id", flat=True)), {self.employee.pk})
        self.assertEqual(legacy, list(ProductInformation.objects.values_list("id", "updated_at")))

    def test_identical_import_does_not_update_products_colors_or_audits(self):
        self.apply()
        before_counts = self.counts()
        before_rows = list(self.Product.objects.order_by("id").values_list("id", "updated_at"))
        result = self.apply()
        self.assertEqual((result["created"], result["existing"]), (0, 4))
        self.assertEqual(self.counts(), before_counts)
        self.assertEqual(list(self.Product.objects.order_by("id").values_list("id", "updated_at")), before_rows)

    def test_changed_same_filename_and_sheet_is_blocked_even_in_preflight(self):
        self.apply()
        changed = [list(row) for row in self.rows]
        changed[0][4] = "不同规格"
        before = self.counts()
        for apply in (False, True):
            with self.subTest(apply=apply), self.assertRaises(ValidationError):
                self.run_import(workbook_bytes(changed), apply=apply, actor=self.user)
        self.assertEqual(self.counts(), before)

    def test_different_filename_is_a_distinct_source(self):
        self.apply()
        result = self.apply(filename="另一个来源.xlsx")
        self.assertEqual((result["created"], self.Product.objects.count(), self.Import.objects.count()), (4, 8, 2))

    def test_apply_requires_existing_active_employee_and_add_permission(self):
        outsider = get_user_model().objects.create_user(username="product_import_no_permission")
        Employee.objects.create(user=outsider, employee_code="PRODUCT_IMPORT_NO_PERMISSION", display_name="无权限")
        no_employee = get_user_model().objects.create_superuser(username="product_import_no_employee", password="Test123!", email="")
        inactive = get_user_model().objects.create_superuser(username="product_import_inactive", password="Test123!", email="", is_active=False)
        Employee.objects.create(user=inactive, employee_code="PRODUCT_IMPORT_INACTIVE", display_name="停用")
        before = self.counts()
        for actor in (None, outsider, no_employee, inactive):
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                self.run_import(apply=True, actor=actor)
        self.assertEqual(self.counts(), before)

    def test_user_with_direct_add_permission_can_import(self):
        user = get_user_model().objects.create_user(username="product_import_allowed")
        Employee.objects.create(user=user, employee_code="PRODUCT_IMPORT_ALLOWED", display_name="有权限")
        user.user_permissions.add(Permission.objects.get(content_type__app_label="product_catalog", codename="add_productcatalog"))
        result = self.run_import(apply=True, actor=user)
        self.assertEqual(result["created"], 4)

    def test_invalid_source_cell_blocks_the_whole_batch(self):
        invalid_values = [(2, None), (3, ""), (1, 123), (4, "=1+1"), (4, "x" * 301), (9, "未知规模")]
        before = self.counts()
        for column, value in invalid_values:
            invalid_rows = [list(row) for row in self.rows]
            invalid_rows[-1][column] = value
            with self.subTest(column=column, value=value), self.assertRaises(ValidationError):
                self.run_import(workbook_bytes(invalid_rows), apply=True, actor=self.user)
        self.assertEqual(self.counts(), before)

    def test_corrupt_workbook_wrong_header_missing_sheet_and_empty_rows_are_rejected(self):
        sources = [b"not an xlsx", workbook_bytes(self.rows, headers=HEADERS[:-1]), workbook_bytes(self.rows, sheet="其他表"), workbook_bytes([])]
        for source in sources:
            with self.subTest(size=len(source)), self.assertRaises(ValidationError):
                self.run_import(source)

    def test_audit_failure_rolls_back_batch_categories_names_products_and_colors(self):
        before = self.counts()
        from apps.product_catalog.services import write_audit_log

        def fail_on_second_product(**kwargs):
            if kwargs.get("object_type") == "PRODUCT_CATALOG" and self.Product.objects.count() == 2:
                raise RuntimeError("audit storage unavailable")
            return write_audit_log(**kwargs)

        with patch("apps.product_catalog.services.write_audit_log", side_effect=fail_on_second_product):
            with self.assertRaisesRegex(RuntimeError, "audit storage unavailable"):
                self.apply()
        self.assertEqual(self.counts(), before)

    def test_verify_replays_saved_workbook_without_writes(self):
        self.apply()
        before = self.counts()
        result = self.importing.verify_product_catalog_import(batch=self.Import.objects.get())
        self.assertTrue(result["valid"])
        self.assertEqual((result["total_rows"], result["matched_rows"]), (4, 4))
        self.assertEqual(result["differences"], [])
        self.assertEqual(self.counts(), before)

    def test_verify_reports_source_rows_for_edited_values_and_colors_without_overwriting(self):
        self.apply()
        edited = self.Product.objects.get(source_row=2)
        edited.specification = "人工修改的规格"
        edited.save(update_fields=["specification", "updated_at"])
        self.Color.objects.filter(product=edited).update(value="蓝色")
        before = list(self.Product.objects.order_by("id").values_list("id", "updated_at"))
        result = self.importing.verify_product_catalog_import(batch=self.Import.objects.get())
        self.assertFalse(result["valid"])
        self.assertEqual(result["matched_rows"], 3)
        self.assertEqual(result["differences"], [{"row": 2, "fields": ["specification", "colors"]}])
        self.assertNotIn("人工修改的规格", json.dumps(result, ensure_ascii=False))
        self.assertEqual(list(self.Product.objects.order_by("id").values_list("id", "updated_at")), before)

    def test_verify_detects_corrupt_saved_source_bytes(self):
        self.apply()
        batch = self.Import.objects.get()
        batch.source_bytes = b"changed bytes"
        batch.save(update_fields=["source_bytes"])
        result = self.importing.verify_product_catalog_import(batch=batch)
        self.assertFalse(result["valid"])
        self.assertIn("source_sha256", result["batch_errors"])

    def test_command_defaults_to_preview_and_requires_actor_for_apply(self):
        before = self.counts()
        output = StringIO()
        with patch("apps.product_catalog.management.commands.import_product_catalog.Path.read_bytes", return_value=self.source):
            call_command("import_product_catalog", self.filename, stdout=output)
            with self.assertRaises(CommandError):
                call_command("import_product_catalog", self.filename, apply=True, stdout=StringIO())
        self.assertEqual(self.counts(), before)
        self.assertEqual(json.loads(output.getvalue())["pending"], 4)

    def test_command_apply_and_verify_use_explicit_actor_and_saved_source(self):
        with patch("apps.product_catalog.management.commands.import_product_catalog.Path.read_bytes", return_value=self.source):
            output = StringIO()
            call_command("import_product_catalog", self.filename, apply=True, actor=self.user.username, stdout=output)
            self.assertEqual(json.loads(output.getvalue())["created"], 4)
            verify = StringIO()
            call_command("import_product_catalog", self.filename, verify=True, stdout=verify)
            self.assertTrue(json.loads(verify.getvalue())["valid"])

    def test_command_rejects_unknown_actor_missing_file_and_conflicting_modes(self):
        with self.assertRaises(CommandError):
            call_command("import_product_catalog", self.filename, apply=True, verify=True, actor=self.user.username)
        with patch("apps.product_catalog.management.commands.import_product_catalog.Path.read_bytes", side_effect=FileNotFoundError("missing")):
            with self.assertRaises(CommandError):
                call_command("import_product_catalog", self.filename)
        with patch("apps.product_catalog.management.commands.import_product_catalog.Path.read_bytes", return_value=self.source):
            with self.assertRaises(CommandError):
                call_command("import_product_catalog", self.filename, apply=True, actor="unknown-user")


class ProductCatalogImportConcurrencyTests(TransactionTestCase):
    def test_simultaneous_changed_versions_cannot_create_two_batches(self):
        module = "apps.product_catalog.importing"
        self.assertIsNotNone(importlib.util.find_spec(module), "尚未实现独立产品来源导入")
        importing = importlib.import_module(module)
        user = get_user_model().objects.create_superuser(username="concurrent_product_import", password="Test123!", email="")
        Employee.objects.create(user=user, employee_code="CONCURRENT_PRODUCT_IMPORT", display_name="并发导入测试员")
        sources = [workbook_bytes([["成品", code, "椅", "完整椅名", "规格", "张", "相同货号", None, None, "定制"]]) for code in ("A", "B")]
        barrier = threading.Barrier(2, timeout=15)

        def import_version(source):
            close_old_connections()
            try:
                barrier.wait()
                try:
                    return importing.import_product_catalog(source, filename="同时提交.xlsx", apply=True, actor=user)
                except ValidationError:
                    return "source-conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(import_version, source) for source in sources]
            results = [future.result(timeout=30) for future in futures]
        self.assertEqual(sum(isinstance(result, dict) and result["created"] == 1 for result in results), 1)
        self.assertEqual(results.count("source-conflict"), 1)
        self.assertEqual(apps.get_model("product_catalog", "ProductCatalogImport").objects.count(), 1)
        self.assertEqual(apps.get_model("product_catalog", "ProductCatalog").objects.count(), 1)
