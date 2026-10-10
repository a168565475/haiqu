"""排产的成品进度依据入库原单，不依据装配报工或库存余量。"""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APITestCase

from apps.inventory.models import FinishedGoodsReceipt
from apps.inventory.tests import test_assembly_receipts as receipt_fixtures
from apps.inventory.tests import test_inventory_api as inventory_fixtures
from apps.inventory.tests.assembly_reporting_fixture import seed_reported_assembly


class ScheduleFinishedProgressTests(receipt_fixtures.AssemblyFixture, APITestCase):
    def setUp(self):
        with patch("apps.inventory.tests.assembly_reporting_fixture.seed_reported_assembly", return_value=None):
            self.prepare()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))

    def progress(self):
        response = self.client.get("/api/v1/workshop-reporting/schedule-progress-statuses/", {
            "schedule_ids": str(self.schedule.pk),
        })
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"][0]["progress"]["ASSEMBLY"]

    def test_no_wage_scheme_or_receipt_starts_at_zero(self):
        self.assertEqual(self.progress(), {"status": "READY", "percentage": 0, "display": "0%"})

    def test_reporting_alone_does_not_advance_but_actual_receipts_do(self):
        seed_reported_assembly(self.line, self.employee, plan=self.plan)
        self.assertEqual(self.progress()["percentage"], 0)
        self.assertEqual(self.post(self.payload(received_quantity=4)).status_code, 201)
        self.assertEqual(self.progress()["percentage"], 40)
        self.assertEqual(self.post(self.payload(received_quantity=6)).status_code, 201)
        self.assertEqual(self.progress()["percentage"], 100)
        self.assertEqual(self.post(self.payload(received_quantity=1)).status_code, 201)
        self.assertEqual(self.progress()["percentage"], 100)
        # 已出库会减少库存余量，但不能抹掉已完成的入库事实。
        FinishedGoodsReceipt.objects.update(remaining_quantity=0)
        self.assertEqual(self.progress()["percentage"], 100)

    def test_multiple_products_and_legacy_receipt_entry_share_totals(self):
        seed_reported_assembly(self.line, self.employee, plan=self.plan)
        second = inventory_fixtures.FinishedGoodsInventoryApiTests.create_second_line(self)
        second.quantity = 30
        second.save(update_fields=["quantity"])
        seed_reported_assembly(second, self.employee)
        self.assertEqual(self.post(self.payload(received_quantity=4)).status_code, 201)
        self.assertEqual(self.progress()["percentage"], 10)
        payload = inventory_fixtures.FinishedGoodsInventoryApiTests.receipt_payload(
            self, production_task_product_id=str(second.pk), received_quantity=6, quantity_per_box=None,
        )
        response = self.client.post("/api/v1/finished-goods-inventory/receipts/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.progress()["percentage"], 25)

    def test_parameter_and_existing_read_permission_boundary(self):
        url = "/api/v1/workshop-reporting/schedule-progress-statuses/"
        self.assertEqual(self.client.get(url, {"schedule_ids": "bad"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"schedule_ids": str(uuid.uuid4())}).data["data"], [])
        self.user.user_permissions.remove(*Permission.objects.filter(content_type__app_label="production_scheduling"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get(url, {"schedule_ids": str(self.schedule.pk)}).status_code, 403)
