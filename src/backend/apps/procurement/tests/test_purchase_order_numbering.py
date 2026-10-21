from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from importlib import import_module
from threading import Barrier, Event
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import OperationalError, close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import ValidationError

from apps.core.models import DailyBusinessNumberCounter
from apps.core.numbering import next_business_number
from apps.boms.models import Bom, BomLine, BomSection
from apps.customers.models import CustomerAccount
from apps.organizations.models import Employee
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import Currency, NumberRule, ProductCategory, ProductionUnit

from ..models import (
    PurchaseContractTemplate,
    PurchaseContractTemplateVersion,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    SupplierPurchaseSheet,
)
from ..purchase_sheet_services import generate_supplier_purchase_sheets
from ..services import create_purchase_order, evaluate_purchase_source, next_purchase_order_number


class PurchaseNumberFixture:
    business_date = date(2099, 12, 20)
    prefix = "CGDD991220"
    legacy_prefix = "CGDD20991220"

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
    def test_shared_counter_continues_from_999_to_1000_and_1001(self):
        original = self.make_order(f"{self.legacy_prefix}99")
        DailyBusinessNumberCounter.objects.create(
            number_type="PURCHASE_ORDER", business_date=self.business_date, last_value=999,
        )
        with transaction.atomic():
            sheet_number = next_purchase_order_number(self.business_date)
            self.make_sheet(sheet_number, original)
            order_number = next_business_number("PURCHASE_ORDER", self.business_date)
            self.make_order(order_number)
        self.assertEqual(sheet_number, f"{self.prefix}1000")
        self.assertEqual(order_number, f"{self.prefix}1001")
        original.refresh_from_db()
        self.assertEqual(original.order_number, f"{self.legacy_prefix}99")

    def test_migration_seeds_numeric_maximum_across_both_models(self):
        order = self.make_order(f"{self.prefix}099")
        self.make_sheet(f"{self.prefix}100", order)
        self.make_sheet(f"{self.prefix}009", order)
        migration = import_module("apps.reference_data.migrations.0029_shared_daily_number_rules")
        migration.seed_daily_number_rules(apps, SimpleNamespace(connection=connection))
        self.assertEqual(next_purchase_order_number(self.business_date), f"{self.prefix}101")

    def test_new_day_starts_at_001_and_keeps_old_numbers(self):
        order = self.make_order(f"{self.legacy_prefix}99")
        sheet = self.make_sheet(f"{self.legacy_prefix}123", order)
        self.assertEqual(next_purchase_order_number(self.business_date), "CGDD991220001")
        self.assertEqual(next_purchase_order_number(date(2099, 12, 21)), "CGDD991221001")
        order.refresh_from_db()
        sheet.refresh_from_db()
        self.assertEqual(order.order_number, f"{self.legacy_prefix}99")
        self.assertEqual(sheet.sheet_number, f"{self.legacy_prefix}123")

    def test_number_fields_allow_legacy_and_extended_sequences(self):
        for model, field_name in ((PurchaseOrder, "order_number"), (SupplierPurchaseSheet, "sheet_number")):
            field = model._meta.get_field(field_name)
            numbers = [f"{self.legacy_prefix}{suffix}" for suffix in ("01", "99", "100", "9" * 38)]
            numbers += [f"{self.prefix}{suffix}" for suffix in ("001", "999", "1000", "9" * 40)]
            for number in numbers:
                with self.subTest(model=model.__name__, number=number):
                    field.run_validators(number)
            for number in (f"{self.prefix}01", f"{self.prefix}AB1", f"{self.prefix}{'9' * 41}", f"{self.legacy_prefix}{'9' * 39}"):
                with self.subTest(model=model.__name__, invalid_number=number):
                    with self.assertRaises(ModelValidationError):
                        field.run_validators(number)

    def test_deletion_keeps_counter_and_business_failure_rolls_back_allocation(self):
        order = self.make_order(next_purchase_order_number(self.business_date))
        order.delete()
        self.assertEqual(next_purchase_order_number(self.business_date), f"{self.prefix}002")
        with self.assertRaisesMessage(ValueError, "业务保存失败"):
            with transaction.atomic():
                self.assertEqual(next_purchase_order_number(self.business_date), f"{self.prefix}003")
                raise ValueError("业务保存失败")
        self.assertEqual(next_purchase_order_number(self.business_date), f"{self.prefix}003")

    def test_source_date_is_preserved_and_rejects_an_invalid_century(self):
        self.assertEqual(next_purchase_order_number(date(2000, 1, 1)), "CGDD000101001")
        self.business_date = date(1999, 12, 20)
        with self.assertRaisesMessage(ValidationError, "2000–2099"):
            next_purchase_order_number(self.business_date)

    def test_description_migration_keeps_padding_and_business_numbers(self):
        order = self.make_order(f"{self.legacy_prefix}99")
        sheet = self.make_sheet(f"{self.legacy_prefix}100", order)
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
        self.assertEqual(order.order_number, f"{self.legacy_prefix}99")
        self.assertEqual(sheet.sheet_number, f"{self.legacy_prefix}100")


@skipUnless(connection.vendor == "postgresql", "并发编号校验需要 PostgreSQL 事务锁")
class PurchaseOrderNumberingConcurrencyTests(PurchaseNumberFixture, TransactionTestCase):
    def make_purchase_payload(self):
        unit = ProductionUnit.objects.create(unit_code="NUM-LOCK", unit_name="编号锁测试件")
        category = ProductCategory.objects.create(item_type="MATERIAL", category_name="编号锁测试材料")
        material = RawMaterialInformation.objects.create(
            material_number="NUM-LOCK-MATERIAL", item_type="MATERIAL", category=category,
            material_name="锁测试配件", specification="测试规格", unit=unit,
        )
        task = self.make_task()
        task.status = "READY"
        task.save(update_fields=["status"])
        product = ProductionTaskProduct.objects.create(
            production_task=task, line_number=1, product_name_snapshot="锁测试产品",
            quantity=1, unit=unit, currency=self.currency, unit_price=1, total_amount=1, exchange_rate=1,
        )
        bom = Bom.objects.create(
            bom_number="BOM-NUM-LOCK", production_task=task, product_line=product,
            creation_method="BLANK", status="VERIFIED", order_quantity=1,
        )
        section = BomSection.objects.create(bom=bom, line_number=1, section_type="ACCESSORY", title="配件类")
        line = BomLine.objects.create(
            section=section, line_number=1, part_name="锁测试配件", unit=unit.unit_name,
            budget_quantity="1", raw_values={"source_inventory_material_id": str(material.pk)},
        )
        source = evaluate_purchase_source(task, bom_id=bom.pk)
        self.assertTrue(source["can_create"], source["blockers"])
        return task, {
            "production_task_id": task.pk, "bom_id": bom.pk, "source_revision": source["source_revision"],
            "lines": [{"bom_line_id": line.pk, "supplier_id": self.supplier.pk,
                       "actual_purchase_quantity": Decimal("1"), "unit_price": Decimal("1")}],
        }

    def test_generator_rejects_calls_outside_transaction(self):
        with self.assertRaisesMessage(RuntimeError, "必须在数据库事务中生成"):
            next_purchase_order_number(self.business_date)

    def test_concurrent_order_and_sheet_share_counter_on_first_insert_and_after_999(self):
        original = self.make_order(f"{self.legacy_prefix}99")
        for starting_value in (None, 999):
            with self.subTest(starting_value=starting_value):
                DailyBusinessNumberCounter.objects.filter(number_type="PURCHASE_ORDER", business_date=self.business_date).delete()
                if starting_value is not None:
                    DailyBusinessNumberCounter.objects.create(
                        number_type="PURCHASE_ORDER", business_date=self.business_date, last_value=starting_value,
                    )
                new_task = self.make_task()
                barrier = Barrier(2)

                def create_numbered_record(kind):
                    close_old_connections()
                    try:
                        barrier.wait(timeout=10)
                        with transaction.atomic():
                            if kind == "order":
                                number = next_business_number("PURCHASE_ORDER", self.business_date)
                                self.make_order(number, task=new_task)
                            else:
                                number = next_purchase_order_number(self.business_date)
                                self.make_sheet(number, original)
                        return number
                    finally:
                        connections.close_all()

                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(create_numbered_record, kind) for kind in ("order", "sheet")]
                    numbers = [future.result(timeout=20) for future in futures]
                first_value = (starting_value or 0) + 1
                self.assertEqual(set(numbers), {f"{self.prefix}{first_value:03d}", f"{self.prefix}{first_value + 1:03d}"})
                self.assertEqual(PurchaseOrder.objects.filter(order_number__in=numbers).count(), 1)
                self.assertEqual(SupplierPurchaseSheet.objects.filter(sheet_number__in=numbers).count(), 1)

    def test_order_supplier_lock_allows_concurrent_sheet_commit_but_blocks_supplier_edits(self):
        task, payload = self.make_purchase_payload()
        original = self.make_order(f"{self.legacy_prefix}99")
        original.status = "SUBMITTED"
        original.save(update_fields=["status"])
        PurchaseOrderLine.objects.create(
            purchase_order=original, line_number=1, supplier=self.supplier,
            section_type_snapshot="ACCESSORY", quantity_parse_status="READY",
        )
        counter_locked, supplier_locked, release_sheet = Event(), Event(), Event()

        def sheet_number():
            number = next_purchase_order_number(self.business_date)
            counter_locked.set()
            self.assertTrue(release_sheet.wait(timeout=10), "未释放采购表提交")
            return number

        def order_number():
            supplier_locked.set()
            return next_purchase_order_number(self.business_date)

        def run(kind):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                if kind == "sheet":
                    sheets = generate_supplier_purchase_sheets(
                        order_id=original.pk,
                        assignments=[{"supplier_id": self.supplier.pk, "template_version_id": self.template_version.pk}],
                        allowed_task_ids=[original.production_task_id], actor_employee=self.employee,
                    )
                    return sheets[0].sheet_number
                self.assertTrue(counter_locked.wait(timeout=10), "采购表未取得共用流水锁")
                return create_purchase_order(
                    validated_data=payload, allowed_task_ids=[task.pk], actor_employee=self.employee,
                ).order_number
            finally:
                connections.close_all()

        with patch("apps.procurement.purchase_sheet_services.next_purchase_order_number", side_effect=sheet_number), \
                patch("apps.procurement.services.next_purchase_order_number", side_effect=order_number):
            with ThreadPoolExecutor(max_workers=2) as pool:
                sheet = pool.submit(run, "sheet")
                order = pool.submit(run, "order")
                try:
                    self.assertTrue(supplier_locked.wait(timeout=10), "新采购未锁定供应商")
                    # 供应商编辑/禁用服务仍使用 FOR UPDATE，应继续被状态校验锁挡住。
                    with self.assertRaises(OperationalError) as blocked:
                        with transaction.atomic():
                            Supplier.objects.select_for_update(nowait=True).get(pk=self.supplier.pk)
                    self.assertEqual(blocked.exception.__cause__.sqlstate, "55P03")
                finally:
                    release_sheet.set()
                numbers = [sheet.result(timeout=20), order.result(timeout=20)]
        self.assertEqual(numbers, [f"{self.prefix}001", f"{self.prefix}002"])
        self.assertEqual(PurchaseOrder.objects.filter(order_number=numbers[1]).count(), 1)
        self.assertEqual(SupplierPurchaseSheet.objects.filter(sheet_number=numbers[0]).count(), 1)
