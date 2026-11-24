from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django.utils.datastructures import MultiValueDict
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory, APITestCase

from apps.production_tasks.api.serializers import (
    AiProductionTaskWriteSerializer,
    ProductionTaskPmcDecisionSerializer,
    ProductionTaskProductReadSerializer,
    ProductionTaskReadSerializer,
    ProductionTaskWriteSerializer,
)
from apps.production_tasks.cost_selectors import task_cost_summary
from apps.production_tasks.services import (
    _product_total, _production_rate_snapshot, _validate_task_tax, create_production_task,
)
from .test_production_task_api import ProductionTaskApiTests


class AiImportUnknownValueTests(SimpleTestCase):
    def test_ai_unknown_financial_fields_do_not_use_manual_defaults(self):
        fields = AiProductionTaskWriteSerializer().fields
        for name in ("currency_id", "includes_tax", "freight_amount", "other_fee_amount"):
            self.assertIsNone(fields[name].run_validation(None))
            self.assertIsNone(fields[name].get_default())
        product = fields["products"].child
        for name in ("currency_id", "unit_price", "exchange_rate"):
            self.assertIsNone(product.fields[name].run_validation(None))
            self.assertIsNone(product.fields[name].get_default())
        selected = product.fields["details"].child.fields["is_selected"]
        self.assertIsNone(selected.run_validation(None))
        self.assertIsNone(selected.get_default())
        self.assertIs(selected.run_validation(False), False)

    def test_manual_creation_still_rejects_unknown_values(self):
        fields = ProductionTaskWriteSerializer().fields
        for name in ("currency_id", "includes_tax", "freight_amount", "other_fee_amount"):
            with self.subTest(field=name), self.assertRaises(ValidationError):
                fields[name].run_validation(None)
        self.assertEqual(fields["freight_amount"].get_default(), Decimal("0"))
        product = fields["products"].child
        for name in ("currency_id", "unit_price", "exchange_rate"):
            with self.subTest(field=name), self.assertRaises(ValidationError):
                product.fields[name].run_validation(None)
        self.assertIs(product.fields["details"].child.fields["is_selected"].get_default(), False)

    def test_existing_unknown_task_edit_preserves_null(self):
        task = SimpleNamespace(currency_id=None, includes_tax=None)
        fields = ProductionTaskWriteSerializer(context={"current_task": task}).fields
        self.assertIsNone(fields["currency_id"].run_validation(None))
        self.assertIsNone(fields["products"].child.fields["unit_price"].run_validation(None))

    def test_pmc_preserves_only_existing_unknown_tax(self):
        unknown = ProductionTaskPmcDecisionSerializer(context={"current_task": SimpleNamespace(includes_tax=None)})
        self.assertIsNone(unknown.fields["includes_tax"].run_validation(None))
        known = ProductionTaskPmcDecisionSerializer(context={"current_task": SimpleNamespace(includes_tax=True)})
        with self.assertRaises(ValidationError):
            known.fields["includes_tax"].run_validation(None)

    def test_unknown_price_is_not_zero_and_known_zero_stays_zero(self):
        self.assertIsNone(_product_total(10, None))
        self.assertEqual(_product_total(10, Decimal("0")), Decimal("0.0000"))
        self.assertEqual(_product_total(3, Decimal("1.2500")), Decimal("3.7500"))

    def test_unknown_or_foreign_rate_is_never_a_cny_identity_snapshot(self):
        usd = SimpleNamespace(code="USD")
        self.assertEqual(_production_rate_snapshot(usd, None), {})
        self.assertEqual(_production_rate_snapshot(None, Decimal("1")), {})
        snapshot = _production_rate_snapshot(usd, Decimal("7.25"))
        self.assertEqual(snapshot["base_currency_code"], "USD")
        self.assertEqual(snapshot["quote_currency_code"], "CNY")
        self.assertEqual(snapshot["rate"], "7.25")
        self.assertNotEqual(snapshot["source_name"], "人民币恒等汇率")

    def test_nullable_local_amount_does_not_become_zero(self):
        serializer = ProductionTaskProductReadSerializer()
        line = SimpleNamespace(currency_id=None, unit_price=Decimal("5"), total_amount=Decimal("50"), exchange_rate=Decimal("1"))
        self.assertIsNone(serializer.get_local_unit_price(line))
        self.assertIsNone(serializer.get_local_total_amount(line))
        line.currency_id = "cny"
        line.exchange_rate = None
        self.assertIsNone(serializer.get_local_total_amount(line))

    def test_task_totals_remain_unknown_until_all_amounts_and_currency_known(self):
        products = Mock()
        line = SimpleNamespace(currency_id="cny", total_amount=None)
        products.all.return_value = [line]
        task = SimpleNamespace(currency_id="cny", products=products, freight_amount=Decimal("0"), other_fee_amount=Decimal("0"))
        serializer = ProductionTaskReadSerializer()
        self.assertIsNone(serializer.get_product_total_amount(task))
        self.assertIsNone(serializer.get_total_amount(task))
        line.total_amount = Decimal("25")
        task.freight_amount = None
        self.assertIsNone(serializer.get_total_amount(task))
        task.freight_amount = Decimal("0")
        self.assertEqual(serializer.get_total_amount(task), Decimal("25"))
        line.currency_id = "usd"
        self.assertIsNone(serializer.get_product_total_amount(task))

    def test_unknown_tax_does_not_waive_known_contradictions(self):
        _validate_task_tax(includes_tax=None, tax_rate=None, allow_unknown=True)
        _validate_task_tax(includes_tax=True, tax_rate=None, allow_unknown=True)
        for includes, rate, allow in [(None, None, False), (True, None, False), (False, 3, True), (True, 99, True)]:
            with self.subTest(includes=includes, rate=rate), self.assertRaises(ValidationError):
                _validate_task_tax(includes_tax=includes, tax_rate=rate, allow_unknown=allow)

    def test_unknown_price_and_fee_cost_summary_is_incomplete(self):
        task = SimpleNamespace(pk="task", currency=None, freight_amount=None, other_fee_amount=Decimal("0"))
        line = SimpleNamespace(total_amount=None, currency=None, exchange_rate=None, exchange_rate_snapshot={})
        sources = dict(products=[line], purchases=[], sheets=[], allocations=[], reports=[], outsourcing=[], tube=[], deferred_sewing=[], receipt_only_deferred=[], expenses=[])
        with patch("apps.production_tasks.cost_selectors._cost_sources", return_value=sources):
            result = task_cost_summary(task=task)
        self.assertIsNone(result["order_amount"])
        self.assertIsNone(result["current_difference"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["missing_count"], 2)


class AiImportUnknownValueDatabaseTests(APITestCase):
    """须在登记并独占的测试库执行；不调用外部AI。"""
    setUp = ProductionTaskApiTests.setUp
    payload = ProductionTaskApiTests.payload

    def create_unknown_task(self):
        payload = self.payload(currency_id=None, includes_tax=None, tax_rate=None,
                               freight_amount=None, other_fee_amount=None)
        payload["products"][0].update(currency_id=None, unit_price=None, exchange_rate=None)
        payload["products"][0]["details"][0]["is_selected"] = None
        serializer = AiProductionTaskWriteSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        request = APIRequestFactory().post("/api/v1/ai-production-import/")
        request.user = self.user
        request.employee = self.employee
        task = create_production_task(validated_data=deepcopy(serializer.validated_data), files=MultiValueDict(),
                                      actor_employee=self.employee, request=request, allow_incomplete_import=True)
        return task, payload

    def test_unknown_draft_can_reopen_edit_and_submit_without_fabricated_money(self):
        task, _ = self.create_unknown_task()
        line = task.products.get()
        self.assertIsNone(task.currency_id)
        self.assertIsNone(line.unit_price)
        self.assertIsNone(line.total_amount)
        self.assertIsNone(line.details.get().is_selected)
        self.assertEqual(line.exchange_rate_snapshot, {})
        response = self.client.get(f"/api/v1/production-tasks/{task.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertIsNone(data["total_amount"])
        self.assertIsNone(data["products"][0]["local_total_amount"])
        edited = self.client.patch(f"/api/v1/production-tasks/{task.pk}/",
                                  {"special_requirements_html": "<p>只补备注</p>"}, format="json",
                                  HTTP_IF_MATCH=response["ETag"])
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertIsNone(edited.data["data"]["includes_tax"])
        self.assertIsNone(edited.data["data"]["freight_amount"])
        submitted = self.client.post(f"/api/v1/production-tasks/{task.pk}/submit/", {}, format="json",
                                     HTTP_IF_MATCH=edited["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertIsNone(submitted.data["data"]["products"][0]["unit_price"])

    def test_normal_create_endpoint_rejects_same_unknown_payload(self):
        _, payload = self.create_unknown_task()
        payload["task_number"] += "-2"
        response = self.client.post("/api/v1/production-tasks/", payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)

