from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.workshop_reporting.api.views import _estimated_plan_wage
from apps.workshop_reporting.models import WageSchemeLineStatus


class EstimatedPlanWageTests(SimpleTestCase):
    def test_sums_required_quantity_times_declared_price_for_active_lines(self):
        scheme = SimpleNamespace(
            lines=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        status=WageSchemeLineStatus.ACTIVE,
                        required_quantity_snapshot=Decimal("200"),
                        declared_price=Decimal("2.345"),
                    ),
                    SimpleNamespace(
                        status="DISABLED",
                        required_quantity_snapshot=Decimal("999"),
                        declared_price=Decimal("99"),
                    ),
                ]
            )
        )

        self.assertEqual(_estimated_plan_wage(scheme), "469.0000")

    def test_returns_none_when_an_active_line_has_no_required_quantity(self):
        scheme = SimpleNamespace(
            lines=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        status=WageSchemeLineStatus.ACTIVE,
                        required_quantity_snapshot=None,
                        declared_price=Decimal("2.345"),
                    )
                ]
            )
        )

        self.assertIsNone(_estimated_plan_wage(scheme))
