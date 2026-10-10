import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.boms.management.commands.enrich_flow_boms import Command


class _RelatedLines:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class EnrichFlowBomsCommandTests(SimpleTestCase):
    def _order(self, line_ids):
        order_id = uuid.uuid4()
        lines = [
            SimpleNamespace(
                bom_id=uuid.UUID(int=10),
                bom_line_id=line_id,
                source_bom_line_id_snapshot=line_id,
                required_quantity=Decimal("2.0000"),
                actual_purchase_quantity=Decimal("2.0000"),
            )
            for line_id in line_ids
        ]
        return SimpleNamespace(
            pk=order_id,
            production_task=object(),
            source_revision="revision-1",
            lines=_RelatedLines(lines),
        )

    @patch("apps.boms.management.commands.enrich_flow_boms.evaluate_purchase_source")
    def test_rejects_no_op_when_purchase_order_is_missing_source_line(self, evaluate):
        first_line_id = uuid.uuid4()
        missing_line_id = uuid.uuid4()
        order = self._order([first_line_id])
        evaluate.return_value = {
            "blockers": [{"code": "PURCHASE_ORDER_EXISTS"}],
            "existing_purchase_order_id": str(order.pk),
            "source_revision": "revision-1",
            "preview_lines": [
                {"bom_line_id": first_line_id, "required_quantity": Decimal("2")},
                {"bom_line_id": missing_line_id, "required_quantity": Decimal("2")},
            ],
        }
        self.assertFalse(Command._purchase_sources_complete([order]))
