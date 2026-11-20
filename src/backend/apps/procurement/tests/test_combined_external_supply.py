from decimal import Decimal

from rest_framework.test import APITestCase

from ..external_supply import sync_external_supply
from ..models import PurchaseOrder
from .test_multi_product_purchase import MultiProductPurchaseFixture


class CombinedExternalSupplyTests(MultiProductPurchaseFixture, APITestCase):
    def choose(self, bom, line, purchase_required):
        line.raw_values = {**line.raw_values, "purchase_required": purchase_required}
        line.save()
        sync_external_supply(bom, [line], actor_employee=self.employee, request=None)

    def test_externalizing_first_then_all_contributions_keeps_history_and_restores_original_row(self):
        self.create_group()
        confirmed = self.batch("30")
        draft = self.batch("20", confirm=False)
        self.choose(self.red_bom, self.red_screw, False)
        progress, = self.detail().data["data"]["progress"]["lines"]
        self.assertEqual(progress["id"], self.line_id)
        self.assertEqual(Decimal(progress["required_quantity"]), 400)
        self.assertEqual(Decimal(progress["remaining_purchase_quantity"]), 350)
        self.assertEqual(PurchaseOrder.objects.get(pk=draft["id"]).lines.count(), 1)
        self.assertEqual(PurchaseOrder.objects.get(pk=confirmed["id"]).lines.count(), 1)
        result = self.client.post(f"/api/v1/purchase-orders/{draft['id']}/confirm/", {}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        second_draft = self.batch("10", confirm=False)
        self.choose(self.blue_bom, self.blue_screw, False)
        self.assertEqual(self.detail().data["data"]["progress"]["external_supply_line_ids"], [self.line_id])
        self.assertEqual(PurchaseOrder.objects.get(pk=second_draft["id"]).lines.count(), 0)
        self.receive(confirmed, "30")
        self.choose(self.red_bom, self.red_screw, True)
        self.choose(self.blue_bom, self.blue_screw, True)
        progress, = self.detail().data["data"]["progress"]["lines"]
        self.assertEqual(progress["id"], self.line_id)
        self.assertEqual(Decimal(progress["remaining_purchase_quantity"]), 1950)
