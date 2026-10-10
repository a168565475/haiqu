from decimal import Decimal

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.procurement.pipe_purchase import purchase_pipe_values


class SamplePipeMeterPurchaseValueTests(SimpleTestCase):
    def setUp(self):
        self.snapshot = {
            "schema_version": 3,
            "measurement_kind": "PIPE",
            "source": "SAMPLE",
            "required_meters": "12.5",
            "shortage_meters": "12.5",
        }

    def test_purchase_roots_and_length_calculate_meters(self):
        values = purchase_pipe_values(self.snapshot, {"actual_bar_count": 3, "raw_bar_length_m": "5.00"})
        self.assertEqual(values["actual_bar_count"], 3)
        self.assertEqual(values["actual_purchase_meters"], Decimal("15.0000"))
        self.assertEqual(values["suggested_purchase_meters"], Decimal("15.0000"))
        self.assertEqual(values["calculation_snapshot"], self.snapshot)

    def test_purchase_requires_both_roots_and_length(self):
        with self.assertRaises(ValidationError):
            purchase_pipe_values(self.snapshot, {"actual_bar_count": 3})
        with self.assertRaises(ValidationError):
            purchase_pipe_values(self.snapshot, {"raw_bar_length_m": "5.00"})

    def test_draft_can_leave_roots_and_length_empty(self):
        values = purchase_pipe_values(self.snapshot, {})
        self.assertIsNone(values["actual_bar_count"])
        self.assertIsNone(values["actual_purchase_meters"])
        self.assertEqual(values["calculation_snapshot"]["schema_version"], 3)
