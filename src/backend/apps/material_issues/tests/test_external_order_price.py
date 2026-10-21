from decimal import Decimal, localcontext
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.inventory.tube_processing_services import metal_component_limits
from apps.material_issues.api.p4_serializers import P4ExternalOrderWriteSerializer
from apps.material_issues.models import MetalProcessingExternalOrder
from apps.material_issues import p4_services
from apps.workshop_config.models import Operation
from apps.workshop_reporting.models import WageScheme, WageSchemeCraft, WageSchemeLine, WorkItem, WorkReport, WorkReportLine
from .test_public_processing_flow import PublicProcessingFixture


class ExternalOrderPriceValidationTests(SimpleTestCase):
    def payload(self, price):
        return {"request_id": str(uuid4()), "factory_id": str(uuid4()),
                "craft_id": str(uuid4()), "allocated_pieces": 5, "unit_price": price}

    def test_price_accepts_two_decimal_places_and_zero(self):
        for price in ("1.25", "0"):
            serializer = P4ExternalOrderWriteSerializer(data=self.payload(price))
            self.assertTrue(serializer.is_valid(), serializer.errors)
            self.assertEqual(serializer.validated_data["unit_price"], Decimal(price))

    def test_price_rejects_invalid_values(self):
        for price in ("-1", "1.234", "NaN", "abc", True):
            serializer = P4ExternalOrderWriteSerializer(data=self.payload(price))
            self.assertFalse(serializer.is_valid())


class ExternalOrderPriceResultTests(SimpleTestCase):
    def test_large_planned_amount_preserves_cents_and_decimal_context(self):
        order = Mock(unit_price=Decimal("99999999999999.99"),
                     allocated_pieces=99999999999999, handoff_pieces=0,
                     returned_good_pieces=0, closure=None, handoff=None)
        order.good_returns.select_related.return_value.all.return_value = []
        with patch.object(p4_services, "_allocation_context", return_value={}), \
                patch.object(p4_services, "_p4_order_etag", return_value='"price-test"'), \
                patch.object(p4_services.AuditLog.objects, "filter") as audit_filter:
            audit_filter.return_value.order_by.return_value = []
            with localcontext() as context:
                context.prec = 28
                result = p4_services._order_result(order)
                self.assertEqual(result["planned_amount"], "9999999999999899000000000000.01")
                self.assertEqual(context.prec, 28)


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True, TUBE_OUTSOURCING_ENABLED=True)
class ExternalOrderPriceApiTests(PublicProcessingFixture, APITestCase):
    def setUp(self):
        super().setUp()
        # 公共夹具已通过真实领料 API 扣出12支；补齐同部位的工价和报工依据。
        f = self.f
        self.assertEqual(self.line.issue.stock_mode, "PUBLIC_V2")
        self.assertEqual(self.line.issued_quantity, 12)
        craft = f.schedule_product.crafts.get(plan_category="METAL").craft
        operation = Operation.objects.create(operation_number="P4-PRICE-OP", product_name=f.profile.part_name,
            craft=craft, name="金工完成", reporting_unit=self.line.unit)
        item = WorkItem.objects.create(product_line=f.product_line, workshop=self.workshop, craft=craft,
            operation=operation, unit=self.line.unit, identity_key="p4-price-report", display_name=f.profile.part_name,
            bom_component_identity=f.profile.component_identity, counting_mode="PIECE")
        scheme = WageScheme.objects.create(scheme_number="P4-PRICE-SCHEME", product_line=f.product_line,
            schedule_product=f.schedule_product, workshop=self.workshop, scope_craft=craft, status="APPROVED",
            effective_from=timezone.localdate(), approved_at=timezone.now(), approved_by_employee=f.employee,
            created_by_employee=f.employee, updated_by_employee=f.employee,
            product_name_snapshot=f.product_line.product_name_snapshot,
            product_number_snapshot=f.product_line.product_number_snapshot,
            operation_product_name_snapshot=f.profile.part_name)
        WageSchemeCraft.objects.create(scheme=scheme, craft=craft)
        required = f.product_line.quantity * f.profile.pieces_per_product
        scheme_line = WageSchemeLine.objects.create(scheme=scheme, work_item=item, line_number=1,
            display_name_snapshot=item.display_name, craft_name_snapshot=craft.name,
            operation_name_snapshot=operation.name, operation_number_snapshot=operation.operation_number,
            unit_name_snapshot="支", bom_component_identity_snapshot=f.profile.component_identity,
            counting_mode="PIECE", order_quantity_snapshot=f.product_line.quantity,
            required_quantity_snapshot=required, declared_price=1)
        report = WorkReport.objects.create(report_number="P4-PRICE-REPORT", production_date=timezone.localdate(),
            product_line=f.product_line, schedule_product=f.schedule_product, workshop=self.workshop,
            scheme=scheme, scheme_version_snapshot=scheme.version, recorder_employee=f.employee,
            updated_by_employee=f.employee, total_amount=12, client_request_id=uuid4(), request_payload_hash="p" * 64)
        WorkReportLine.objects.create(report=report, line_number=1, scheme_line=scheme_line, work_item=item,
            workshop_employee=self.recipient, quantity=12, order_quantity_snapshot=f.product_line.quantity,
            required_quantity_snapshot=required, unit_price_snapshot=1, amount=12,
            display_name_snapshot=item.display_name, craft_name_snapshot=craft.name,
            operation_name_snapshot=operation.name, unit_name_snapshot="支", employee_name_snapshot=self.recipient.name)
        basis = metal_component_limits(f.product_line)["components"][str(f.profile.component_identity)]
        self.assertTrue(basis["basis_ready"], basis["blockers"])
        self.assertEqual((basis["issued"], basis["allowance"]["reported_minimum"],
                          basis["allowance"]["remaining"]), (12, 12, 12))

    def test_price_is_saved_and_returned_without_stock_write(self):
        _, rework = self.create_rework(5)
        ledgers_before = self.ledger_counts()
        payload = {"request_id": str(uuid4()), "factory_id": str(self.f.factory.pk),
                   "craft_id": str(self.f.spray.pk), "allocated_pieces": 5, "unit_price": "1.25"}
        url = f"/api/v1/metal-processing-reworks/{rework.pk}/orders/"
        first = self.post(url, payload, expected=201).data["data"]
        self.assertEqual(Decimal(first["unit_price"]), Decimal("1.25"))
        self.assertEqual(Decimal(first["planned_amount"]), Decimal("6.25"))
        self.assertEqual(MetalProcessingExternalOrder.objects.get(pk=first["id"]).unit_price, Decimal("1.25"))
        again = self.post(url, payload, expected=201).data["data"]
        self.assertEqual(first["id"], again["id"])
        payload["unit_price"] = "2"
        self.post(url, payload, expected=409)
        self.assertEqual(self.ledger_counts(), ledgers_before)

    def test_legacy_order_does_not_invent_zero_price(self):
        order = self.create_order()
        response = self.client.get(f"/api/v1/metal-processing-external-orders/{order.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data["data"]["unit_price"])
        self.assertIsNone(response.data["data"]["planned_amount"])
