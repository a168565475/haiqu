from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.finance.purchase_payable_serializers import (
    PurchasePayablePricingSerializer,
    PurchasePayableQuerySerializer,
)
from apps.finance.purchase_payable_services import line_amount, payable_quantity


class PurchasePayablePureTests(SimpleTestCase):
    def test_kg_uses_confirmed_weight_without_jin_conversion(self):
        line = SimpleNamespace(
            source_unit_text_snapshot="KG",
            accepted_weight_kg=Decimal("1900.5000"),
            accepted_quantity=Decimal("999.0000"),
        )
        self.assertEqual(payable_quantity(line), Decimal("1900.5000"))

    def test_other_unit_uses_confirmed_quantity(self):
        line = SimpleNamespace(
            source_unit_text_snapshot="PCS",
            accepted_weight_kg=Decimal("2.0000"),
            accepted_quantity=Decimal("100.0000"),
        )
        self.assertEqual(payable_quantity(line), Decimal("100.0000"))

    def test_amount_rounds_to_two_decimal_places(self):
        self.assertEqual(line_amount(Decimal("3"), Decimal("1.005")), Decimal("3.02"))

    def test_pricing_input_matches_frontend_contract_and_rejects_duplicate_lines(self):
        serializer = PurchasePayablePricingSerializer(data={
            "lines": [{
                "line_id": "00000000-0000-0000-0000-000000000001",
                "unit_price": "1.2500",
                "price_unit_text": "KG",
                "price_source": "采购确认",
                "price_remark": "含税口径待确认",
            }],
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        duplicate = PurchasePayablePricingSerializer(data={
            "lines": [
                {"line_id": "00000000-0000-0000-0000-000000000001", "unit_price": "1", "price_unit_text": "KG"},
                {"line_id": "00000000-0000-0000-0000-000000000001", "unit_price": "2", "price_unit_text": "KG"},
            ],
        })
        self.assertFalse(duplicate.is_valid())

    def test_query_accepts_inbound_date_range(self):
        serializer = PurchasePayableQuerySerializer(data={
            "inbound_date_from": "2026-11-01",
            "inbound_date_to": "2026-11-30",
            "page": "1",
            "page_size": "20",
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        invalid = PurchasePayableQuerySerializer(data={
            "inbound_date_from": "2026-12-01",
            "inbound_date_to": "2026-11-01",
        })
        self.assertFalse(invalid.is_valid())
