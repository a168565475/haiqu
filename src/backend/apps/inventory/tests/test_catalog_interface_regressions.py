"""共同接口回归：缓存状态不能代替已锁定数据库状态，新半成品不能绕过额度。"""
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.material_catalog.models import MaterialCatalog
from ..catalog_receipts import credit_catalog_inbound
from ..internal_receipt_limits import validate_combined_output
from ..models import MaterialInbound, PublicStockBalance, PublicStockMovement
from .test_public_stock_services import PublicStockFixture


class CatalogInterfaceRegressionTests(PublicStockFixture, TestCase):
    def manual_line(self):
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="material_catalog"))
        catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="公共接口回归管材")
        response = self.client.post("/api/v1/material-inventory/manual-receipts/", {
            "client_request_id": str(uuid4()), "inbound_date": str(timezone.localdate()), "remark": "公共接口回归",
            "items": [{"material_catalog_id": str(catalog.pk), "zone_id": str(self.zone.pk), "received_bar_count": 3, "raw_bar_length_m": "6.00",
                "material_selection": {"catalog_version": catalog.updated_at.isoformat(), "scope": "BASE",
                    "processing_state": "RAW", "unit_id": str(self.root_unit.pk),
                    "attributes": {"material": "铁", "shape": "圆管", "section_size": "20", "thickness": "1", "length": "6000"}}}]}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return MaterialInbound.objects.get().lines.select_related("inbound").get()

    def test_confirmed_database_state_overrides_pending_relation_cache(self):
        line = self.manual_line()
        original = PublicStockMovement.objects.get()
        line.inbound.status = "PENDING_QUALITY"
        movement = credit_catalog_inbound(line=line, actor_employee=self.employee)
        self.assertEqual(movement.pk, original.pk)
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 3)

    def test_pending_database_state_rejects_confirmed_relation_cache(self):
        line = self.manual_line()
        MaterialInbound.objects.filter(pk=line.inbound_id).update(status="PENDING_QUALITY")
        self.assertEqual(line.inbound.status, "CONFIRMED")
        with self.assertRaises(ValidationError):
            credit_catalog_inbound(line=line, actor_employee=self.employee)
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 3)

    def test_catalog_semi_cannot_bypass_combined_output_limit(self):
        source = {"source_type": "INTERNAL_SEMI_RECEIPT", "source_id": uuid4(), "source_line_id": uuid4(),
            "production_task_id": self.task.pk, "product_line_id": self.product_line.pk, "bom_line_id": self.bom_line.pk}
        identity = {"stock_kind": "CATALOG_SEMI", "identity_snapshot": {"completed_craft": {"code": "METAL"}}}
        required = self.product_line.quantity * self.bom_line.pieces_per_product
        validate_combined_output(source=source, identity=identity, quantity=required, quality="AVAILABLE")
        self.assert_error("INTERNAL_RECEIPT_DEMAND_EXCEEDED", lambda: validate_combined_output(
            source=source, identity=identity, quantity=required + 1, quality="AVAILABLE"))
