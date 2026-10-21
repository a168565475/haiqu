import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.organizations.models import Employee

from ..api.detail_serializers import ScheduleDetailSummaryResponseSerializer
from ..detail_summary import _total
from ..models import ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft


class CompleteSummaryTotalTests(SimpleTestCase):
    def test_sum_decimal_amounts_and_preserve_real_zero(self):
        self.assertEqual(_total(["0.00", "0"]), "0.00")
        self.assertEqual(_total(["0.1", "0.2", "123456789012345.67"]), "123456789012345.97")

    def test_unknown_amount_is_not_a_partial_or_zero_total(self):
        self.assertIsNone(_total(["10.00", None]))
        self.assertIsNone(_total([]))


class ScheduleDetailSummaryApiTests(APITestCase):
    def setUp(self):
        from .test_production_scheduling_api import ProductionSchedulingApiTests

        ProductionSchedulingApiTests.setUp(self)
        today = timezone.localdate()
        self.schedule = ProductionSchedule.objects.create(
            schedule_number="PC-DETAIL-SUMMARY", production_task=self.task,
            client_request_id=uuid.uuid4(), source_revision_hash="a" * 64,
            request_payload_hash="b" * 64, created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        self.schedule_product = ProductionScheduleProduct.objects.create(
            schedule=self.schedule, product_line=self.line, line_number=1,
            planned_quantity=100, source_quantity_snapshot=100, unit=self.product.unit,
            unit_name_snapshot=self.product.unit.unit_name,
            product_snapshot={"product_name": "测试产品", "specification": "47*55*79；颜色：酒红色；材质：PE", "color_name": "酒红色"},
            material_inbound_date=today, metal_return_date=today + timedelta(days=1),
            sewing_return_date=today + timedelta(days=2), finished_inbound_date=today + timedelta(days=3),
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=self.schedule_product, craft=self.internal_craft,
            craft_type_snapshot="INTERNAL", craft_name_snapshot=self.internal_craft.name,
            plan_category="METAL",
        )
        self.url = f"/api/v1/production-schedules/{self.schedule.pk}/detail-summary/"

    def test_authenticated_read_returns_summary_without_granting_source_permissions(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        body = response.data["data"]
        self.assertEqual(body["schedule_id"], str(self.schedule.pk))
        self.assertEqual(len(body["products"]), 1)
        product = body["products"][0]
        self.assertFalse(product["outsourcing"]["allowed"])
        self.assertFalse(product["material_issues"]["allowed"])
        self.assertIsNone(product["estimated_wage"])
        self.assertIsNone(product["reported_amount"])
        self.assertIsNone(body["totals"]["estimated_wage"])
        serializer = ScheduleDetailSummaryResponseSerializer(data=response.data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_no_session_is_rejected(self):
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_source_permission_does_not_grant_schedule_permission(self):
        self.user.user_permissions.clear()
        self.user.user_permissions.add(Permission.objects.get(codename="view_workreport"))
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_inaccessible_schedule_is_not_exposed(self):
        other = get_user_model().objects.create_user(username="detail-unrelated")
        Employee.objects.create(user=other, employee_code="DETAIL-OTHER", display_name="无关员工")
        other.user_permissions.add(Permission.objects.get(codename="view_productionschedule"))
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_product_display_separates_specification_without_mutating_snapshot(self):
        self.line.material_snapshot = "PE"
        self.line.save(update_fields=["material_snapshot", "updated_at"])
        response = self.client.get(f"/api/v1/production-schedules/{self.schedule.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        product = response.data["data"]["products"][0]["product"]
        self.assertEqual(product["specification_display"], "47*55*79")
        self.assertEqual(product["color_name"], "酒红色")
        self.assertEqual(product["material"], "PE")
        self.schedule_product.refresh_from_db()
        self.assertIn("材质：PE", self.schedule_product.product_snapshot["specification"])
        self.assertNotIn("material", self.schedule_product.product_snapshot)
