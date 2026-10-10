from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from importlib import import_module
from threading import Barrier
from types import SimpleNamespace
from unittest import skipUnless

from django.apps import apps
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import ValidationError

from apps.customers.models import CustomerAccount
from apps.organizations.models import Employee
from apps.production_tasks.models import ProductionTask
from apps.reference_data.models import Currency, NumberRule

from ..models import (
    PurchaseContractTemplate,
    PurchaseContractTemplateVersion,
    PurchaseOrder,
    Supplier,
    SupplierPurchaseSheet,
)
from ..services import PURCHASE_ORDER_DAILY_LIMIT, next_purchase_order_number


class PurchaseNumberFixture:
    business_date = date(2099, 12, 20)
    prefix = "CGDD20991220"

    def setUp(self):
        super().setUp()
        self.customer = CustomerAccount.objects.create(
            account_code="PUR-NUM-CUSTOMER", account_name="编号测试客户", primary_country_code="CN",
        )
        self.employee = Employee.objects.create(employee_code="PUR-NUM-EMP", display_name="编号测试员工")
        self.currency, _ = Currency.objects.get_or_create(
            code="CNY", defaults={"numeric_code": "156", "chinese_name": "人民币"},
        )
        self.supplier = Supplier.objects.create(
            supplier_number="GYS99871", supplier_type="MATERIAL",
            supplier_categories=["TUBE"], supplier_name="编号测试供应商",
        )
        template = PurchaseContractTemplate.objects.create(
            template_code="PUR-NUM-TEMPLATE", template_name="编号测试模板",
        )
        self.template_version = PurchaseContractTemplateVersion.objects.create(
            template=template, version_number=1,
        )
        self.task_index = 0

    def make_task(self):
        self.task_index += 1
        return ProductionTask.objects.create(
            task_number=f"PUR-NUM-TASK-{self.task_index}",
            contract_number=f"PUR-NUM-CONTRACT-{self.task_index}",
            order_source="NEW", order_number=f"PUR-NUM-SALES-{self.task_index}",
            customer_account=self.customer, salesperson=self.employee, currency=self.currency,
            order_date=self.business_date, delivery_date=self.business_date + timedelta(days=1),
            includes_tax=True, order_tolerance_percent=0, is_repeat_order=False,
            preproduction_sample_required=False, delivery_method="SINGLE",
        )

    def make_order(self, number, *, task=None):
        task = task or self.make_task()
        return PurchaseOrder.objects.create(
            order_number=number, production_task=task,
            production_task_number_snapshot=task.task_number,
            sales_order_number_snapshot=task.order_number,
            customer_name_snapshot=self.customer.account_name, source_revision="numbering-test",
        )

    def make_sheet(self, number, order):
        return SupplierPurchaseSheet.objects.create(
            sheet_number=number, purchase_order=order, supplier=self.supplier,
            supplier_number_snapshot=self.supplier.supplier_number,
            supplier_name_snapshot=self.supplier.supplier_name,
            template_version=self.template_version, is_current=False,
        )


class PurchaseOrderNumberingTests(PurchaseNumberFixture, TestCase):
    def test_shared_sequence_continues_from_99_to_100_and_101(self):
        original = self.make_order(f"{self.prefix}99")
        with transaction.atomic():
            number_100 = next_purchase_order_number(self.business_date)
            self.make_sheet(number_100, original)
            number_101 = next_purchase_order_number(self.business_date)
            self.make_order(number_101)
        self.assertEqual(number_100, f"{self.prefix}100")
        self.assertEqual(number_101, f"{self.prefix}101")
        original.refresh_from_db()
        self.assertEqual(original.order_number, f"{self.prefix}99")

    def test_uses_numeric_maximum_across_both_models(self):
        order = self.make_order(f"{self.prefix}99")
        self.make_sheet(f"{self.prefix}100", order)
        self.make_sheet(f"{self.prefix}09", order)
        self.assertEqual(next_purchase_order_number(self.business_date), f"{self.prefix}101")
        self.make_order(f"{self.prefix}120")
        self.assertEqual(next_purchase_order_number(self.business_date), f"{self.prefix}121")

    def test_new_day_starts_at_01_and_keeps_old_numbers(self):
        order = self.make_order(f"{self.prefix}99")
        sheet = self.make_sheet(f"{self.prefix}123", order)
        self.assertEqual(next_purchase_order_number(date(2099, 12, 21)), "CGDD2099122101")
        order.refresh_from_db()
        sheet.refresh_from_db()
        self.assertEqual(order.order_number, f"{self.prefix}99")
        self.assertEqual(sheet.sheet_number, f"{self.prefix}123")

    def test_number_fields_allow_legacy_and_extended_sequences(self):
        for model, field_name in ((PurchaseOrder, "order_number"), (SupplierPurchaseSheet, "sheet_number")):
            field = model._meta.get_field(field_name)
            for suffix in ("01", "99", "100", "101", "9" * 38):
                with self.subTest(model=model.__name__, suffix=suffix):
                    field.run_validators(f"{self.prefix}{suffix}")
            for suffix in ("1", "AB", "9" * 39):
                with self.subTest(model=model.__name__, invalid_suffix=suffix):
                    with self.assertRaises(ModelValidationError):
                        field.run_validators(f"{self.prefix}{suffix}")

    def test_last_50_character_number_is_allowed_then_rejected(self):
        self.make_order(f"{self.prefix}{PURCHASE_ORDER_DAILY_LIMIT - 1}")
        number = next_purchase_order_number(self.business_date)
        self.assertEqual(len(number), 50)
        self.assertEqual(number, f"{self.prefix}{PURCHASE_ORDER_DAILY_LIMIT}")
        self.make_order(number)
        with self.assertRaises(ValidationError) as caught:
            next_purchase_order_number(self.business_date)
        self.assertIn("38 位上限", str(caught.exception.detail))

    def test_description_migration_keeps_padding_and_business_numbers(self):
        order = self.make_order(f"{self.prefix}99")
        sheet = self.make_sheet(f"{self.prefix}100", order)
        rule, _ = NumberRule.objects.get_or_create(
            number_type="PURCHASE_ORDER",
            defaults={"chinese_name": "采购订单", "is_configured": False},
        )
        rule.sequence_padding = 2
        rule.description = "单日上限99张"
        rule.save(update_fields=["sequence_padding", "description"])
        module = import_module("apps.procurement.migrations.0020_expand_daily_purchase_number")
        module.update_purchase_number_description(apps, SimpleNamespace(connection=connection))
        rule.refresh_from_db()
        order.refresh_from_db()
        sheet.refresh_from_db()
        self.assertEqual(rule.sequence_padding, 2)
        self.assertIn("超过99继续100、101", rule.description)
        self.assertEqual(order.order_number, f"{self.prefix}99")
        self.assertEqual(sheet.sheet_number, f"{self.prefix}100")


@skipUnless(connection.vendor == "postgresql", "并发编号校验需要 PostgreSQL 事务锁")
class PurchaseOrderNumberingConcurrencyTests(PurchaseNumberFixture, TransactionTestCase):
    def test_generator_rejects_calls_outside_transaction(self):
        with self.assertRaisesMessage(RuntimeError, "必须在数据库事务中生成"):
            next_purchase_order_number(self.business_date)

    def test_concurrent_order_and_sheet_share_unique_numbers_after_99(self):
        original = self.make_order(f"{self.prefix}99")
        new_task = self.make_task()
        barrier = Barrier(2)

        def create_numbered_record(kind):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    number = next_purchase_order_number(self.business_date)
                    if kind == "order":
                        self.make_order(number, task=new_task)
                    else:
                        self.make_sheet(number, original)
                return number
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create_numbered_record, kind) for kind in ("order", "sheet")]
            numbers = [future.result(timeout=20) for future in futures]
        self.assertEqual(set(numbers), {f"{self.prefix}100", f"{self.prefix}101"})
        self.assertEqual(PurchaseOrder.objects.filter(order_number__in=numbers).count(), 1)
        self.assertEqual(SupplierPurchaseSheet.objects.filter(sheet_number__in=numbers).count(), 1)
