from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.core.api.exceptions import Conflict
from apps.procurement.completion_services import generate_quality_returns, purchase_completion_summary


class WeightCompletionContractTests(SimpleTestCase):
    def setUp(self):
        self.receipt = SimpleNamespace(
            measurement_kind='PIPE', source_unit_text_snapshot='KG',
            inbound=SimpleNamespace(status='CONFIRMED'),
            received_quantity=Decimal('18'), accepted_quantity=Decimal('18'), return_quantity=Decimal('0'),
            received_weight_kg=Decimal('4.1'), accepted_weight_kg=Decimal('4.1'), return_weight_kg=Decimal('0'),
        )
        line = SimpleNamespace(actual_purchase_quantity=Decimal('5'),
            material_inbound_lines=SimpleNamespace(all=lambda: [self.receipt]))
        self.order = SimpleNamespace(status='PURCHASING', lines=SimpleNamespace(all=lambda: [line]))

    def test_completion_uses_real_weight_even_when_meter_quantity_exceeds_purchase(self):
        self.assertEqual(purchase_completion_summary(self.order)['inbound_status'], 'PARTIAL_RECEIVED')

    def test_missing_pipe_weight_never_falls_back_to_meters(self):
        for field in ('received_weight_kg', 'accepted_weight_kg', 'return_weight_kg'):
            original = getattr(self.receipt, field)
            setattr(self.receipt, field, None)
            with self.subTest(field=field), self.assertRaises(Conflict):
                purchase_completion_summary(self.order)
            setattr(self.receipt, field, original)

    def test_ordinary_kg_and_historical_meter_receipts_keep_quantity_fields(self):
        for kind, unit in (('OTHER', 'KG'), ('PIPE', '米')):
            self.receipt.measurement_kind = kind
            self.receipt.source_unit_text_snapshot = unit
            self.receipt.received_weight_kg = self.receipt.accepted_weight_kg = self.receipt.return_weight_kg = None
            with self.subTest(kind=kind, unit=unit):
                self.assertEqual(purchase_completion_summary(self.order)['inbound_status'], 'COMPLETED')

    def test_return_generation_rejects_missing_weight_before_writing(self):
        self.receipt.return_quantity = Decimal('6')
        self.receipt.return_weight_kg = None
        with self.assertRaises(Conflict):
            generate_quality_returns(inbound=None, lines=[self.receipt], actor_employee=None, request=None)

    def test_hardware_completion_uses_kg_and_rejects_missing_weight(self):
        self.receipt.measurement_kind = 'OTHER'
        self.receipt.calculation_snapshot = {'measurement_kind': 'HARDWARE_WEIGHT'}
        self.assertEqual(purchase_completion_summary(self.order)['inbound_status'], 'PARTIAL_RECEIVED')
        self.receipt.return_weight_kg = None
        with self.assertRaises(Conflict):
            generate_quality_returns(inbound=None, lines=[self.receipt], actor_employee=None, request=None)
