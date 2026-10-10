"""成品颜色选填，覆盖装配、原入库入口与批量入库。"""
from rest_framework.test import APITestCase

from apps.inventory.models import FinishedGoodsReceipt
from apps.inventory.tests import test_assembly_receipts as assembly_fixtures
from apps.inventory.tests import test_inventory_api as inventory_fixtures


class FinishedReceiptOptionalColorTests(assembly_fixtures.AssemblyFixture, APITestCase):
    def setUp(self):
        self.prepare()
        self.line.color_name_snapshot = ""
        self.line.save(update_fields=["color_name_snapshot"])

    def test_blank_assembly_color_is_saved_and_replay_does_not_duplicate(self):
        self.assertEqual(self.preview()["actual_color"], "")
        payload = self.payload(actual_color="", received_quantity=2)
        etag = self.preview()["etag"]
        response = self.post(payload, etag)
        self.assertEqual(response.status_code, 201, response.data)
        replay = self.post(payload, etag)
        self.assertEqual(replay.status_code, 200, replay.data)
        receipt = FinishedGoodsReceipt.objects.get()
        self.assertEqual(receipt.actual_color, "")
        self.assertEqual(receipt.remaining_quantity, 2)
        record = self.client.get(f"/api/v1/finished-goods-records/{receipt.pk}/")
        self.assertEqual(record.status_code, 200, record.data)
        self.assertEqual(record.data["data"]["actual_color"], "")

    def test_missing_whitespace_and_existing_assembly_colors(self):
        for supplied, expected in [(None, ""), ("   ", ""), (" 深灰色 ", "深灰色")]:
            payload = self.payload(actual_color=supplied, received_quantity=1)
            if supplied is None:
                payload.pop("actual_color")
            response = self.post(payload)
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(FinishedGoodsReceipt.objects.get(pk=response.data["data"]["id"]).actual_color, expected)

    def test_original_single_and_batch_entries_allow_blank_colors(self):
        payload = inventory_fixtures.FinishedGoodsInventoryApiTests.receipt_payload(
            self, actual_color="", received_quantity=2, quantity_per_box=None,
        )
        response = self.client.post('/api/v1/finished-goods-inventory/receipts/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        payload.update(expected_received_total=2, actual_color="   ")
        response = self.client.post('/api/v1/finished-goods-inventory/batch-receipts/', {"items": [payload]}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(list(FinishedGoodsReceipt.objects.values_list('actual_color', flat=True)), ["", ""])

    def test_optional_color_does_not_relax_quantity_or_length_validation(self):
        for changes in [{"actual_color": "", "received_quantity": 0}, {"actual_color": "", "received_quantity": 12}, {"actual_color": "色" * 201}]:
            response = self.post(self.payload(**changes))
            self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(FinishedGoodsReceipt.objects.exists())
