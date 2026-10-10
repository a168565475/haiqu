import copy
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.inventory.models import MaterialStockMovement, SemiFinishedStockMovement
from apps.material_issues.models import MaterialIssueLine, MetalProcessingExternalOrder, MetalProcessingOriginalHandoff
from apps.material_issues.tests.test_metal_processing_p4 import MetalProcessingP4Fixture

from ..models import OutsourcingDispatchLine, OutsourcingFactoryCraft, OutsourcingMaterialItem, OutsourcingOrder


URL = "/api/v1/unified-outsourcing-orders/"


class UnifiedOutsourcingOrderApiTests(MetalProcessingP4Fixture, APITestCase):
    def rows(self, **filters):
        response = self.client.get(URL, filters)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def only_permissions(self, *names):
        user = self.f.user
        user.is_superuser = False
        user.save(update_fields=["is_superuser"])
        permissions = [Permission.objects.get(content_type__app_label=name.split(".")[0], codename=name.split(".")[1]) for name in names]
        user.user_permissions.set(permissions)
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))

    def raw_fabric(self, *, returned=False):
        response = self.f.create_order(self.payload("FABRIC", "150"))
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data["data"]["id"]
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order_id)
        detail = self.client.get(f"/api/v1/outsourcing-orders/{order_id}/")
        dispatched = self.client.post(f"/api/v1/outsourcing-orders/{order_id}/confirm-dispatch/", {
            "request_id": str(uuid.uuid4()), "lines": [{"material_item_id": str(material.pk),
            "inbound_line_id": str(self.f.material_inbound_line.pk), "requested_quantity": "150"}],
        }, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(dispatched.status_code, 200, dispatched.data)
        if returned:
            dispatch_line = OutsourcingDispatchLine.objects.get(dispatch__order_id=order_id)
            response = self.client.post(f"/api/v1/outsourcing-orders/{order_id}/confirm-return/", {
                "request_id": str(uuid.uuid4()), "factory_id": str(self.f.factory.pk),
                "good_zone_id": str(self.f.semi_zone.pk), "defective_zone_id": str(self.f.defective_zone.pk),
                "received_by_employee_id": str(self.f.employee.pk), "return_date": str(timezone.localdate()),
                "lines": [{"allocation_id": str(material.allocation_id), "good_quantity": "1", "defective_quantity": "0"}],
                "raw_inputs": [{"allocation_id": str(material.allocation_id), "dispatch_line_id": str(dispatch_line.pk),
                                "kind": "RAW_INPUT", "quantity": "1.5", "reason": "测试真实投入后回货"}],
            }, format="json", HTTP_IF_MATCH=dispatched["ETag"])
            self.assertEqual(response.status_code, 200, response.data)
        return order_id

    def test_combines_models_before_pagination_and_deduplicates_original(self):
        rework = self.create_order()
        raw_id = self.raw_fabric()
        now = timezone.now()
        OutsourcingOrder.objects.filter(pk=self.original_order).update(updated_at=now)
        MetalProcessingExternalOrder.objects.filter(pk=rework.pk).update(updated_at=now - timedelta(seconds=1))
        OutsourcingOrder.objects.filter(pk=raw_id).update(updated_at=now - timedelta(seconds=2))
        pages = [self.rows(page=page, page_size=1) for page in (1, 2, 3)]
        self.assertEqual([page["meta"]["total"] for page in pages], [3, 3, 3])
        self.assertEqual([page["data"][0]["id"] for page in pages], [self.original_order, str(rework.pk), raw_id])
        all_rows = self.rows()["data"]
        self.assertEqual(len({row["row_key"] for row in all_rows}), 3)
        self.assertEqual({row["source_kind"] for row in all_rows}, {"METAL", "RAW", "REWORK"})
        rework_row = next(row for row in all_rows if row["record_type"] == "REWORK")
        self.assertIsNone(rework_row["delivery_date"])
        self.assertEqual(rework_row["dispatched_quantities"], [{"quantity": "0", "unit": "支"}])

    def test_pending_spray_is_not_inferred_to_be_metal(self):
        row = self.rows()["data"][0]
        self.assertEqual(row["source_kind"], "UNSELECTED")
        self.assertEqual(row["dispatched_quantities"], [])
        self.assertFalse(row["direct_handoff"])

    def test_product_search_matches_regular_fields_without_exposing_restricted_products(self):
        self.create_original_handoff()
        for keyword in ("委外测试椅", "OBM-PRODUCT-001", "OBM-ITEM"):
            self.assertEqual(self.rows(search=keyword)["meta"]["total"], 1, keyword)
        self.only_permissions("material_issues.view_metalprocessingsource", "outsourcing.view_outsourcingorder")
        with patch("apps.outsourcing.unified_selectors.accessible_outsourcing_orders", return_value=OutsourcingOrder.objects.none()):
            self.assertEqual(self.rows()["meta"]["total"], 1)
            for keyword in ("委外测试椅", "OBM-PRODUCT-001", "OBM-ITEM"):
                self.assertEqual(self.rows(search=keyword)["meta"]["total"], 0, keyword)

    def test_fabric_dispatch_and_return_keep_separate_units(self):
        order_id = self.raw_fabric(returned=True)
        row = next(row for row in self.rows()["data"] if row["id"] == order_id)
        self.assertEqual(row["dispatched_quantities"], [{"quantity": "150", "unit": "米"}])
        self.assertEqual(row["returned_quantities"], [{"quantity": "1", "unit": "套"}])

    def test_raw_dispatch_uses_physical_material_quantity_not_purchase_deduction(self):
        order_id = self.raw_fabric()
        OutsourcingDispatchLine.objects.filter(dispatch__order_id=order_id).update(material_quantity=Decimal("175"), source_quantity=Decimal("150"))
        row = next(row for row in self.rows()["data"] if row["id"] == order_id)
        self.assertEqual(row["dispatched_quantities"], [{"quantity": "175", "unit": "米"}])

    def test_filtering_is_global_and_factory_includes_rework(self):
        order = self.create_order()
        self.assertEqual(self.rows(source_kind="REWORK")["data"][0]["id"], str(order.pk))
        self.assertEqual(self.rows(status="PENDING_HANDOFF")["meta"]["total"], 1)
        self.assertEqual(self.rows(factory_id=str(self.f.factory.pk))["meta"]["total"], 2)
        self.assertEqual(self.rows(craft_id=str(self.f.spray.pk))["meta"]["total"], 2)
        self.assertEqual(self.rows(search=order.order_number)["meta"]["total"], 1)
        self.assertEqual(self.rows(issue_id=str(self.line.issue_id))["meta"]["total"], 2)
        self.assertEqual(self.rows(product_line_id=str(uuid.uuid4()))["meta"]["total"], 0)

    def test_factory_quantity_filter_does_not_include_other_factory_handoffs(self):
        other_factory = copy.copy(self.f.factory)
        other_factory.pk = None
        other_factory.factory_number = "UNIFIED-SECOND"
        other_factory.name = "统一列表第二加工厂"
        other_factory.save()
        for link in self.f.factory.craft_links.all():
            OutsourcingFactoryCraft.objects.create(factory=other_factory, craft=link.craft, craft_name_snapshot=link.craft_name_snapshot)
        payload = self.payload(amount="18")
        product = payload["products"][0]
        allocations = product["processing_items"][0]["allocations"]
        allocations[0].update(input_quantity="12", allocated_quantity="12")
        allocations.append({**allocations[0], "factory_id": str(other_factory.pk), "input_quantity": "6", "allocated_quantity": "6"})
        product["materials"][0]["planned_issue_quantity"] = "12"
        product["materials"].append({**product["materials"][0], "factory_id": str(other_factory.pk), "planned_issue_quantity": "6"})
        created = self.f.create_order(payload)
        self.assertEqual(created.status_code, 201, created.data)
        order_id = created.data["data"]["id"]
        for factory, pieces in ((self.f.factory, 8), (other_factory, 4)):
            self.post(f"/api/v1/metal-processing-sources/{self.line.pk}/handoffs/", {
                "request_id": str(uuid.uuid4()), "original_order_id": order_id, "factory_id": str(factory.pk),
                "handoff_pieces": pieces, "handoff_date": str(timezone.localdate()),
            }, etag=self.source_etag())
        row = next(row for row in self.rows()["data"] if row["id"] == order_id)
        self.assertEqual(row["dispatched_quantities"], [{"quantity": "12", "unit": "支"}])
        row = self.rows(factory_id=str(other_factory.pk))["data"][0]
        self.assertEqual(row["dispatched_quantities"], [{"quantity": "4", "unit": "支"}])
        self.assertEqual(row["factory_names"], [other_factory.name])

    def test_regular_only_permission_does_not_expose_rework_or_metal_actions(self):
        self.create_order()
        self.only_permissions("outsourcing.view_outsourcingorder")
        rows = self.rows()["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["detail_access"], "REGULAR")
        self.assertFalse(rows[0]["can_delete"])
        self.assertFalse(rows[0]["can_revoke_dispatched"])
        self.assertEqual(self.client.get(URL + "options/").status_code, 200)

    def test_metal_only_permission_keeps_original_projection_and_hides_whole_order_fields(self):
        order = self.create_order()
        self.only_permissions("material_issues.view_metalprocessingsource")
        rows = self.rows()["data"]
        self.assertEqual({row["id"] for row in rows}, {self.original_order, str(order.pk)})
        original = next(row for row in rows if row["record_type"] == "ORIGINAL")
        self.assertEqual(original["detail_access"], "METAL")
        self.assertEqual(original["source_issue_line_id"], str(self.line.pk))
        self.assertEqual(original["dispatched_quantities"], [{"quantity": "8", "unit": "支"}])
        self.assertEqual(original["product"], {})
        self.assertIsNone(original["planned_amount"])
        self.assertIsNone(original["delivery_date"])
        self.assertEqual(original["schedule_number"], "")
        options = self.client.get(URL + "options/")
        self.assertEqual(options.status_code, 200, options.data)
        self.assertTrue(all(row["outsourcing_code"] == "POWDER_COATING" for row in options.data["data"]["crafts"]))

    def test_projection_does_not_add_hidden_source_quantities(self):
        self.create_original_handoff(8)
        other_line = self.issue_line(quantity=12)
        self.write("completions", self.complete_payload(4), line=other_line)
        response = self.client.post(f"/api/v1/metal-processing-sources/{other_line.pk}/handoffs/", {
            "request_id": str(uuid.uuid4()), "original_order_id": self.original_order,
            "factory_id": str(self.f.factory.pk), "handoff_pieces": 4, "handoff_date": str(timezone.localdate()),
        }, format="json", HTTP_IF_MATCH=self.detail(other_line)["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        self.only_permissions("material_issues.view_metalprocessingsource")
        with patch("apps.outsourcing.unified_selectors.processing_lines", return_value=MaterialIssueLine.objects.filter(pk=self.line.pk)):
            row = self.rows()["data"][0]
        self.assertEqual(row["dispatched_quantities"], [{"quantity": "8", "unit": "支"}])
        self.assertEqual(row["processing_count"], 1)
        with patch("apps.outsourcing.unified_selectors.processing_lines", return_value=MaterialIssueLine.objects.none()):
            self.assertEqual(self.rows()["meta"]["total"], 0)

    def test_metal_channel_survives_absent_schedule_scope_even_with_regular_permission(self):
        self.create_order()
        for permissions in (("material_issues.view_metalprocessingsource",), (
            "material_issues.view_metalprocessingsource", "outsourcing.view_outsourcingorder",
        )):
            self.only_permissions(*permissions)
            with patch("apps.outsourcing.unified_selectors.accessible_outsourcing_orders", return_value=OutsourcingOrder.objects.none()):
                rows = self.rows()["data"]
            self.assertEqual(len(rows), 2)
            original = next(row for row in rows if row["record_type"] == "ORIGINAL")
            self.assertEqual(original["detail_access"], "METAL")
            self.assertEqual(original["source_issue_line_id"], str(self.line.pk))
            self.assertIsNone(original["planned_amount"])
            self.assertEqual(original["schedule_number"], "")

    def test_no_view_permission_rejected_and_invalid_filters_are_reported(self):
        for filters in ({"factory_id": "bad"}, {"source_kind": "GUESS"}, {"status": "BAD"}, {"search": "x" * 201}):
            self.assertEqual(self.client.get(URL, filters).status_code, 400)
        self.only_permissions()
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.client.get(URL + "options/").status_code, 403)

    def test_source_filters_keep_original_order_and_source_ids(self):
        handoff = self.create_original_handoff()
        for filters in ({"original_order_id": self.original_order}, {"source_id": str(handoff.source_id)}):
            response = self.client.get("/api/v1/metal-processing-sources/", filters)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual([row["issue_line_id"] for row in response.data["data"]], [str(self.line.pk)])
        response = self.client.get("/api/v1/metal-processing-sources/", {"original_order_id": str(uuid.uuid4())})
        self.assertEqual(response.data["meta"]["total"], 0)

    def test_read_only_queries_do_not_write_inventory_and_are_bounded(self):
        self.create_order()
        self.raw_fabric(returned=True)
        before = (MaterialStockMovement.objects.count(), SemiFinishedStockMovement.objects.count(), MetalProcessingOriginalHandoff.objects.count())
        with CaptureQueriesContext(connection) as captured:
            self.rows()
        self.assertLess(len(captured), 35)
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in captured))
        after = (MaterialStockMovement.objects.count(), SemiFinishedStockMovement.objects.count(), MetalProcessingOriginalHandoff.objects.count())
        self.assertEqual(before, after)
