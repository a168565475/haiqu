import uuid
from datetime import date

from django.test import SimpleTestCase

from apps.inventory.api.material_transfers import MaterialTransferInputSerializer


class MaterialTransferSerializerTests(SimpleTestCase):
    def payload(self, **overrides):
        payload = {
            "client_request_id": str(uuid.uuid4()),
            "direction": "IN",
            "transfer_date": date.today().isoformat(),
            "remark": "盘点调整",
            "items": [{
                "material_catalog_id": str(uuid.uuid4()),
                "material_selection": {
                    "catalog_version": "2026-11-07T00:00:00Z",
                    "scope": "BASE",
                    "processing_state": "RAW",
                    "attributes": {"specification": "M8"},
                    "unit_name": "个",
                },
                "zone_id": str(uuid.uuid4()),
                "quantity": "2",
            }],
        }
        payload.update(overrides)
        return payload

    def test_accepts_general_inbound_payload(self):
        serializer = MaterialTransferInputSerializer(data=self.payload())

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rejects_blank_remark(self):
        serializer = MaterialTransferInputSerializer(data=self.payload(remark="   "))

        self.assertFalse(serializer.is_valid())
        self.assertIn("remark", serializer.errors)

    def test_rejects_more_than_one_hundred_lines(self):
        payload = self.payload(items=[])
        payload["items"] = [self.payload()["items"][0] for _ in range(101)]
        serializer = MaterialTransferInputSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("items", serializer.errors)
