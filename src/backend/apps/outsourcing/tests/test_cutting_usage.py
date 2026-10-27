from decimal import Decimal

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.boms.material_flow_bom import apply_line_quantities
from apps.inventory.models import MaterialStockMovement, PublicStockBalance, SemiFinishedStockBalance
from ..models import OutsourcingFactoryAllocation, OutsourcingMaterialItem, OutsourcingProcessingItem
from .test_material_flow import MaterialFlowFixture
from .test_public_stock_flow import PublicOutsourcingFixture


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

    def test_historical_snapshot_and_meter_dispatch_return_do_not_use_piece_count_as_sets(self):
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

@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class PublicCuttingOutputSetsTests(PublicOutsourcingFixture, APITestCase):
    def new_payload(self, sets="60", meters="17.25"):
        payload = self.payload("FABRIC", meters)
        item = payload["products"][0]["processing_items"][0]
        item["quantity"] = sets
        item["allocations"][0].update(input_quantity=None, allocated_quantity=sets)
        return payload

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
