from decimal import Decimal

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.samples.pipe_materials import (
    is_total_meter_pipe,
    sample_pipe_meter_snapshot,
    total_meter_value,
)


class SamplePipeMeterValueTests(SimpleTestCase):
    def test_total_meter_snapshot_uses_demand_and_shortage_meters(self):
        row = {
            "key": "2f0f2b1a-13be-4d79-8dd8-3a1a164a3ce4",
            "category": "tube",
            "quantity": "12.50",
            "supplyQuantity": "4.5",
            "shortageQuantity": "8",
            "rawMaterialId": "raw-1",
        }
        self.assertTrue(is_total_meter_pipe(row))
        snapshot = sample_pipe_meter_snapshot(row)
        self.assertEqual(snapshot["required_meters"], "12.50")
        self.assertEqual(snapshot["supply_meters"], "4.5")
        self.assertEqual(snapshot["shortage_meters"], "8.00")
        self.assertEqual(snapshot["schema_version"], 3)

    def test_legacy_pipe_rows_do_not_switch_to_meter_mode(self):
        row = {"category": "tube", "quantity": "2", "cuttingLengthMm": "3050", "piecesPerBar": "4"}
        self.assertFalse(is_total_meter_pipe(row))

    def test_meter_value_rejects_negative_and_excess_precision(self):
        with self.assertRaises(ValidationError):
            total_meter_value("-1", "quantity")
        with self.assertRaises(ValidationError):
            total_meter_value("1.12345", "quantity")
        self.assertEqual(total_meter_value(Decimal("0"), "quantity", allow_zero=True), Decimal("0"))
