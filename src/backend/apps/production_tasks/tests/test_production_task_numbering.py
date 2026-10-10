from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.customers.models import CustomerAccount
from apps.organizations.models import Employee
from apps.procurement.models import PurchaseOrder
from apps.production_tasks.management.commands.renumber_production_tasks import (
    CONFIRM_TOKEN,
    Command,
)
from apps.production_tasks.models import DeliveryMethod, OrderSource, ProductionTask
from apps.production_tasks.numbering import next_production_task_number
from apps.reference_data.models import Currency


class ProductionTaskNumberingTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        user = get_user_model().objects.create_superuser(
            username="production_number_admin",
            email="production-number-admin@example.com",
            password="test-password",
        )
        self.actor = Employee.objects.create(
            user=user,
            employee_code="NUMBER_ADMIN",
            display_name="生产编号管理员",
        )
        self.customer = CustomerAccount.objects.create(
            account_code="NUMBER_CUSTOMER",
            account_name="生产编号测试客户",
            primary_country_code="CN",
        )
        self.currency, self.currency_created = Currency.objects.get_or_create(
            code="CNY",
            defaults={
                "numeric_code": "156",
                "chinese_name": "人民币",
                "english_name": "Renminbi",
                "symbol": "¥",
            },
        )

    def _fixture_teardown(self):
        # 并发测试需要真实提交，但全库 flush 会删除由迁移建立的公共产品夹具，
        # 因此只清理本测试以固定前缀创建的数据。
        PurchaseOrder.objects.filter(
            production_task__contract_number__startswith="NUMBER-CONTRACT-",
        ).delete()
        # 审计表由数据库触发器保护为只增不删；TRUNCATE 仅用于销毁隔离测试库数据。
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE TABLE audit_log")
        ProductionTask.objects.filter(contract_number__startswith="NUMBER-CONTRACT-").delete()
        CustomerAccount.objects.filter(account_code="NUMBER_CUSTOMER").delete()
        Employee.objects.filter(employee_code="NUMBER_ADMIN").delete()
        get_user_model().objects.filter(username="production_number_admin").delete()
        if self.currency_created:
            Currency.objects.filter(pk=self.currency.pk).delete()

    def create_task(self, task_number, sequence, order_date=date(2026, 9, 14)):
        return ProductionTask.objects.create(
            task_number=task_number,
            contract_number=f"NUMBER-CONTRACT-{sequence:03d}",
            order_source=OrderSource.NEW,
            order_number=f"NUMBER-ORDER-{sequence:03d}",
            customer_account=self.customer,
            order_date=order_date,
            delivery_date=order_date,
            salesperson=self.actor,
            currency=self.currency,
            includes_tax=False,
            order_tolerance_percent=Decimal("0"),
            is_repeat_order=False,
            preproduction_sample_required=False,
            delivery_method=DeliveryMethod.SINGLE,
        )

    def test_renumber_requires_preflight_guards_and_repairs_snapshots_on_rerun(self):
        first = self.create_task("HT-202609-000011", 1)
        second = self.create_task("MO-202609-000012", 2)
        purchase_order = PurchaseOrder.objects.create(
            order_number="CGDD2026091401",
            production_task=first,
            production_task_number_snapshot=first.task_number,
            sales_order_number_snapshot=first.order_number,
            customer_name_snapshot=self.customer.account_name,
            source_revision="numbering-test",
            currency=self.currency,
            currency_code_snapshot=self.currency.code,
            created_by_employee=self.actor,
        )
        command = Command()
        tasks, _, _, digest = command._plan(2026, 201)

        with self.assertRaises(CommandError):
            call_command(
                "renumber_production_tasks",
                year=2026,
                current_sequence=201,
                commit=True,
                confirm=CONFIRM_TOKEN,
                actor_employee_code=self.actor.employee_code,
            )

        call_command(
            "renumber_production_tasks",
            year=2026,
            current_sequence=201,
            commit=True,
            confirm=CONFIRM_TOKEN,
            actor_employee_code=self.actor.employee_code,
            expected_task_count=len(tasks),
            expected_old_number_sha256=digest,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        purchase_order.refresh_from_db()
        self.assertEqual([first.task_number, second.task_number], ["HT26200", "HT26201"])
        self.assertEqual(purchase_order.production_task_number_snapshot, "HT26200")
        self.assertEqual(
            AuditLog.objects.filter(action="TASK_NUMBER_RENUMBERED").count(),
            2,
        )

        PurchaseOrder.objects.filter(pk=purchase_order.pk).update(
            production_task_number_snapshot="BROKEN-SNAPSHOT",
        )
        tasks, _, _, digest = command._plan(2026, 201)
        call_command(
            "renumber_production_tasks",
            year=2026,
            current_sequence=201,
            commit=True,
            confirm=CONFIRM_TOKEN,
            actor_employee_code=self.actor.employee_code,
            expected_task_count=len(tasks),
            expected_old_number_sha256=digest,
        )
        purchase_order.refresh_from_db()
        self.assertEqual(purchase_order.production_task_number_snapshot, "HT26200")
        self.assertEqual(
            AuditLog.objects.filter(action="TASK_NUMBER_RENUMBERED").count(),
            2,
        )
        with transaction.atomic():
            self.assertEqual(next_production_task_number(date(2026, 12, 31)), "HT26202")

    def test_two_concurrent_creations_receive_distinct_yearly_numbers(self):
        def create_in_thread(sequence):
            close_old_connections()
            try:
                with transaction.atomic():
                    task_number = next_production_task_number(date(2026, 9, 14))
                    self.create_task(task_number, sequence)
                    return task_number
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            numbers = list(executor.map(create_in_thread, [1, 2]))

        self.assertEqual(set(numbers), {"HT26001", "HT26002"})

    def test_yearly_limit_rejects_sequence_above_999(self):
        self.create_task("HT26999", 999)
        with transaction.atomic(), self.assertRaises(ValidationError):
            next_production_task_number(date(2026, 12, 31))
