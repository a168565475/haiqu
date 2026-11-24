from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.inventory.hardware_receipts import hardware_receipt_values, is_hardware_weight, quality_hardware_quantities, validate_hardware_inbound
from apps.inventory.hardware_stock_weights import piece_weight_change
from apps.inventory.stock_services import returned_material_weight
from apps.material_issues.requirements import inventory_source_quantity


class HardwareWeightQuantityTests(SimpleTestCase):
    def line(self, unit="个"):
        purchase = SimpleNamespace(source_unit_text="KG", calculation_snapshot={"measurement_kind": "HARDWARE_WEIGHT", "hardware_unit_weight_kg": "0.00396"})
        item = {"received_piece_count": 1000, "received_weight_kg": Decimal("3.96")}
        values = hardware_receipt_values(purchase_line=purchase, item=item, piece_unit=unit)
        return SimpleNamespace(**values, received_quantity=item["received_quantity"], accepted_quantity=item["received_quantity"],
                               return_quantity=Decimal(0), source_unit_text_snapshot="KG")

    def test_rivet_and_washer_reference_count_is_floored_from_actual_weight(self):
        for unit in ("个", "片"):
            line = self.line(unit)
            self.assertEqual(line.received_quantity, 1000)
            self.assertEqual(line.received_weight_kg, Decimal("3.96"))
            line.return_quantity = quality_hardware_quantities(line, {"return_piece_count": 100, "return_weight_kg": Decimal("0.4")})
            line.accepted_quantity = line.received_quantity - line.return_quantity
            validate_hardware_inbound(line, unit)
            self.assertEqual(line.accepted_quantity, 898)
            self.assertEqual(line.return_quantity, 102)
            self.assertEqual(line.accepted_weight_kg, Decimal("3.56"))

    def test_client_count_never_overrides_authoritative_weight_conversion(self):
        purchase = SimpleNamespace(source_unit_text="KG", calculation_snapshot={"measurement_kind": "HARDWARE_WEIGHT", "hardware_unit_weight_kg": "0.00396"})
        for count in (None, 0, -1, True, Decimal("1.5"), "NaN"):
            with self.subTest(count=count):
                item = {"received_piece_count": count, "received_weight_kg": Decimal("3.96")}
                hardware_receipt_values(purchase_line=purchase, item=item, piece_unit="个")
                self.assertEqual(item["received_quantity"], 1000)

    def test_batches_floor_independently_and_tiny_weight_preserves_zero_reference(self):
        purchase = SimpleNamespace(source_unit_text="KG", calculation_snapshot={"measurement_kind": "HARDWARE_WEIGHT", "hardware_unit_weight_kg": "0.00396"})
        quantities = []
        for _ in range(2):
            item = {"received_weight_kg": Decimal("1")}
            hardware_receipt_values(purchase_line=purchase, item=item, piece_unit="个")
            quantities.append(item["received_quantity"])
        self.assertEqual(quantities, [252, 252])
        item = {"received_weight_kg": Decimal("0.001")}
        hardware_receipt_values(purchase_line=purchase, item=item, piece_unit="个")
        self.assertEqual((item["received_quantity"], item["received_weight_kg"]), (Decimal(0), Decimal("0.001")))
        for single_weight in (None, "0", "-1", "NaN", "0.000000001"):
            purchase.calculation_snapshot["hardware_unit_weight_kg"] = single_weight
            with self.subTest(single_weight=single_weight), self.assertRaises(ValidationError):
                hardware_receipt_values(purchase_line=purchase, item={"received_weight_kg": Decimal("1")}, piece_unit="个")

    def test_invalid_weight_and_ambiguous_piece_unit_rejected(self):
        purchase = SimpleNamespace(source_unit_text="KG", calculation_snapshot={"measurement_kind": "HARDWARE_WEIGHT"})
        for weight in (None, 0, -1, "NaN", "Infinity", "1.00001"):
            with self.subTest(weight=weight), self.assertRaises(ValidationError):
                hardware_receipt_values(purchase_line=purchase, item={"received_piece_count": 100, "received_weight_kg": weight}, piece_unit="片")
        with self.assertRaises(ValidationError):
            hardware_receipt_values(purchase_line=purchase, item={"received_piece_count": 100, "received_weight_kg": "1"}, piece_unit="箱")

    def test_non_object_measurement_snapshot_is_reported_as_invalid(self):
        for snapshot in ([], ["measurement_kind"], "measurement_kind", False, 1):
            with self.subTest(snapshot=snapshot), self.assertRaises(ValidationError):
                is_hardware_weight(SimpleNamespace(calculation_snapshot=snapshot))

    def test_native_kg_stays_kg_without_integer_piece_conversion(self):
        purchase = SimpleNamespace(source_unit_text="KG", calculation_snapshot={"measurement_kind": "HARDWARE_WEIGHT"})
        item = {"received_weight_kg": Decimal("3.9567")}
        values = hardware_receipt_values(purchase_line=purchase, item=item, piece_unit="KG")
        line = SimpleNamespace(**values, received_quantity=item["received_quantity"], source_unit_text_snapshot="KG")
        line.return_quantity = quality_hardware_quantities(line, {"return_weight_kg": Decimal("0.1234")})
        line.accepted_quantity = line.received_quantity - line.return_quantity
        validate_hardware_inbound(line, "KG")
        self.assertEqual(line.accepted_quantity, Decimal("3.8333"))
        self.assertEqual(line.accepted_weight_kg, Decimal("3.8333"))
        self.assertEqual(piece_weight_change(before_quantity=Decimal("3.8333"), before_weight=Decimal("3.8333"),
            quantity=Decimal("0.6789"), direction="OUT", quantity_unit="KG"),
            (Decimal("3.8333"), Decimal("0.6789"), Decimal("3.1544")))

    def test_quality_zero_full_and_partial_boundaries(self):
        for weight in ("-1", "4", "NaN"):
            with self.subTest(weight=weight), self.assertRaises(ValidationError):
                quality_hardware_quantities(self.line(), {"return_weight_kg": weight})
        line = self.line()
        self.assertEqual(quality_hardware_quantities(line, {"return_weight_kg": "0", "return_piece_count": 999999}), 0)
        self.assertEqual(quality_hardware_quantities(line, {"return_weight_kg": "3.96", "return_piece_count": 0}), 1000)
        self.assertEqual(line.accepted_weight_kg, 0)
        line = self.line()
        line.return_quantity = quality_hardware_quantities(line, {"return_weight_kg": "3.9599"})
        line.accepted_quantity = line.received_quantity - line.return_quantity
        validate_hardware_inbound(line, "个")
        self.assertEqual((line.accepted_quantity, line.accepted_weight_kg), (Decimal(0), Decimal("0.0001")))

    def test_partial_return_uses_remaining_weight_and_never_independent_floor_totals(self):
        line = self.line()
        line.received_weight_kg = line.accepted_weight_kg = Decimal("3.9650")
        line.received_quantity = line.accepted_quantity = Decimal(1001)
        line.return_quantity = quality_hardware_quantities(line, {"return_weight_kg": "0.0001"})
        line.accepted_quantity = line.received_quantity - line.return_quantity
        self.assertEqual(line.return_quantity, 0)
        self.assertEqual(line.accepted_quantity, 1001)
        validate_hardware_inbound(line, "个")

    def test_known_weight_is_allocated_from_actual_balance_and_last_issue_clears(self):
        before, moved, after = piece_weight_change(before_quantity=Decimal(3), before_weight=Decimal("1"), quantity=Decimal(1), direction="OUT")
        self.assertEqual((before, moved, after), (Decimal(1), Decimal("0.3333"), Decimal("0.6667")))
        self.assertEqual(piece_weight_change(before_quantity=Decimal(2), before_weight=after, quantity=Decimal(2), direction="OUT"),
                         (Decimal("0.6667"), Decimal("0.6667"), Decimal(0)))

    def test_mixed_legacy_weight_stays_unknown_until_empty_pool_restarts(self):
        self.assertEqual(piece_weight_change(before_quantity=10, before_weight=None, quantity=10, direction="IN", weight_quantity=Decimal("1")), (None, Decimal(1), None))
        self.assertEqual(piece_weight_change(before_quantity=10, before_weight=Decimal("1"), quantity=10, direction="IN"), (Decimal(1), None, None))
        self.assertEqual(piece_weight_change(before_quantity=20, before_weight=None, quantity=20, direction="OUT"), (None, None, None))
        self.assertEqual(piece_weight_change(before_quantity=0, before_weight=None, quantity=100, direction="IN", weight_quantity=Decimal("3.96")),
                         (Decimal(0), Decimal("3.96"), Decimal("3.96")))

    def test_zero_reference_inbound_keeps_existing_residual_weight(self):
        self.assertEqual(piece_weight_change(before_quantity=0, before_weight=Decimal("0.001"), quantity=0,
            direction="IN", weight_quantity=Decimal("0.002")), (Decimal("0.001"), Decimal("0.002"), Decimal("0.003")))
        self.assertEqual(piece_weight_change(before_quantity=0, before_weight=Decimal("0.003"), quantity=1,
            direction="IN", weight_quantity=Decimal("0.004")), (Decimal("0.003"), Decimal("0.004"), Decimal("0.007")))
        with self.assertRaises(ValidationError):
            piece_weight_change(before_quantity=0, before_weight=Decimal("0.001"), quantity=0, direction="OUT")

    def test_issue_requirement_uses_pieces_and_not_purchase_kg(self):
        for unit in ("个", "片"):
            line = SimpleNamespace(section=SimpleNamespace(section_type="ACCESSORY"), unit=unit,
                raw_values={"hardware_weight_mode": "AUTO", "unit_material_weight_kg": "0.00396"},
                budget_quantity="1200", total_consumption="", unit_consumption="12")
            quantity, _, _, source_unit, status = inventory_source_quantity(line, SimpleNamespace(order_quantity=100))
            self.assertEqual((quantity, source_unit, status), (Decimal(1200), unit, "READY"))

    def test_return_reuses_original_remaining_weight_and_rejects_over_return(self):
        original = SimpleNamespace(quantity=Decimal(3), weight_quantity=Decimal("1"), balance_id="balance", direction="OUT")
        returned = SimpleNamespace(quantity=Decimal(1), weight_quantity=Decimal("0.3333"), direction="IN")
        source = SimpleNamespace(pk="dispatch", raw_material_id="material", unit_id="unit", zone_id="zone", unit=SimpleNamespace(unit_name="个"))
        with patch("apps.inventory.stock_services.MaterialStockMovement.objects") as manager:
            manager.select_for_update.return_value.filter.return_value.first.return_value = original
            manager.filter.return_value.order_by.return_value = [returned]
            self.assertEqual(returned_material_weight(source=source, quantity=Decimal(2)), Decimal("0.6667"))
            with self.assertRaises(ValidationError):
                returned_material_weight(source=source, quantity=Decimal(3))
            original.weight_quantity = None
            returned.weight_quantity = None
            self.assertIsNone(returned_material_weight(source=source, quantity=Decimal(2)))
