import io
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook

from apps.customers.models import CustomerAccount
from apps.files.models import BusinessFile, FileScanStatus
from apps.organizations.models import Employee
from apps.reference_data.models import ProductColor

from ..models import (
    FeeVerificationStatus,
    SampleFeeRecord,
    SampleItem,
    SampleProduct,
    SampleProductSamplingDetail,
    SampleRequest,
    SampleRequestStatus,
    SampleWorkflowRecord,
)
from ..workbook_import import (
    IMPORT_EMPLOYEE_CODE,
    MISSING_CATEGORY_NAME,
    SampleWorkbookImportError,
    build_sample_workbook_import_plan,
    execute_sample_workbook_import,
)


class SampleWorkbookImportTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.import_employee, _ = Employee.objects.get_or_create(
            employee_code=IMPORT_EMPLOYEE_CODE,
            defaults={"display_name": "恩特 ERP 导入服务"},
        )
        self.product_color, _ = ProductColor.objects.get_or_create(
            color_card="潘通色卡",
            color_name="7743C（近墨绿）",
            color_code="7743C",
        )
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.workbook_path = Path(self.temp_dir.name) / "samples.xlsx"
        self._create_workbook(self.workbook_path)

    def _create_workbook(self, path):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "打样单"
        headers = {
            "A1": "标题",
            "B1": "打样单编号",
            "C1": "打样单号-手填",
            "D1": "生成打样单号",
            "X1": "样品明细",
            "AL1": "打样信息明细",
            "AP1": "特殊说明",
            "BT1": "流程状态",
            "BU1": "当前节点",
            "X2": "产品类别",
            "Y2": "产品名称",
            "Z2": "规格",
            "AA2": "色卡",
            "AB2": "颜色",
            "AC2": "色号",
            "AD2": "打样数量",
            "AK2": "样品明细UUID",
            "AL2": "类型",
            "AM2": "类别",
            "AN2": "描述",
            "AO2": "图片",
        }
        for cell, value in headers.items():
            sheet[cell] = value

        values = {
            "A3": "1",
            "B3": "不导入编号",
            "C3": "HTS-26008",
            "D3": "HTS-HTS-26008",
            "E3": "原业务员",
            "F3": "邮寄",
            "G3": "2026-09-01",
            "H3": "2026-09-05",
            "I3": "一次交货",
            "J3": "否",
            "K3": "否",
            "L3": "原制单人",
            "M3": "2026-09-02",
            "N3": MISSING_CATEGORY_NAME,
            "O3": "测试椅",
            "P3": "标准规格",
            "R3": 1,
            "S3": 60,
            "T3": 10,
            "U3": 40,
            "V3": 50,
            "W3": 45,
            "X3": MISSING_CATEGORY_NAME,
            "Y3": "测试椅",
            "Z3": "标准规格",
            "AA3": "潘通定色",
            "AB3": "7743C（近墨绿）",
            "AC3": "7743C",
            "AD3": 1,
            "AE3": "无",
            "AF3": "明细备注",
            "AG3": 0,
            "AH3": 0,
            "AI3": "否",
            "AJ3": "否",
            "AK3": str(uuid.UUID("11111111-2222-3333-4444-555555555555")),
            "AL3": "材料",
            "AM3": "材质",
            "AN3": "铝管",
            "AP3": "历史特殊说明",
            "AQ3": "同意",
            "AS3": "历史备注",
            "AU3": "2026-09-02 10:00:00",
            "AY3": "2026-09-02 11:00:00",
            "BC3": "2026-09-02 12:00:00",
            "BJ3": 100,
            "BR3": "2026-09-02 09:00:00",
            "BS3": "2026-09-02 12:00:00",
            "BT3": "流转完成",
        }
        for cell, value in values.items():
            sheet[cell] = value
        workbook.save(path)

    def _create_existing_sample(self, media_root):
        customer = CustomerAccount.objects.create(
            account_code="OLD_SAMPLE_CUSTOMER",
            account_name="旧样品客户",
        )
        sample = SampleRequest.objects.create(
            customer_account=customer,
            owner_employee=self.import_employee,
            request_number="HTS-OLD-001",
            requested_at=timezone.now(),
        )
        storage_key = "samples/old-task.png"
        target = Path(media_root) / storage_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"old sample task")
        business_file = BusinessFile.objects.create(
            uploaded_by_employee=self.import_employee,
            original_name="old-task.png",
            storage_key=storage_key,
            content_type="image/png",
            size_bytes=15,
            scan_status=FileScanStatus.CLEAN,
        )
        SampleProduct.objects.create(
            sample_request=sample,
            line_number=1,
            product_name="旧产品",
            task_sheet_file=business_file,
        )
        return sample, business_file, target

    def test_dry_run_parses_corrections_without_writing_samples(self):
        stdout = io.StringIO()
        call_command(
            "import_sample_workbook",
            str(self.workbook_path),
            expect_samples=1,
            stdout=stdout,
        )

        plan = build_sample_workbook_import_plan(self.workbook_path)
        self.assertEqual(SampleRequest.objects.count(), 0)
        self.assertEqual(plan.samples[0]["manual_request_number"], "26008")
        self.assertEqual(plan.samples[0]["request_number"], "HTS-26008")
        self.assertEqual(plan.samples[0]["status"], SampleRequestStatus.FINISHED)
        self.assertEqual(len(plan.corrections), 2)
        self.assertEqual(plan.samples[0]["items"][0]["id"], uuid.UUID("11111111-2222-3333-4444-555555555555"))
        self.assertEqual(plan.samples[0]["items"][0]["color_card"], "潘通定色")
        self.assertEqual(plan.samples[0]["items"][0]["product_color_id"], self.product_color.pk)
        self.assertEqual(plan.samples[0]["sampling_details"][0]["category_label"], "材质")
        self.assertTrue(plan.samples[0]["sampling_details"][0]["is_selected"])
        self.assertIn('"mode":"dry-run"', stdout.getvalue())

    def test_apply_replaces_existing_sample_and_imports_all_related_rows(self):
        with override_settings(MEDIA_ROOT=self.temp_dir.name):
            old_sample, old_file, physical_file = self._create_existing_sample(self.temp_dir.name)
            plan = build_sample_workbook_import_plan(self.workbook_path)
            result = execute_sample_workbook_import(plan, expected_existing=1)

        self.assertFalse(SampleRequest.objects.filter(pk=old_sample.pk).exists())
        self.assertFalse(BusinessFile.objects.filter(pk=old_file.pk).exists())
        self.assertFalse(physical_file.exists())
        imported = SampleRequest.objects.get(request_number="HTS-26008")
        self.assertEqual(imported.manual_request_number, "26008")
        self.assertEqual(imported.owner_employee, self.import_employee)
        self.assertEqual(imported.status, SampleRequestStatus.FINISHED)
        self.assertEqual(SampleProduct.objects.filter(sample_request=imported).count(), 1)
        self.assertEqual(SampleItem.objects.filter(sample_request=imported).count(), 1)
        self.assertEqual(SampleProductSamplingDetail.objects.filter(sample_product__sample_request=imported).count(), 1)
        self.assertEqual(SampleWorkflowRecord.objects.filter(sample_request=imported).count(), 7)
        fee = SampleFeeRecord.objects.get(sample_request=imported)
        self.assertEqual(fee.currency_code, "CNY")
        self.assertEqual(fee.amount, 100)
        self.assertEqual(fee.verification_status, FeeVerificationStatus.MANUALLY_CONFIRMED)
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["created_categories"], [MISSING_CATEGORY_NAME])
        self.assertEqual(result["storage_cleanup"], [{"storage_key": "samples/old-task.png", "status": "deleted"}])

    def test_expected_existing_guard_leaves_current_data_untouched(self):
        with override_settings(MEDIA_ROOT=self.temp_dir.name):
            old_sample, old_file, physical_file = self._create_existing_sample(self.temp_dir.name)
            plan = build_sample_workbook_import_plan(self.workbook_path)
            with self.assertRaises(SampleWorkbookImportError):
                execute_sample_workbook_import(plan, expected_existing=2)

        self.assertTrue(SampleRequest.objects.filter(pk=old_sample.pk).exists())
        self.assertTrue(BusinessFile.objects.filter(pk=old_file.pk).exists())
        self.assertTrue(physical_file.exists())

    def test_failure_after_delete_rolls_back_database_and_keeps_file(self):
        with override_settings(MEDIA_ROOT=self.temp_dir.name):
            old_sample, old_file, physical_file = self._create_existing_sample(self.temp_dir.name)
            plan = build_sample_workbook_import_plan(self.workbook_path)
            with patch(
                "apps.samples.workbook_import.ProductCategory.objects.get_or_create",
                side_effect=RuntimeError("forced import failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "forced import failure"):
                    execute_sample_workbook_import(plan, expected_existing=1)

        self.assertTrue(SampleRequest.objects.filter(pk=old_sample.pk).exists())
        self.assertTrue(BusinessFile.objects.filter(pk=old_file.pk).exists())
        self.assertTrue(physical_file.exists())
