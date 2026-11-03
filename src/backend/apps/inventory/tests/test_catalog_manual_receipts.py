from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone

from apps.material_catalog.models import MaterialCatalog
from ..models import MaterialInbound, PublicStockBalance, PublicStockMovement
from .test_public_stock_services import PublicStockFixture


class CatalogManualReceiptTests(PublicStockFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="material_catalog"))
        self.catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="手工入库新管材")
        self.payload = {"client_request_id": str(uuid4()), "inbound_date": str(timezone.localdate()), "remark": "盘盈入库",
            "items": [{"material_catalog_id": str(self.catalog.pk), "zone_id": str(self.zone.pk), "received_bar_count": 3, "raw_bar_length_m": "6.00",
                "material_selection": {"catalog_version": self.catalog.updated_at.isoformat(), "scope": "BASE",
                    "processing_state": "RAW", "unit_id": str(self.root_unit.pk),
                    "attributes": {"material": "铁", "shape": "圆管", "section_size": "20", "thickness": "1", "length": "6000"}}}]}

    def post(self, payload=None):
        return self.client.post("/api/v1/material-inventory/manual-receipts/", payload or self.payload, format="json")

    def test_options_added_and_original_version_retry_is_idempotent(self):
        version = self.catalog.updated_at
        first = self.post()
        self.assertEqual(first.status_code, 201, first.data)
        self.catalog.refresh_from_db()
        self.assertNotEqual(version, self.catalog.updated_at)
        self.assertEqual(self.post().data["data"]["id"], first.data["data"]["id"])
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        line = MaterialInbound.objects.get().lines.get()
        self.assertEqual(line.material_catalog_id, self.catalog.pk)
        self.assertIsNone(line.raw_material_information_id)
        self.assertEqual(line.source_unit_text_snapshot, "米")
        self.assertEqual(PublicStockBalance.objects.get().quantity, 3)
        listing = self.client.get("/api/v1/material-inventory/", {"q": "手工入库新管材"})
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(listing.data["count"], 1)
        row = listing.data["results"][0]
        self.assertEqual(row["material_catalog_id"], str(self.catalog.pk))
        self.assertEqual(row["unit"], "根")
        self.assertEqual(row["material_selection_snapshot"], line.material_selection_snapshot)
        url = f"/api/v1/material-inventory/{self.catalog.pk}"
        query = {"identity_key": row["identity_key"]}
        summary = self.client.get(f"{url}/summary/", query)
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(Decimal(summary.data["data"]["current_quantity"]), 3)
        self.assertEqual(summary.data["data"]["unit"], "根")
        self.assertEqual(self.client.get(f"{url}/order-purchases/", query).data["data"], [])
        self.assertEqual(self.client.get(f"{url}/order-issues/", query).data["data"], [])

    def test_same_request_cannot_change_selected_attribute_or_owner(self):
        self.assertEqual(self.post().status_code, 201)
        changed = deepcopy(self.payload)
        changed["items"][0]["material_selection"]["attributes"]["thickness"] = "2"
        self.assertEqual(self.post(changed).status_code, 409)
        from django.contrib.auth import get_user_model
        from apps.organizations.models import Employee
        other = get_user_model().objects.create_user(username="manual-other")
        Employee.objects.create(user=other, employee_code="MANUAL_OTHER", display_name="其他员工")
        other.user_permissions.set(self.user.user_permissions.all())
        self.client.force_authenticate(other)
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(PublicStockMovement.objects.count(), 1)

    def test_root_quantity_keeps_meters_as_auxiliary(self):
        item = self.payload["items"][0]
        item.pop("received_quantity", None)
        item.update(received_bar_count=3, raw_bar_length_m="6.00")
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        line = MaterialInbound.objects.get().lines.get()
        self.assertEqual(line.received_quantity, 18)
        self.assertEqual(Decimal(line.calculation_snapshot["received_meters"]), 18)
        self.assertEqual(PublicStockBalance.objects.get().meter_quantity, 18)
        self.assertEqual(self.post().status_code, 201)

    def test_invalid_zone_rolls_back_directory_options_and_inbound(self):
        self.payload["items"][0]["zone_id"] = str(self.semi_zone.pk)
        response = self.post()
        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(self.catalog.attribute_values.exists())
        self.assertFalse(MaterialInbound.objects.exists())
        self.assertFalse(PublicStockBalance.objects.exists())

    def test_old_and_new_identity_are_mutually_exclusive(self):
        self.payload["items"][0]["raw_material_id"] = str(self.raw_material.pk)
        response = self.post()
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(MaterialInbound.objects.exists())

    def test_decimal_unit_and_saved_balance_query_keep_unit_and_zone(self):
        from ..catalog_stock_queries import available_catalog_balances
        item = self.payload["items"][0]
        self.catalog.category_key = self.catalog.template_key = "HARDWARE"
        self.catalog.save()
        item["material_selection"]["catalog_version"] = self.catalog.updated_at.isoformat()
        item["material_selection"]["attributes"] = {"specification": "M8"}
        item.pop("received_bar_count")
        item.pop("raw_bar_length_m")
        item["received_quantity"] = "2.5000"
        item["material_selection"].pop("unit_id")
        item["material_selection"]["unit_name"] = "公斤"
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        line = MaterialInbound.objects.get().lines.get()
        self.catalog.name = "改名后的品名"
        self.catalog.save()
        args = {"material_catalog_id": self.catalog.pk, "material_selection_snapshot": line.material_selection_snapshot}
        rows = available_catalog_balances(**args, zone_id=self.zone.pk)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["quantity"], Decimal("2.5"))
        self.assertEqual(rows[0]["available_quantity"], Decimal("2.5"))
        self.assertEqual(rows[0]["reserved_quantity"], 0)
        self.assertEqual(rows[0]["unit_name"], "公斤")
        self.assertEqual(rows[0]["material_selection_snapshot"]["name"], "手工入库新管材")
        self.assertEqual(available_catalog_balances(**args, zone_id=self.semi_zone.pk), [])
