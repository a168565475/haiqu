import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from openpyxl import Workbook

from apps.customers.models import (
    AssignmentRole,
    ContactMethodType,
    CustomerAccount,
    CustomerAssignment,
    CustomerContact,
)
from apps.files.models import BusinessFile, FileScanStatus
from apps.imports.ente_customer_import import build_import_plan, execute_import, plan_summary
from apps.imports.models import ImportBatch, ImportBatchStatus, ImportRecord
from apps.organizations.models import Employee


class EnteCustomerImportTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.source_path = Path(self.temporary_directory.name) / "ente-customers.xlsx"
        self._create_workbook(self.source_path)

    @staticmethod
    def _create_workbook(path):
        workbook = Workbook()
        customers = workbook.active
        customers.title = "客户信息"
        customers.append(
            [
                "序号", "客户代码", "系统唯一标识", "客户名称", "客户简称", "客户类型",
                "客户等级", "客户来源", "所属业务员", "业务员代码", "区域代码", "网站",
                "所属行业", "国家/地区", "最后联系时间", "读取完整性", "未完整原因", "联系人数量",
            ]
        )
        customers.append(
            [
                1, 26614, "ente-system-id-1", "意大利测试客户", None, "潜在客户", "★询价",
                "阿里国际", "申佳明;仇鑫", "0007;0007", "3", "www.example.com",
                "国外最终客户", "欧洲", "2026-05-20 16:00", "完整", None, 1,
            ]
        )
        contacts = workbook.create_sheet("联系人信息")
        contacts.append(
            [
                "客户代码", "客户名称", "系统唯一标识", "联系人序号", "联系人", "职位",
                "邮箱", "手机", "电话", "办公电话", "宅电", "WhatsApp", "微信",
                "是否主联系人", "部门", "备注", "性别", "QQ", "读取完整性", "未完整原因",
            ]
        )
        contacts.append(
            [
                26614, "意大利测试客户", "ente-system-id-1", 1, "Anna  Rossi", "采购经理",
                "anna@example.com", None, None, None, None, None, None, "Y", "采购部", None,
                "女", "123456", "完整", None,
            ]
        )
        workbook.save(path)
        workbook.close()

    def _fake_scan(self, uploaded_file, actor_employee):
        business_file = BusinessFile.objects.create(
            uploaded_by_employee=actor_employee,
            original_name=uploaded_file.name,
            storage_key=f"tests/{uuid.uuid4()}.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=uploaded_file.size,
            content_hash="test-hash",
            scan_status=FileScanStatus.CLEAN,
            scan_message="stream: OK",
        )
        return business_file, self.source_path

    def test_plan_preserves_nonempty_legacy_fields_and_internal_name_spaces(self):
        plan = build_import_plan(self.source_path)

        self.assertEqual(plan["customer_count"], 1)
        self.assertEqual(plan["contact_count"], 1)
        self.assertEqual(plan["customers"][0]["grade_code"], "F")
        self.assertEqual(plan["customers"][0]["country_code"], "")
        self.assertEqual(plan["customers"][0]["region_selector_code"], "3")
        self.assertEqual(plan["customers"][0]["industry_code"], "FOREIGN_END_CUSTOMER")
        self.assertEqual(plan["customers"][0]["legacy_source_data"]["mapped_values"]["区域代码"], "3")
        self.assertEqual(plan["customers"][0]["legacy_source_data"]["mapped_values"]["所属行业"], "国外最终客户")
        self.assertNotIn("客户简称", plan["customers"][0]["legacy_source_data"]["fields"])
        contact = plan["customers"][0]["contacts"][0]
        self.assertEqual(contact["display_name"], "Anna  Rossi")
        self.assertEqual(contact["legacy_source_data"]["fields"], {"性别": "女", "QQ": "123456"})

    @patch("apps.imports.ente_customer_import.save_and_scan_upload")
    def test_execute_import_creates_customer_contacts_assignments_and_audit(self, mock_scan):
        mock_scan.side_effect = self._fake_scan
        plan = build_import_plan(self.source_path)

        result = execute_import(plan)

        self.assertEqual(result["status"], ImportBatchStatus.COMPLETED)
        customer = CustomerAccount.objects.get(source_system="ENTE_ERP", external_id="ente-system-id-1")
        self.assertEqual(customer.account_name, "意大利测试客户")
        self.assertEqual(customer.primary_country_code, "")
        self.assertEqual(customer.primary_website_url, "https://www.example.com")
        self.assertEqual(customer.primary_region.region_name, "欧洲")
        self.assertIsNone(customer.secondary_region)
        self.assertEqual(customer.industry_item.item_code, "FOREIGN_END_CUSTOMER")
        self.assertEqual(customer.legacy_source_data["mapped_values"]["所属行业"], "国外最终客户")
        self.assertEqual(customer.legacy_source_data["mapped_values"]["区域代码"], "3")
        self.assertEqual(customer.grade_reviews.get(effective_to__isnull=True).grade_item.item_code, "F")
        self.assertEqual(customer.source_attributions.get(effective_to__isnull=True).source_item.item_code, "ALIBABA_INTERNATIONAL")
        self.assertEqual(customer.type_assignments.get(effective_to__isnull=True).type_item.item_code, "POTENTIAL")
        self.assertEqual(
            customer.activity_reviews.get(effective_to__isnull=True).activity_status,
            "FOLLOW_UP",
        )

        assignments = CustomerAssignment.objects.filter(customer_account=customer).order_by("assignment_role")
        self.assertEqual(assignments.count(), 2)
        self.assertEqual(assignments.filter(assignment_role=AssignmentRole.PRIMARY_OWNER).count(), 1)
        self.assertEqual(assignments.filter(assignment_role=AssignmentRole.COLLABORATOR).count(), 1)
        self.assertTrue(Employee.objects.filter(employee_code="ENTE_0007_01", display_name="申佳明").exists())
        self.assertTrue(Employee.objects.filter(employee_code="ENTE_0007_02", display_name="仇鑫").exists())

        contact = CustomerContact.objects.get(customer_account=customer)
        self.assertEqual(contact.display_name, "Anna  Rossi")
        self.assertTrue(contact.is_primary_contact)
        self.assertEqual(contact.legacy_source_data["fields"], {"性别": "女", "QQ": "123456"})
        self.assertEqual(
            contact.methods.get(method_type=ContactMethodType.EMAIL).raw_value,
            "anna@example.com",
        )

        batch = ImportBatch.objects.get(pk=result["batch_id"])
        self.assertEqual(batch.total_count, 1)
        self.assertEqual(batch.success_count, 1)
        self.assertEqual(batch.failure_count, 0)
        record = ImportRecord.objects.get(import_batch=batch)
        self.assertEqual(record.raw_data["customer"]["客户代码"], 26614)
        self.assertEqual(plan_summary(plan)["existing_customer_count"], 1)
