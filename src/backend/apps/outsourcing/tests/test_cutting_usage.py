from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.boms.material_flow_bom import apply_line_quantities
from apps.inventory.models import MaterialStockMovement, SemiFinishedStockBalance
from ..material_flow import processing_basis
from ..models import OutsourcingFactoryAllocation, OutsourcingOrder, OutsourcingProcessingItem
from ..services import processing_reference_usage, processing_required_quantity
from .test_material_flow import MaterialFlowFixture


class CuttingUsageDemandTests(SimpleTestCase):
    def test_new_demand_uses_sets_per_product_and_preserves_legacy_piece_quantity_rule(self):
        line = SimpleNamespace(cut_piece_quantity="2", unit_consumption="0.125", cutting_pieces_per_set=2,
                               fabric_meters_per_piece="0.125", cutting_sets_per_product=1)
        self.assertEqual(processing_required_quantity(line, 105), Decimal("105.0000"))
        self.assertEqual(processing_reference_usage(line), "1")
        line.cutting_sets_per_product = 3
        self.assertEqual(processing_required_quantity(line, 105), Decimal("315.0000"))
        line.cutting_pieces_per_set = line.fabric_meters_per_piece = line.cutting_sets_per_product = None
        self.assertEqual(processing_required_quantity(line, 105), Decimal("210.0000"))
        self.assertEqual(processing_reference_usage(line), "2")
        line.cut_piece_quantity = ""
        self.assertEqual(processing_required_quantity(line, 100), Decimal("12.5000"))

    def test_partial_new_values_never_fall_back_to_legacy_rule(self):
        line = SimpleNamespace(cut_piece_quantity="2", unit_consumption="0.125", cutting_pieces_per_set=2,
                               fabric_meters_per_piece=None, cutting_sets_per_product=None)
        self.assertIsNone(processing_required_quantity(line, 100))


class CuttingUsageOutsourcingTests(MaterialFlowFixture, APITestCase):
    def enable_piece_usage(self, meters="0.5", sets=1):
        line = self.f.cutting
        line.cutting_pieces_per_set = 2
        line.fabric_meters_per_piece = Decimal(meters)
        line.cutting_sets_per_product = sets
        apply_line_quantities(line, self.f.bom.order_quantity)
        line.save()

    def new_payload(self, amount="100", expected="100"):
        payload = self.payload("FABRIC", amount)
        item = payload["products"][0]["processing_items"][0]
        item["quantity"] = expected
        item["allocations"][0]["allocated_quantity"] = expected
        return payload

    def test_source_preview_reports_sets_pieces_meters_and_leaves_fabric_procurement_unchanged(self):
        self.enable_piece_usage(sets=3)
        before = (OutsourcingOrder.objects.count(), MaterialStockMovement.objects.count())
        response = self.f.get_bom(self.f.sewing)
        self.assertEqual(response.status_code, 200, response.data)
        item = response.data["data"]["processing_items"][0]
        self.assertEqual((Decimal(item["required_quantity"]), item["reference_usage"], item["unit"], item["input_unit"]),
                         (300, "3", "套", "米"))
        snapshot = item["conversion_snapshot"]
        self.assertEqual((snapshot["required_sets"], snapshot["required_pieces"], snapshot["required_meters"]),
                         (300, 600, "300.0000"))
        self.f.fabric.refresh_from_db()
        self.assertEqual(self.f.fabric.unit_consumption, "1.5")
        self.assertEqual(before, (OutsourcingOrder.objects.count(), MaterialStockMovement.objects.count()))

    def test_new_snapshot_and_meter_dispatch_return_do_not_use_piece_count_as_sets(self):
        self.enable_piece_usage()
        response = self.f.create_order(self.new_payload())
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data["data"]["id"]
        allocation = OutsourcingFactoryAllocation.objects.get(processing_item__order_product__order_id=order_id)
        frozen = dict(allocation.conversion_snapshot)
        self.assertEqual((frozen["cutting_pieces_per_set"], frozen["fabric_meters_per_piece"], frozen["cutting_sets_per_product"]),
                         (2, "0.5000", 1))
        self.assertEqual((frozen["fabric_meters_per_set"], allocation.allocated_quantity), ("1.0000", 100))
        processing = OutsourcingProcessingItem.objects.get(order_product__order_id=order_id)
        self.assertEqual(processing.component_snapshot["reference_usage"], "1")
        self.assertFalse(MaterialStockMovement.objects.filter(direction="OUT").exists())
        _, source = self.dispatch(order_id, "FABRIC", "100")
        self.assertEqual(source.issued_quantity, 100)
        # 单据已经冻结，后续修改当前 BOM 不能改旧单据的米/套关系。
        self.enable_piece_usage(meters="0.75", sets=2)
        allocation.refresh_from_db()
        self.assertEqual(allocation.conversion_snapshot, frozen)
        self.return_goods(order_id, source, 100, 0, [self.entry(source, "RAW_INPUT", 100)])
        balance = SemiFinishedStockBalance.objects.get(quality="AVAILABLE")
        self.assertEqual((balance.quantity, balance.unit.unit_name), (100, "套"))
        self.assertEqual(MaterialStockMovement.objects.filter(direction="OUT").count(), 1)

    def test_forged_derived_meters_and_piece_based_output_are_not_trusted(self):
        self.enable_piece_usage()
        self.f.cutting.fabric_meters_per_set = Decimal("0.5")
        self.f.cutting.save(update_fields=["fabric_meters_per_set"])
        self.assertEqual(processing_basis(self.f.cutting)["fabric_meters_per_set"], "1.0000")
        response = self.f.create_order(self.new_payload(expected="200"))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(OutsourcingOrder.objects.exists())

    def test_legacy_frozen_snapshot_remains_unchanged_after_bom_adopts_new_fields(self):
        order_id = self.create("FABRIC", "99")
        allocation = OutsourcingFactoryAllocation.objects.get(processing_item__order_product__order_id=order_id)
        frozen = dict(allocation.conversion_snapshot)
        self.assertEqual(frozen["fabric_meters_per_set"], "1.5000")
        self.assertNotIn("cutting_pieces_per_set", frozen)
        self.enable_piece_usage()
        allocation.refresh_from_db()
        self.assertEqual(allocation.conversion_snapshot, frozen)
