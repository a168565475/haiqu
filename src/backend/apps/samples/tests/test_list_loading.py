from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.models import RoleActionGrant
from apps.access_control.sales_policy import access_for
from apps.files.models import BusinessFile
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.reference_data.models import ProductColor

from ..api.serializers import SampleRequestListSummarySerializer
from ..material_arrival_services import material_progress
from ..models import (
    SampleItem, SampleMaterialIssue, SampleMaterialProcurementRequest,
    SampleMaterialRequest, SampleProduct, SampleRequest, SampleShipment,
)
from ..selectors import sample_requests_with_context


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False)
class SampleListLoadingTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser("sample-list-admin", password="test")
        cls.employee = Employee.objects.create(user=cls.user, employee_code="SAMPLE_LIST_ADMIN", display_name="管理员")
        cls.file = BusinessFile.objects.create(
            original_name="sample.png", storage_key="sample-list-loading/sample.png",
            content_type="image/png", size_bytes=1, scan_status="CLEAN",
        )
        cls.color = ProductColor.objects.create(color_card="色卡", color_code="BLUE", color_name="蓝色")
        cls.samples = []
        for index in range(3):
            sample = SampleRequest.objects.create(
                request_number=f"SUMMARY-{index}", owner_employee=cls.employee,
                requested_by_employee=cls.employee, requested_at=timezone.now(),
                status="DIRECTOR_REVIEW", application_payload_hash="application",
                reference_image=cls.file, purpose="详情说明", notes="详情备注",
            )
            cls.samples.append(sample)
            for line in (1, 2):
                product = SampleProduct.objects.create(
                    sample_request=sample, line_number=line, product_name=f"产品 {line}",
                    specification="常规规格", category_name_snapshot="椅子", length_cm=50,
                    task_sheet_file=cls.file, product_image=cls.file,
                    product_selection_snapshot={"large_detail": "x" * 10000},
                )
                SampleItem.objects.create(
                    sample_request=sample, sample_product=product, line_number=line,
                    product_description_snapshot=f"产品 {line}", requested_quantity=line,
                    sample_quantity=line, unit_code="PCS", product_color=cls.color,
                )
            record = SampleMaterialRequest.objects.create(
                sample_request=sample, draft={"lines": [{"key": "material", "quantity": "4", "name": "材料"}]},
                warehouse_draft={"lines": [{"key": "material", "supplyQuantity": "0"}]},
                submitted_at=timezone.now(), reviewed_at=timezone.now(),
            )
            SampleMaterialProcurementRequest.objects.create(
                material_request=record, lines=[{"key": "material", "shortageQuantity": "4"}],
            )
            SampleMaterialIssue.objects.create(material_request=record, status="ISSUED" if index == 2 else "PENDING_CONFIRMATION")
            shipment_snapshot = {"recipient_snapshot": {"name": "测试收件人"}, "address_snapshot": {"address_line1": "测试地址"}}
            SampleShipment.objects.create(sample_request=sample, status="SHIPPED", shipped_at=timezone.now()-timedelta(days=1), **shipment_snapshot)
            SampleShipment.objects.create(sample_request=sample, status="DELIVERED", shipped_at=timezone.now(), **shipment_snapshot)

    def setUp(self):
        self.client.force_authenticate(self.user)

    def test_list_only_loads_summary_fields_and_has_no_per_row_queries(self):
        counts = []
        for page_size in (1, 50):
            self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get("/api/v1/sample-requests/", {"page_size": page_size})
            self.assertEqual(response.status_code, 200, response.data)
            counts.append(len(queries))
            sql = "\n".join(query["sql"] for query in queries)
            for table in (
                "business_file", "sample_product_sampling_detail", "sample_fee_record", "sample_approval_link",
                "sample_feedback", "sample_file_link", "sample_workflow_record", "sample_sla_link",
                "sample_task_link", "sample_material_issue_line", "sample_shipment_item", "sample_shipment_event",
            ):
                self.assertNotIn(f'"{table}"', sql)
            for field in ("product_selection_snapshot", "recipient_snapshot", "director_note"):
                self.assertNotIn(f'"{field}"', sql)
        self.assertEqual(counts[0], counts[1])
        row = response.data["data"][0]
        self.assertEqual(set(row), {
            "id", "request_number", "submitted_on", "customer_name", "owner", "status", "status_display",
            "sample_type_display", "sample_due_date", "requested_at", "requested_due_at", "products",
            "item_summary", "application_actions", "material_summary", "allowed_permissions", "latest_shipment",
        })
        self.assertEqual(set(row["owner"]), {"id", "display_name"})
        self.assertEqual(set(row["products"][0]), {
            "id", "line_number", "category_name", "product_name", "specification", "color", "total_sample_quantity",
        })
        self.assertEqual(row["products"][0]["color"], "色卡 / BLUE / 蓝色")
        self.assertEqual([product["total_sample_quantity"] for product in row["products"]], [1, 2])
        self.assertEqual(row["latest_shipment"], {"status": "DELIVERED", "status_display": "已送达"})
        self.assertEqual(row["item_summary"], {"text": "产品 1 等 2 项", "count": 2})

    def test_preloaded_summary_serialization_does_not_fetch_deferred_fields(self):
        samples = list(sample_requests_with_context(list_mode=True))
        request = SimpleNamespace(user=self.user, employee=self.employee)
        access_for(request)
        with self.assertNumQueries(0):
            data = SampleRequestListSummarySerializer(samples, many=True, context={"request": request}).data
        self.assertEqual(len(data), 3)
        self.assertTrue(all(row["application_actions"]["can_director_review"] for row in data))

    def test_detail_keeps_full_form_and_product_contract(self):
        detail = self.client.get(f"/api/v1/sample-requests/{self.samples[0].pk}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        row = detail.data["data"]
        self.assertIn("edit_capabilities", row)
        self.assertIn("current_fee", row)
        self.assertIn("workflow_records", row)
        self.assertEqual(row["purpose"], "详情说明")
        self.assertEqual(row["products"][0]["length_cm"], "50.00")
        self.assertEqual(row["products"][0]["task_sheet_file_name"], "sample.png")
        self.assertIn("details", row["products"][0])
        self.assertIn("sampling_details", row["products"][0])

    def test_legacy_items_remain_visible_without_product_rows(self):
        legacy = SampleRequest.objects.create(
            request_number="SUMMARY-LEGACY", owner_employee=self.employee, requested_at=timezone.now(),
        )
        SampleItem.objects.create(
            sample_request=legacy, line_number=1, product_description_snapshot="历史样品",
            requested_quantity=1, unit_code="PCS",
        )
        response = self.client.get("/api/v1/sample-requests/", {"q": "SUMMARY-LEGACY"})
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["data"][0]
        self.assertEqual(row["products"], [])
        self.assertEqual(row["item_summary"]["text"], "历史样品")
        self.assertIsNone(row["material_summary"])
        self.assertFalse(row["application_actions"]["is_application"])

    def test_scoped_permissions_and_actions_match_detail(self):
        user = get_user_model().objects.create_user("sample-list-owner")
        owner = Employee.objects.create(user=user, employee_code="SAMPLE_LIST_OWNER", display_name="业务员")
        group = Group.objects.create(name="样品列表本人权限")
        role = RoleProfile.objects.create(auth_group=group, role_code="SAMPLE_LIST_OWNER", display_name="本人权限")
        EmployeeRoleAssignment.objects.create(employee=owner, role_profile=role, effective_from=timezone.now())
        for code in ("view_samplerequest", "review_sample_application"):
            permission = Permission.objects.get(content_type__app_label="samples", codename=code)
            group.permissions.add(permission)
            RoleActionGrant.objects.create(role=role, permission=permission, scope="OWN")
        sample = SampleRequest.objects.create(
            request_number="SUMMARY-OWN", owner_employee=owner, requested_by_employee=owner,
            requested_at=timezone.now(), status="DIRECTOR_REVIEW", application_payload_hash="application",
        )
        self.client.force_authenticate(user)
        listed = self.client.get("/api/v1/sample-requests/")
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual([row["id"] for row in listed.data["data"]], [str(sample.pk)])
        row = listed.data["data"][0]
        detail = self.client.get(f"/api/v1/sample-requests/{sample.pk}/").data["data"]
        self.assertEqual(row["allowed_permissions"], detail["allowed_permissions"])
        for key, value in row["application_actions"].items():
            self.assertEqual(value, detail["application_actions"][key])
        self.assertTrue(row["application_actions"]["can_director_review"])
        self.assertFalse(row["application_actions"]["can_edit_materials"])

    def test_material_summary_preserves_state_priority(self):
        sample = self.samples[0]
        record = SampleMaterialRequest.objects.get(sample_request=sample)
        issue = SampleMaterialIssue.objects.get(material_request=record)
        cases = [
            (False, "PENDING_CONFIRMATION", "MATERIAL_ISSUE_REVIEW"),
            (False, "ISSUED", "MATERIALS_ISSUED"),
            (True, "ISSUED", "MATERIALS_READY"),
        ]
        for no_materials, issue_status, expected in cases:
            with self.subTest(no_materials=no_materials, issue_status=issue_status):
                record.no_materials = no_materials
                record.submitted_at = None
                record.save(update_fields=["no_materials", "submitted_at"])
                issue.status = issue_status
                issue.save(update_fields=["status"])
                current = sample_requests_with_context(list_mode=True).get(pk=sample.pk)
                with self.assertNumQueries(0):
                    summary = material_progress(current, summary_only=True)
                full = material_progress(sample_requests_with_context().get(pk=sample.pk))
                self.assertEqual(summary["status"], expected)
                self.assertEqual({key: summary[key] for key in ("label", "status")}, {key: full[key] for key in ("label", "status")})

