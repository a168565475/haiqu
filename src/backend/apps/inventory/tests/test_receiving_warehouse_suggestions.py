from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.db.models import Q
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.test import APIRequestFactory

from apps.inventory.api.views import MaterialInventoryViewSet
from apps.inventory.selectors import material_receiving_warehouse_suggestions
from apps.procurement.models import PurchaseOrderLine


class ReceivingWarehouseSuggestionTests(SimpleTestCase):
    def setUp(self):
        self.raw = SimpleNamespace(pk=uuid4(), status="ACTIVE", warehouse_type="MATERIAL")
        self.semi = SimpleNamespace(pk=uuid4(), status="ACTIVE", warehouse_type="SEMI_FINISHED")
        self.catalog = SimpleNamespace(pk=uuid4(), base_warehouse=self.raw, base_warehouse_id=self.raw.pk,
                                       semi_warehouse=self.semi, semi_warehouse_id=self.semi.pk)
        self.catalog_query = patch("apps.inventory.selectors.MaterialCatalog.objects.filter").start()
        self.zone_query = patch("apps.inventory.selectors.WarehouseZone.objects.filter").start()
        self.addCleanup(patch.stopall)
        self.catalog_query.return_value.select_related.return_value = [self.catalog]
        self.zone_query.return_value.values_list.return_value = [self.raw.pk, self.semi.pk]

    def line(self, state="RAW"):
        return SimpleNamespace(pk=uuid4(), material_catalog_id=self.catalog.pk,
                               material_selection_snapshot={"processing_state": state, "scope": "BASE"})

    def test_frozen_state_selects_exact_default_without_mutating_snapshots(self):
        raw, semi = self.line(), self.line("PROCESSED")
        raw.material_selection_snapshot["scope"] = "SPRAY"
        before = deepcopy([raw.material_selection_snapshot, semi.material_selection_snapshot])
        result = material_receiving_warehouse_suggestions([raw, semi])
        self.assertEqual(result, {raw.pk: str(self.raw.pk), semi.pk: str(self.semi.pk)})
        self.assertEqual([raw.material_selection_snapshot, semi.material_selection_snapshot], before)

    def test_unusable_default_never_falls_back_to_other_warehouse(self):
        line = self.line()
        for warehouse in (None, SimpleNamespace(pk=self.raw.pk, status="DISABLED", warehouse_type="MATERIAL"),
                          SimpleNamespace(pk=self.raw.pk, status="ACTIVE", warehouse_type="SEMI_FINISHED")):
            with self.subTest(warehouse=warehouse):
                self.catalog.base_warehouse = warehouse
                self.assertEqual(material_receiving_warehouse_suggestions([line]), {})
        self.catalog.base_warehouse = self.raw
        self.zone_query.return_value.values_list.return_value = []
        self.assertEqual(material_receiving_warehouse_suggestions([line]), {})

    def test_processed_default_with_material_type_is_not_suggested(self):
        self.catalog.semi_warehouse = self.raw
        self.assertEqual(material_receiving_warehouse_suggestions([self.line("PROCESSED")]), {})

    def test_unknown_or_missing_frozen_state_is_not_inferred(self):
        for snapshot in ({}, {"processing_state": "INVALID"}, None):
            with self.subTest(snapshot=snapshot):
                line = self.line()
                line.material_selection_snapshot = snapshot
                self.assertEqual(material_receiving_warehouse_suggestions([line]), {})

    def test_legacy_or_archived_catalog_has_no_suggestion(self):
        line = self.line()
        line.material_catalog_id = None
        self.assertEqual(material_receiving_warehouse_suggestions([line]), {})
        self.catalog_query.assert_not_called()
        self.zone_query.assert_not_called()
        line.material_catalog_id = self.catalog.pk
        self.catalog_query.return_value.select_related.return_value = []
        self.assertEqual(material_receiving_warehouse_suggestions([line]), {})
        self.assertTrue(self.catalog_query.call_args.kwargs["archived_at__isnull"])

    def test_multiple_zones_still_suggest_warehouse_and_lookups_are_batched(self):
        self.zone_query.return_value.values_list.return_value = [self.raw.pk, self.raw.pk]
        lines = [self.line() for _ in range(20)]
        result = material_receiving_warehouse_suggestions(lines)
        self.assertEqual(result, {line.pk: str(self.raw.pk) for line in lines})
        self.catalog_query.assert_called_once()
        self.zone_query.assert_called_once()
        self.assertEqual(self.zone_query.call_args.kwargs["status"], "ACTIVE")
        self.assertEqual(self.zone_query.call_args.kwargs["warehouse__status"], "ACTIVE")


class ReceivingWarehouseSuggestionContractTests(SimpleTestCase):
    def test_response_keeps_suggestion_nullable_and_preserves_material_snapshot(self):
        warehouse_id = str(uuid4())
        snapshot = {"processing_state": "RAW", "category_key": "TUBE"}
        line = PurchaseOrderLine(line_number=1, actual_purchase_quantity=Decimal("10"),
                                 material_selection_snapshot=snapshot)
        legacy = PurchaseOrderLine(line_number=2, actual_purchase_quantity=Decimal("3"))
        request = SimpleNamespace(query_params={"purchase_order_id": str(uuid4())})
        with patch.object(MaterialInventoryViewSet, "_accessible_task_ids", return_value=[]), \
                patch("apps.inventory.api.views.purchase_order_access", return_value=Q()), \
                patch("apps.inventory.api.views.PurchaseOrder.objects.filter") as orders, \
                patch("apps.inventory.api.views.eligible_material_lines", return_value=[(line, Decimal("8")), (legacy, Decimal("3"))]), \
                patch("apps.inventory.api.views.material_receiving_warehouse_suggestions", return_value={line.pk: warehouse_id}), \
                patch("apps.inventory.api.views.etag_for_instance", return_value='"version"'):
            orders.return_value.first.return_value = SimpleNamespace()
            response = MaterialInventoryViewSet().eligible_lines(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"][0]["suggested_warehouse_id"], warehouse_id)
        self.assertIsNone(response.data["data"][1]["suggested_warehouse_id"])
        self.assertEqual(response.data["data"][0]["material_selection_snapshot"], snapshot)
        self.assertEqual(response.data["data"][0]["remaining_quantity"], "8.0000")
        self.assertEqual(response["ETag"], '"version"')

    def test_missing_or_invalid_order_id_rejects_before_reading_suggestions(self):
        with patch("apps.inventory.api.views.material_receiving_warehouse_suggestions") as suggestions:
            for value in ("", "not-a-uuid"):
                with self.subTest(value=value), self.assertRaises(ValidationError):
                    MaterialInventoryViewSet().eligible_lines(SimpleNamespace(query_params={"purchase_order_id": value}))
            suggestions.assert_not_called()

    def test_inaccessible_order_rejects_before_reading_suggestions(self):
        with patch.object(MaterialInventoryViewSet, "_accessible_task_ids", return_value=[]), \
                patch("apps.inventory.api.views.purchase_order_access", return_value=Q(pk__in=[])), \
                patch("apps.inventory.api.views.PurchaseOrder.objects.filter") as orders, \
                patch("apps.inventory.api.views.material_receiving_warehouse_suggestions") as suggestions:
            orders.return_value.first.return_value = None
            with self.assertRaises(NotFound):
                MaterialInventoryViewSet().eligible_lines(SimpleNamespace(query_params={"purchase_order_id": str(uuid4())}))
            suggestions.assert_not_called()

    def test_anonymous_request_cannot_read_suggestions(self):
        request = APIRequestFactory().get("/api/v1/material-inventory/eligible-lines/", {"purchase_order_id": str(uuid4())})
        with patch("apps.inventory.api.views.material_receiving_warehouse_suggestions") as suggestions:
            response = MaterialInventoryViewSet.as_view({"get": "eligible_lines"})(request)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.data["error"]["code"], "AUTHENTICATION_REQUIRED")
            suggestions.assert_not_called()
