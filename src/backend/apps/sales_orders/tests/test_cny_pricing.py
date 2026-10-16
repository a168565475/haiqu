from datetime import timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.reference_data.models import Currency, ExchangeRate
from apps.sales_orders.models import SalesOrder
from apps.sales_orders.tests import test_sales_order_api as fixtures


class SpecificationDisplayTests(SimpleTestCase):
    def test_only_verified_trailing_color_material_are_removed(self):
        from apps.sales_orders.presentation import specification_display
        for original, expected in (
            ("45*52*47；加厚；颜色：酒红色；材质：尼龙", "45*52*47；加厚"),
            ("45*52*47;颜色:酒红色;材质:尼龙", "45*52*47"),
            ("45*52*47；颜色：蓝色", "45*52*47；颜色：蓝色"),
            ("45*52*47；颜色：酒红色；备注：保留", "45*52*47；颜色：酒红色；备注：保留"),
        ):
            with self.subTest(original=original):
                line = SimpleNamespace(customer_specification_snapshot=original, specification_snapshot="",
                                       customer_color_snapshot="酒红色", material_snapshot="尼龙")
                self.assertEqual(specification_display(line), expected)
                self.assertEqual(line.customer_specification_snapshot, original)


class SalesCnyPricingTests(APITestCase):
    direct_payload = fixtures.SalesOrderApiTests.direct_payload
    create_direct = fixtures.SalesOrderApiTests.create_direct
    quotation_context = fixtures.SalesOrderApiTests.quotation_context
    quoted_payload = fixtures.SalesOrderApiTests.quoted_payload
    confirmed_change_payload = fixtures.SalesOrderApiTests.confirmed_change_payload

    def setUp(self):
        fixtures.SalesOrderApiTests.setUp(self)
        ExchangeRate.objects.update(status="INACTIVE")
        self.usd = Currency.objects.get(code="USD")
        self.cny = Currency.objects.get(code="CNY")

    def rate(self, value="7.12345678", currency=None, **values):
        return ExchangeRate.objects.create(
            base_currency=currency or self.usd, quote_currency=self.cny, rate=value,
            effective_date=values.pop("effective_date", timezone.localdate()), source_name="配置测试来源",
            source_version="v1", **values,
        )

    def create_foreign(self, rate, **overrides):
        values = {"currency_code": rate.base_currency.code, "exchange_rate_record_id": str(rate.pk)}
        values.update(overrides)
        return self.create_direct(**values)

    def confirm(self, created):
        response = self.client.post(
            f"/api/v1/sales-orders/{created.data['data']['id']}/confirm/", {}, format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_create_freezes_config_rate_and_rounds_unit_before_quantity(self):
        rate = self.rate("1.00010000")
        payload = self.direct_payload(quantity="3", unit_price="0.5000")
        payload.update(currency_code="USD", exchange_rate_record_id=str(rate.pk), exchange_rate="999")
        response = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data["data"]
        self.assertIn("total_amount_cny", data)
        self.assertEqual(Decimal(data["exchange_rate"]), Decimal("1.00010000"))
        self.assertEqual(data["exchange_rate_record_id"], str(rate.pk))
        self.assertEqual(data["exchange_rate_snapshot"]["capture_reason"], "CREATED")
        self.assertEqual(Decimal(data["lines"][0]["unit_price_cny"]), Decimal("0.5001"))
        self.assertEqual(Decimal(data["lines"][0]["line_total_cny"]), Decimal("1.5003"))
        self.assertEqual(Decimal(data["total_amount_cny"]), Decimal("1.5003"))
        saved = SalesOrder.objects.get(pk=data["id"])
        self.assertEqual(saved.total_amount_cny, Decimal("1.5003"))
        self.assertEqual(saved.lines.get().unit_price_cny, Decimal("0.5001"))

    def test_zero_amount_is_valid_frozen_pricing(self):
        response = self.create_direct(lines=[{**self.direct_payload()["lines"][0], "unit_price": "0"}])
        self.assertIn("total_amount_cny", response.data["data"])
        self.assertEqual(Decimal(response.data["data"]["total_amount_cny"]), Decimal("0"))
        self.confirm(response)

    def test_missing_or_future_rate_cannot_create_foreign_order(self):
        for future in (False, True):
            if future:
                self.rate(effective_date=timezone.localdate() + timedelta(days=1))
            payload = self.direct_payload()
            payload["currency_code"] = "USD"
            response = self.client.post("/api/v1/sales-orders/", payload, format="json")
            self.assertEqual(response.status_code, 400, response.data)
            self.assertEqual(SalesOrder.objects.count(), 0)

    def test_cny_overflow_returns_validation_error_and_rolls_back_order(self):
        rate = self.rate("999999999999.00000000")
        payload = self.direct_payload(quantity="1", unit_price="99999999999999.9999")
        payload.update(currency_code="USD", exchange_rate_record_id=str(rate.pk))
        response = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(SalesOrder.objects.exists())

    def test_preview_rejects_ambiguous_rates_and_invalid_currency(self):
        self.rate()
        self.rate("7.2")
        for code in ("USD", "BAD", "USD/CNY"):
            response = self.client.get("/api/v1/sales-orders/exchange-rate-preview/", {"currency_code": code})
            self.assertEqual(response.status_code, 400, response.data)

    def test_preview_uses_sales_permission_without_configuration_permission(self):
        rate = self.rate()
        user = get_user_model().objects.create_user(username="sales_rate_only")
        Employee.objects.create(user=user, employee_code="SALES_RATE_ONLY", display_name="销售汇率")
        user.user_permissions.add(Permission.objects.get(content_type__app_label="sales_orders", codename="add_salesorder"))
        self.client.force_authenticate(user)
        self.assertFalse(user.has_perm("reference_data.view_exchangerate"))
        response = self.client.get("/api/v1/sales-orders/exchange-rate-preview/", {"currency_code": "USD"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["exchange_rate_record_id"], str(rate.pk))
        self.assertEqual(response.data["data"]["exchange_rate"], "7.12345678")
        user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        denied = self.client.get("/api/v1/sales-orders/exchange-rate-preview/", {"currency_code": "USD"})
        self.assertEqual(denied.status_code, 403, denied.data)
        user.user_permissions.add(Permission.objects.get(content_type__app_label="sales_orders", codename="add_salesorder"))
        Employee.objects.filter(user=user).update(status="INACTIVE")
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        inactive = self.client.get("/api/v1/sales-orders/exchange-rate-preview/", {"currency_code": "USD"})
        self.assertEqual(inactive.status_code, 403, inactive.data)
        self.client.force_authenticate(None)
        anonymous = self.client.get("/api/v1/sales-orders/exchange-rate-preview/", {"currency_code": "USD"})
        self.assertEqual(anonymous.status_code, 401, anonymous.data)

    def test_stale_preview_rejected_without_creating_order(self):
        old = self.rate()
        old.status = "INACTIVE"
        old.save()
        self.rate("7.8", correction_of=old)
        payload = self.direct_payload()
        payload.update(currency_code="USD", exchange_rate_record_id=str(old.pk))
        response = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["error"]["code"], "SALES_EXCHANGE_RATE_CHANGED")
        self.assertFalse(SalesOrder.objects.exists())

    def test_draft_edit_and_confirmation_keep_frozen_rate_after_configuration_change(self):
        old = self.rate("7.10000001")
        created = self.create_foreign(old)
        old.status = "INACTIVE"
        old.save()
        latest = self.rate("8.2", correction_of=old)
        payload = self.direct_payload(quantity="12", unit_price="20")
        payload.update(currency_code="USD", exchange_rate_record_id=str(latest.pk), exchange_rate="99")
        edited = self.client.patch(
            f"/api/v1/sales-orders/{created.data['data']['id']}/", payload, format="json", HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(Decimal(edited.data["data"]["exchange_rate"]), Decimal("7.10000001"))
        self.assertIn("total_amount_cny", edited.data["data"])
        self.assertEqual(Decimal(edited.data["data"]["total_amount_cny"]), Decimal("1704"))
        confirmed = self.confirm(edited)
        snapshot = SalesOrder.objects.get(pk=confirmed.data["data"]["id"]).versions.get().snapshot
        self.assertEqual(snapshot["exchange_rate_record_id"], str(old.pk))
        self.assertEqual(Decimal(snapshot["total_amount_cny"]), Decimal("1704"))

    def test_currency_change_freezes_new_configuration(self):
        created = self.create_direct()
        rate = self.rate("7.2")
        payload = self.direct_payload()
        payload.update(currency_code="USD", exchange_rate_record_id=str(rate.pk))
        response = self.client.patch(
            f"/api/v1/sales-orders/{created.data['data']['id']}/", payload, format="json", HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("total_amount_cny", response.data["data"])
        self.assertEqual(Decimal(response.data["data"]["total_amount_cny"]), Decimal("1440"))
        self.assertEqual(response.data["data"]["exchange_rate_snapshot"]["capture_reason"], "CURRENCY_CHANGED")

    def test_confirmed_price_change_keeps_rate_and_updates_cny_version(self):
        rate = self.rate("7.2")
        confirmed = self.confirm(self.create_foreign(rate))
        rate.status = "INACTIVE"
        rate.save()
        self.rate("8.2", correction_of=rate)
        self.currency_code = "USD"
        payload = self.confirmed_change_payload(confirmed, unit_price="21")
        response = self.client.post(
            f"/api/v1/sales-orders/{confirmed.data['data']['id']}/confirmed-change/",
            {"order": payload, "change_reason": "客户调价", "customer_facing_change": True,
             "change_evidence_file_id": str(self.evidence.pk), "pmc_impact_confirmed": False},
            format="json", HTTP_IF_MATCH=confirmed["ETag"],
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("total_amount_cny", response.data["data"])
        self.assertEqual(Decimal(response.data["data"]["total_amount_cny"]), Decimal("1512"))
        self.assertEqual(response.data["data"]["exchange_rate_record_id"], str(rate.pk))

    def test_quotation_conversion_freezes_sales_rate(self):
        _, version, line = self.quotation_context()
        payload = self.quoted_payload(version, line)
        payload.update(exchange_rate="999")
        response = self.client.post("/api/v1/sales-orders/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn("total_amount_cny", response.data["data"])
        self.assertEqual(Decimal(response.data["data"]["total_amount_cny"]), Decimal("60"))
        self.assertEqual(Decimal(response.data["data"]["exchange_rate"]), Decimal("1"))


class LegacyCnyBackfillTests(APITestCase):
    setUp = SalesCnyPricingTests.setUp
    direct_payload = SalesCnyPricingTests.direct_payload
    create_direct = SalesCnyPricingTests.create_direct
    confirm = SalesCnyPricingTests.confirm
    rate = SalesCnyPricingTests.rate
    def legacy(self):
        response = self.confirm(self.create_direct())
        order = SalesOrder.objects.get(pk=response.data["data"]["id"])
        if hasattr(order, "total_amount_cny"):
            SalesOrder.objects.filter(pk=order.pk).update(
                currency_code="USD", exchange_rate=Decimal("1"), exchange_rate_record=None,
                exchange_rate_snapshot={}, total_amount_cny=None,
            )
            order.lines.update(unit_price_cny=None, line_total_cny=None)
        else:
            order.currency_code = "USD"
            order.save()
        order.refresh_from_db()
        return order

    def test_legacy_backfill_is_once_audited_and_does_not_rewrite_versions(self):
        rate = self.rate("7.2")
        order = self.legacy()
        frozen_version = order.versions.get().snapshot
        call_command("backfill_sales_order_cny", order_number=[order.order_number], stdout=StringIO())
        order.refresh_from_db()
        self.assertIsNone(order.total_amount_cny)
        previous_updated_at = order.updated_at
        call_command("backfill_sales_order_cny", apply=True, employee_code=self.employee.employee_code,
                     order_number=[order.order_number], stdout=StringIO())
        order.refresh_from_db()
        self.assertGreater(order.updated_at, previous_updated_at)
        first_updated_at = order.updated_at
        call_command("backfill_sales_order_cny", apply=True, employee_code=self.employee.employee_code,
                     order_number=[order.order_number], stdout=StringIO())
        order.refresh_from_db()
        self.assertEqual(order.updated_at, first_updated_at)
        self.assertEqual(order.total_amount_cny, Decimal("1440"))
        self.assertEqual(order.exchange_rate_record_id, rate.pk)
        self.assertEqual(order.exchange_rate_snapshot["capture_reason"], "LEGACY_BACKFILL")
        self.assertEqual(order.exchange_rate_snapshot["previous_exchange_rate"], "1.00000000")
        self.assertIn("captured_at", order.exchange_rate_snapshot)
        self.assertEqual(order.versions.get().snapshot, frozen_version)
        self.assertEqual(AuditLog.objects.filter(object_type="SALES_ORDER", object_id=order.pk, action="CNY_BACKFILLED").count(), 1)

    def test_backfill_validates_entire_batch_before_writing(self):
        self.rate("7.2")
        first = self.legacy()
        second = self.legacy()
        SalesOrder.objects.filter(pk=second.pk).update(currency_code="EUR")
        with self.assertRaises(CommandError):
            call_command("backfill_sales_order_cny", apply=True, employee_code=self.employee.employee_code, stdout=StringIO())
        first.refresh_from_db()
        self.assertIsNone(first.total_amount_cny)
        self.assertFalse(AuditLog.objects.filter(action="CNY_BACKFILLED").exists())
