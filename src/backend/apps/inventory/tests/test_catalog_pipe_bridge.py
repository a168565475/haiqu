"""根米接口纠偏的直接回归；真实独占 PostgreSQL 与原领料 API。"""
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.material_catalog.models import MaterialCatalog
from apps.material_issues.catalog_requirements import catalog_requirement_specs
from apps.material_issues.models import MaterialIssue
from ..catalog_stock_identity import build_catalog_stock_identity
from ..catalog_stock_queries import available_catalog_balances
from ..models import MaterialInbound, PublicStockBalance
from .test_public_stock_services import PublicStockFixture


@override_settings(PUBLIC_STOCK_ISSUES_ENABLED=True)
class CatalogPipeBridgeTests(PublicStockFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="根米桥接管材")
        self.saved = {"schema_version": 1, "catalog_id": str(self.catalog.pk), "catalog_version": self.catalog.updated_at.isoformat(),
            "category_key": "TUBE", "template_key": "TUBE", "name": self.catalog.name, "scope": "BASE",
            "processing_state": "RAW", "processing_stage": "RAW", "completed_craft": None, "semi_kind": None,
            "attributes": {"material": "铁", "shape": "圆管", "section_size": "20", "thickness": "1", "length": "6000"},
            "unit_id": str(self.root_unit.pk), "unit_name": "根", "display_name": "根米桥接管材 / 根"}

    def identity(self, length):
        return build_catalog_stock_identity(material_catalog_id=self.catalog.pk,
            material_selection_snapshot=self.saved, raw_bar_length_m=length)

    def test_actual_length_required_not_inferred_from_attribute(self):
        for length in (None, "0", "3.051", "NaN", True):
            with self.subTest(length=length), self.assertRaises(ValidationError):
                self.identity(length)

    def test_lengths_separate_and_query_can_select_exact_batch_length(self):
        long = self.credit(3, identity=self.identity("6.00")).balance
        short = self.credit(2, identity=self.identity("3.05")).balance
        self.assertNotEqual(long.pk, short.pk)
        self.assertEqual(long.meter_quantity, 18)
        self.assertEqual(short.meter_quantity, Decimal("6.10"))
        args = {"material_catalog_id": self.catalog.pk, "material_selection_snapshot": self.saved}
        self.assertEqual(len(available_catalog_balances(**args)), 2)
        exact = available_catalog_balances(**args, raw_bar_length_m="3.05")
        self.assertEqual([row["balance_id"] for row in exact], [str(short.pk)])
        self.debit(short.pk, 1)
        short.refresh_from_db()
        self.assertEqual((short.quantity, short.meter_quantity), (1, Decimal("3.05")))

    def test_manual_root_input_creates_meter_receipt_and_root_stock(self):
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="material_catalog"))
        payload = {"client_request_id": str(uuid4()), "inbound_date": str(timezone.localdate()), "remark": "根米桥接",
            "items": [{"material_catalog_id": str(self.catalog.pk), "zone_id": str(self.zone.pk),
                "received_bar_count": 3, "raw_bar_length_m": "6.00", "material_selection": {
                    "catalog_version": self.catalog.updated_at.isoformat(), "scope": "BASE", "processing_state": "RAW",
                    "unit_id": str(self.root_unit.pk), "attributes": self.saved["attributes"]}}]}
        response = self.client.post("/api/v1/material-inventory/manual-receipts/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        line = MaterialInbound.objects.get().lines.get()
        self.assertEqual((line.measurement_kind, line.source_unit_text_snapshot), ("PIPE", "米"))
        self.assertEqual((line.received_bar_count, line.received_quantity), (3, 18))
        self.assertIsNone(line.raw_material_information_id)
        balance = PublicStockBalance.objects.get()
        self.assertEqual((balance.quantity, balance.meter_quantity, balance.raw_bar_length_m), (3, 18, 6))
        self.assertEqual(self.client.post("/api/v1/material-inventory/manual-receipts/", payload, format="json").status_code, 201)
        self.assertEqual(MaterialInbound.objects.count(), 1)

    def make_issue(self, length):
        self.bom_line.material_catalog = self.catalog
        self.bom_line.material_selection_snapshot = self.saved
        self.bom_line.raw_values["pipe_plan_version"] = 3
        self.bom_line.material_quantity = None
        self.bom_line.unit = "根"
        self.bom_line.save()
        self.credit(10, identity=self.identity(length))
        specs, blockers = catalog_requirement_specs(self.task.pk, self.product_line.pk)
        self.assertFalse(blockers, blockers)
        return self.client.post("/api/v1/material-issues/", {
            "client_request_id": str(uuid4()), "schedule_product_id": str(self.schedule_product.pk), "plan_category": "METAL",
            "production_task_id": str(self.task.pk), "product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk),
            "recipient_workshop_employee_id": str(self.recipient.pk), "issue_at": timezone.now().isoformat(),
            "lines": [{"requirement_id": str(specs[0]["id"]), "requested_quantity": "12"}]}, format="json")

    def test_issue_preserves_piece_to_root_allocation_and_saved_length(self):
        created = self.make_issue(self.bom_line.raw_bar_length_m)
        self.assertEqual(created.status_code, 201, created.data)
        identifier = created.data["data"]["id"]
        submitted = self.client.post(f"/api/v1/material-issues/{identifier}/submit/", {}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        preview = self.client.post(f"/api/v1/material-issues/{identifier}/preview-issue/", {}, format="json")
        self.assertTrue(preview.data["data"]["can_confirm"], preview.data)
        confirmed = self.client.post(f"/api/v1/material-issues/{identifier}/confirm-issue/", {"request_id": str(uuid4())},
            format="json", HTTP_IF_MATCH=submitted["ETag"])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        line = MaterialIssue.objects.get(pk=identifier).lines.get()
        self.assertEqual(line.unit_snapshot, "支")
        self.assertEqual(Decimal(line.conversion_snapshot["manufacturing_issued_pieces"]), 12)
        self.assertEqual(line.public_stock_allocations.get().stock_quantity, 2)
        self.assertEqual(line.public_stock_allocations.get().meter_quantity, 2 * Decimal(self.bom_line.raw_bar_length_m))
        balance = PublicStockBalance.objects.get()
        self.assertEqual(balance.quantity, 8)
        self.assertEqual(balance.meter_quantity, 8 * Decimal(self.bom_line.raw_bar_length_m))

    def test_issue_never_falls_back_to_a_different_length_pool(self):
        created = self.make_issue("6.00")
        self.assertEqual(created.status_code, 400, created.data)
        self.assertFalse(MaterialIssue.objects.exists())
        self.assertEqual(PublicStockBalance.objects.get().quantity, 10)
