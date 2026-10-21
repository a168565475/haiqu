from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework.exceptions import ValidationError

from apps.boms.material_flow_bom import apply_line_quantities
from apps.inventory.models import MaterialStockMovement, PublicStockBalance, SemiFinishedStockBalance
from ..material_flow import input_plan, processing_basis
from ..models import OutsourcingFactoryAllocation, OutsourcingMaterialItem, OutsourcingOrder, OutsourcingProcessingItem
from ..services import processing_reference_usage, processing_required_quantity
from .test_material_flow import MaterialFlowFixture
from .test_public_stock_flow import PublicOutsourcingFixture


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

    def test_count_demand_ignores_missing_and_conflicting_historical_meters(self):
        line = SimpleNamespace(cut_piece_quantity="2", unit_consumption="0.125", cutting_pieces_per_set=2,
                               fabric_meters_per_piece=None, cutting_sets_per_product=3)
        self.assertEqual(processing_required_quantity(line, 100), Decimal("300"))
        line.fabric_meters_per_piece = "-4"
        self.assertEqual(processing_required_quantity(line, 100), Decimal("300"))

    def test_output_sets_are_integer_and_do_not_invent_raw_meter_quantity(self):
        snapshot = {"kind": "FABRIC", "quantity_basis": "OUTPUT_SETS"}
        plan = input_plan("12", snapshot)
        self.assertEqual(plan["output_quantity"], 12)
        self.assertIsNone(plan["raw_quantity"])
        for value in ("0", "1.5", "-1"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                input_plan(value, snapshot)

    def test_legacy_fabric_and_pipe_keep_their_frozen_input_conversion(self):
        legacy = input_plan("99", {"kind": "FABRIC", "fabric_meters_per_set": "1.5"})
        self.assertEqual((legacy["output_quantity"], legacy["raw_quantity"]), (66, 99))
        pipe = input_plan("12", {"kind": "PIPE", "pieces_per_bar": 6, "raw_bar_length_m": "3.05"})
        self.assertEqual((pipe["output_quantity"], pipe["raw_quantity"]), (12, 2))


class CuttingUsageOutsourcingTests(MaterialFlowFixture, APITestCase):
    def enable_piece_usage(self, meters="0.5", sets=1):
        line = self.f.cutting
        line.cutting_pieces_per_set = 2
        line.fabric_meters_per_piece = Decimal(meters) if meters is not None else None
        line.fabric_meters_per_set = None if meters is None else Decimal("99")
        line.cutting_sets_per_product = sets
        apply_line_quantities(line, self.f.bom.order_quantity)
        line.save()

    def new_payload(self, amount="100", expected="100"):
        payload = self.payload("FABRIC", amount)
        item = payload["products"][0]["processing_items"][0]
        item["quantity"] = expected
        item["allocations"][0]["allocated_quantity"] = expected
        item["allocations"][0]["input_quantity"] = None
        return payload

    def test_source_preview_reports_sets_and_pieces_and_leaves_fabric_procurement_unchanged(self):
        self.enable_piece_usage(sets=3)
        before = (OutsourcingOrder.objects.count(), MaterialStockMovement.objects.count())
        response = self.f.get_bom(self.f.sewing)
        self.assertEqual(response.status_code, 200, response.data)
        item = response.data["data"]["processing_items"][0]
        self.assertEqual((Decimal(item["required_quantity"]), item["reference_usage"], item["unit"], item["input_unit"]),
                         (300, "3", "套", "套"))
        snapshot = item["conversion_snapshot"]
        self.assertEqual((snapshot["required_sets"], snapshot["required_pieces"], snapshot["quantity_basis"]),
                         (300, 600, "OUTPUT_SETS"))
        self.assertEqual(Decimal(item["available_quantity"]), 300)
        self.assertNotIn("required_meters", snapshot)
        self.f.fabric.refresh_from_db()
        self.assertEqual(self.f.fabric.unit_consumption, "1.5")
        self.assertEqual(before, (OutsourcingOrder.objects.count(), MaterialStockMovement.objects.count()))

    def test_new_snapshot_and_meter_dispatch_return_do_not_use_piece_count_as_sets(self):
        self.enable_piece_usage(meters=None)
        response = self.f.create_order(self.new_payload(amount="17.25"))
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data["data"]["id"]
        allocation = OutsourcingFactoryAllocation.objects.get(processing_item__order_product__order_id=order_id)
        frozen = dict(allocation.conversion_snapshot)
        self.assertEqual((frozen["cutting_pieces_per_set"], frozen["cutting_sets_per_product"]), (2, 1))
        self.assertEqual((frozen["quantity_basis"], allocation.allocated_quantity), ("OUTPUT_SETS", 100))
        self.assertIsNone(allocation.input_quantity)
        self.assertNotIn("fabric_meters_per_set", frozen)
        saved = response.data["data"]["products"][0]["processing_items"][0]["allocations"][0]
        self.assertIsNone(saved["input_quantity"])
        processing = OutsourcingProcessingItem.objects.get(order_product__order_id=order_id)
        self.assertEqual(processing.component_snapshot["reference_usage"], "1")
        self.assertFalse(MaterialStockMovement.objects.filter(direction="OUT").exists())
        _, source = self.dispatch(order_id, "FABRIC", "17.25")
        self.assertEqual(source.issued_quantity, Decimal("17.25"))
        self.assertEqual(source.snapshot["input_unit"], "米")
        # 加工套数已冻结，后续 BOM 历史米数不能改变本单回货额度。
        self.enable_piece_usage(meters="0.75", sets=2)
        allocation.refresh_from_db()
        self.assertEqual(allocation.conversion_snapshot, frozen)
        self.return_goods(order_id, source, 40)
        self.return_goods(order_id, source, 61, expected=409)
        self.return_goods(order_id, source, 60)
        balance = SemiFinishedStockBalance.objects.get(quality="AVAILABLE")
        self.assertEqual((balance.quantity, balance.unit.unit_name), (100, "套"))
        self.assertEqual(MaterialStockMovement.objects.filter(direction="OUT").count(), 1)

    def test_historical_meters_are_ignored_and_order_sets_still_limit_allocation(self):
        self.enable_piece_usage()
        self.f.cutting.fabric_meters_per_set = Decimal("0.5")
        self.f.cutting.save(update_fields=["fabric_meters_per_set"])
        self.assertNotIn("fabric_meters_per_set", processing_basis(self.f.cutting))
        response = self.f.create_order(self.new_payload(expected="200"))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(OutsourcingOrder.objects.exists())

    def test_legacy_frozen_snapshot_still_converts_meters_after_current_bom_drops_them(self):
        self.enable_piece_usage()
        response = self.f.create_order(self.new_payload(amount="99", expected="66"))
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data["data"]["id"]
        allocation = OutsourcingFactoryAllocation.objects.get(processing_item__order_product__order_id=order_id)
        frozen = {key: value for key, value in allocation.conversion_snapshot.items()
                  if key not in {"quantity_basis", "raw_input_unit", "remainder_meters"}}
        frozen.update(input_unit="米", fabric_meters_per_set="1.5")
        allocation.conversion_snapshot = frozen
        allocation.input_quantity = 99
        allocation.input_unit_snapshot = "米"
        allocation.save()
        OutsourcingMaterialItem.objects.filter(allocation=allocation).update(conversion_snapshot=frozen)
        _, source = self.dispatch(order_id, "FABRIC", "99")
        self.enable_piece_usage(meters=None)
        allocation.refresh_from_db()
        self.assertEqual(allocation.conversion_snapshot, frozen)
        self.return_goods(order_id, source, 66, expected=409)
        self.return_goods(order_id, source, 66, raw_inputs=[self.entry(source, "RAW_INPUT", 99)])

    def test_pending_external_allocations_reduce_set_availability_and_block_overallocation(self):
        self.enable_piece_usage(meters=None)
        first = self.f.create_order(self.new_payload(amount="15.5", expected="60"))
        self.assertEqual(first.status_code, 201, first.data)
        preview = self.f.get_bom(self.f.sewing)
        self.assertEqual(Decimal(preview.data["data"]["processing_items"][0]["available_quantity"]), 40)
        response = self.f.create_order(self.new_payload(amount="1", expected="41"))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(OutsourcingOrder.objects.count(), 1)

    def test_obsolete_meter_input_is_rejected_instead_of_reinterpreted_as_sets(self):
        self.enable_piece_usage()
        payload = self.new_payload()
        payload["products"][0]["processing_items"][0]["allocations"][0]["input_quantity"] = "100"
        response = self.f.create_order(payload)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(OutsourcingOrder.objects.exists())


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class PublicCuttingOutputSetsTests(PublicOutsourcingFixture, APITestCase):
    def new_payload(self, sets="60", meters="17.25"):
        payload = self.payload("FABRIC", meters)
        item = payload["products"][0]["processing_items"][0]
        item["quantity"] = sets
        item["allocations"][0].update(input_quantity=None, allocated_quantity=sets)
        return payload

    def test_public_preview_keeps_set_availability_independent_of_fabric_meter_allowance(self):
        response = self.f.create_order(self.new_payload())
        self.assertEqual(response.status_code, 201, response.data)
        preview = self.f.get_bom(self.f.sewing)
        self.assertEqual(preview.status_code, 200, preview.data)
        item = preview.data["data"]["processing_items"][0]
        self.assertEqual((Decimal(item["available_quantity"]), item["input_unit"]), (40, "套"))
        material = preview.data["data"]["material_items"][0]
        self.assertEqual(material["conversion_snapshot"]["input_unit"], "米")

    def test_public_dispatch_debits_decimal_meters_and_returns_allocated_sets_without_meter_input(self):
        self.f.cutting.fabric_meters_per_piece = None
        self.f.cutting.fabric_meters_per_set = None
        self.f.cutting.save(update_fields=["fabric_meters_per_piece", "fabric_meters_per_set"])
        response = self.f.create_order(self.new_payload())
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data["data"]["id"]
        _, source = self.dispatch(order_id, "FABRIC", "17.25")
        self.f.material_balance.refresh_from_db()
        self.assertEqual(self.f.material_balance.quantity, Decimal("182.75"))
        self.return_goods(order_id, source, 20)
        payload = self.return_goods(order_id, source, 40)
        self.post(order_id, "confirm-return", payload)
        self.return_goods(order_id, source, 1, expected=409)
        balance = PublicStockBalance.objects.get(stock_kind="SEMI")
        self.assertEqual((balance.quantity, balance.unit.unit_name, balance.meter_quantity), (60, "套", None))
