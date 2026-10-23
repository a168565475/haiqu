import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone as datetime_timezone
from importlib import import_module
from threading import Barrier
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.core.daily_numbering import DAILY_NUMBER_RULES, next_daily_business_number
from apps.core.models import DailyBusinessNumberCounter
from apps.core.numbering import next_business_number
from apps.procurement.tests import test_purchase_order_numbering as purchase_fixtures
from apps.reference_data.models import NumberRule
from apps.workshop_reporting.models import WorkReportHistory


class DailyBusinessNumberTests(TestCase):
    number_date = date(2099, 12, 20)

    def test_all_confirmed_namespaces_use_short_date_and_three_digits(self):
        expected_prefixes = {
            "BOM": "BOM", "PURCHASE_ORDER": "CGDD", "PURCHASE_REQUEST": "PR", "PURCHASE_RETURN": "TH",
            "PRODUCTION_SCHEDULE": "PC", "MATERIAL_INBOUND": "CLRK", "MATERIAL_ISSUE": "LL",
            "INTERNAL_SEMI_RECEIPT": "BNRK", "FINISHED_GOODS_RECEIPT": "CPRK", "FINISHED_GOODS_OUTBOUND": "CPCK",
            "OUTSOURCING_ORDER": "WF", "OUTSOURCING_DISPATCH": "FL", "OUTSOURCING_RETURN": "WH",
            "TUBE_OUTSOURCING_RECEIPT": "WFHK", "WORK_REPORT": "BG", "FINANCE_ACCOUNT": "ZH",
        }
        self.assertEqual(DAILY_NUMBER_RULES, expected_prefixes)
        for number_type, prefix in expected_prefixes.items():
            with self.subTest(number_type=number_type):
                self.assertEqual(next_daily_business_number(number_type, self.number_date), f"{prefix}991220001")

    def test_date_and_number_type_have_independent_counters(self):
        self.assertEqual(next_daily_business_number("OUTSOURCING_ORDER", self.number_date), "WF991220001")
        self.assertEqual(next_daily_business_number("OUTSOURCING_ORDER", self.number_date), "WF991220002")
        self.assertEqual(next_daily_business_number("OUTSOURCING_RETURN", self.number_date), "WH991220001")
        self.assertEqual(next_daily_business_number("OUTSOURCING_ORDER", date(2099, 12, 21)), "WF991221001")
        self.assertEqual(next_daily_business_number("WORK_REPORT", date(2028, 2, 29)), "BG280229001")
        self.assertEqual(next_daily_business_number("BOM", date(2000, 1, 1)), "BOM000101001")

    def test_shared_entry_uses_the_same_daily_counter_for_all_confirmed_types(self):
        for number_type, prefix in DAILY_NUMBER_RULES.items():
            with self.subTest(number_type=number_type):
                self.assertEqual(next_daily_business_number(number_type, self.number_date), f"{prefix}991220001")
                self.assertEqual(next_business_number(number_type, self.number_date), f"{prefix}991220002")

    def test_default_day_is_shanghai_even_when_active_timezone_is_utc(self):
        now = datetime(2099, 12, 20, 16, 30, tzinfo=datetime_timezone.utc)
        with timezone.override("UTC"), patch("apps.core.daily_numbering.timezone.now", return_value=now):
            self.assertEqual(next_daily_business_number("MATERIAL_ISSUE"), "LL991221001")

    def test_999_expands_without_truncation(self):
        DailyBusinessNumberCounter.objects.create(
            number_type="PURCHASE_ORDER", business_date=self.number_date, last_value=999,
        )
        self.assertEqual(next_daily_business_number("PURCHASE_ORDER", self.number_date), "CGDD9912201000")
        self.assertEqual(next_daily_business_number("PURCHASE_ORDER", self.number_date), "CGDD9912201001")

    def test_business_failure_rolls_back_first_insert_and_later_increment(self):
        with self.assertRaisesMessage(ValueError, "业务失败"):
            with transaction.atomic():
                next_daily_business_number("BOM", self.number_date)
                raise ValueError("业务失败")
        self.assertFalse(DailyBusinessNumberCounter.objects.filter(number_type="BOM").exists())
        self.assertEqual(next_daily_business_number("BOM", self.number_date), "BOM991220001")
        with self.assertRaisesMessage(ValueError, "业务失败"):
            with transaction.atomic():
                self.assertEqual(next_daily_business_number("BOM", self.number_date), "BOM991220002")
                raise ValueError("业务失败")
        self.assertEqual(next_daily_business_number("BOM", self.number_date), "BOM991220002")

    def test_unsupported_types_and_invalid_dates_do_not_allocate(self):
        for number_type in ("CUSTOMER", "PRODUCTION_TASK", "WAGE_SCHEME", "UNKNOWN"):
            with self.subTest(number_type=number_type), self.assertRaises(ValueError):
                next_daily_business_number(number_type, self.number_date)
        for invalid_date in ("2099-12-20", datetime(2099, 12, 20), 0):
            with self.subTest(business_date=invalid_date), self.assertRaises(ValueError):
                next_daily_business_number("BOM", invalid_date)
        self.assertFalse(DailyBusinessNumberCounter.objects.exists())

    def test_dates_outside_short_year_range_are_validation_errors_without_allocation(self):
        for invalid_date in (date(1999, 12, 31), date(2100, 1, 1)):
            with self.subTest(business_date=invalid_date), self.assertRaisesMessage(ValidationError, "2000–2099"):
                next_daily_business_number("MATERIAL_INBOUND", invalid_date)
        self.assertFalse(DailyBusinessNumberCounter.objects.exists())

    def test_database_rejects_duplicate_namespace_day_and_nonpositive_counter(self):
        DailyBusinessNumberCounter.objects.create(number_type="BOM", business_date=self.number_date, last_value=1)
        for last_value in (1, 0, -1):
            with self.subTest(last_value=last_value), self.assertRaises(IntegrityError), transaction.atomic():
                DailyBusinessNumberCounter.objects.create(
                    number_type="BOM" if last_value == 1 else "MATERIAL_ISSUE",
                    business_date=self.number_date, last_value=last_value,
                )

    def test_daily_rules_are_registered_without_postgresql_sequences(self):
        for number_type, prefix in DAILY_NUMBER_RULES.items():
            with self.subTest(number_type=number_type):
                rule = NumberRule.objects.get(number_type=number_type)
                self.assertEqual((rule.prefix, rule.format_pattern, rule.sequence_padding), (prefix, "{prefix}{short_date}{sequence}", 3))
                self.assertEqual((rule.sequence_name, rule.reset_policy, rule.date_granularity), ("", "DAILY", "DAY"))
                self.assertTrue(rule.is_configured)

    def test_configured_never_rule_still_requires_sequence(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            NumberRule.objects.create(
                number_type="TEST_MISSING_SEQUENCE", chinese_name="缺少序列", prefix="TEST",
                format_pattern="{prefix}{sequence}", reset_policy="NEVER", sequence_name="",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            NumberRule.objects.create(
                number_type="TEST_MISSING_FORMAT", chinese_name="缺少格式", prefix="TEST",
                format_pattern="", reset_policy="DAILY", sequence_name="",
            )


class DailyNumberMigrationTests(purchase_fixtures.PurchaseNumberFixture, TestCase):
    def test_seed_keeps_business_numbers_and_takes_shared_and_deleted_history_maximum(self):
        old_order = self.make_order("CGDD2099122001")
        ambiguous_old_order = self.make_order("CGDD2010011001")
        new_order = self.make_order("CGDD991220005")
        sheet = self.make_sheet("CGDD991220008", new_order)
        history = WorkReportHistory.objects.create(
            client_request_id=uuid.uuid4(), report_id=uuid.uuid4(), report_number="BG991220030",
            request_payload_hash="a" * 64, deleted_at=timezone.now(),
        )
        AuditLog.objects.create(
            object_type="PURCHASE_ORDER", object_id=uuid.uuid4(), action="DELETED", occurred_at=timezone.now(),
            before_data={"order_number": "CGDD991220010", "deleted_supplier_purchase_sheets": [{"sheet_number": "CGDD991220015"}]},
        )
        AuditLog.objects.create(
            object_type="SUPPLIER_PURCHASE_SHEET", object_id=uuid.uuid4(), action="DELETED", occurred_at=timezone.now(),
            before_data={"sheet_number": "CGDD991220020"},
        )
        AuditLog.objects.create(
            object_type="OUTSOURCING_ORDER", object_id=uuid.uuid4(), action="DELETED", occurred_at=timezone.now(),
            before_data={"order_number": "WF991220040"},
        )
        unaffected_rules = list(NumberRule.objects.exclude(number_type__in=DAILY_NUMBER_RULES).order_by("pk").values())
        migration = import_module("apps.reference_data.migrations.0029_shared_daily_number_rules")
        migration.seed_daily_number_rules(apps, SimpleNamespace(connection=connection))
        self.assertEqual(next_daily_business_number("PURCHASE_ORDER", self.business_date), "CGDD991220021")
        self.assertEqual(next_daily_business_number("WORK_REPORT", self.business_date), "BG991220031")
        self.assertEqual(next_daily_business_number("OUTSOURCING_ORDER", self.business_date), "WF991220041")
        self.assertEqual(next_daily_business_number("PURCHASE_ORDER", date(2020, 10, 1)), "CGDD2010011002")
        migration.seed_daily_number_rules(apps, SimpleNamespace(connection=connection))
        self.assertEqual(next_daily_business_number("PURCHASE_ORDER", self.business_date), "CGDD991220022")
        for record in (old_order, ambiguous_old_order, new_order, sheet, history):
            record.refresh_from_db()
        self.assertEqual(old_order.order_number, "CGDD2099122001")
        self.assertEqual(ambiguous_old_order.order_number, "CGDD2010011001")
        self.assertEqual(new_order.order_number, "CGDD991220005")
        self.assertEqual(sheet.sheet_number, "CGDD991220008")
        self.assertEqual(history.report_number, "BG991220030")
        self.assertEqual(
            list(NumberRule.objects.exclude(number_type__in=DAILY_NUMBER_RULES).order_by("pk").values()), unaffected_rules,
        )

    def test_deleting_a_numbered_business_record_does_not_reuse_its_number(self):
        number = next_daily_business_number("PURCHASE_ORDER", self.business_date)
        order = self.make_order(number)
        order.delete()
        self.assertEqual(next_daily_business_number("PURCHASE_ORDER", self.business_date), "CGDD991220002")

    def test_seed_only_recognizes_valid_new_format(self):
        migration = import_module("apps.reference_data.migrations.0029_shared_daily_number_rules")
        self.assertEqual(migration.parse_daily_number("CGDD2602281000", "CGDD"), (date(2026, 2, 28), 1000))
        for number in ("CGDD2026102001", "CGDD260229001", "CGDD260228000", "CGDD26022801", "CGDD2602280001", "CGDD-260228-001", None):
            with self.subTest(number=number):
                self.assertIsNone(migration.parse_daily_number(number, "CGDD"))


@skipUnless(connection.vendor == "postgresql", "并发日流水校验需要 PostgreSQL")
class DailyNumberConcurrencyTests(TransactionTestCase):
    # 这里只操作 core 计数表，避免并发测试的 flush 清空其他模块的迁移夹具。
    available_apps = ["apps.core"]
    number_date = date(2099, 12, 20)

    def test_generator_requires_business_transaction(self):
        with self.assertRaisesMessage(RuntimeError, "必须在数据库事务中生成"):
            next_daily_business_number("MATERIAL_ISSUE", self.number_date)

    def test_concurrent_first_insert_and_existing_counter_are_unique(self):
        for starting_value in (None, 999):
            with self.subTest(starting_value=starting_value):
                DailyBusinessNumberCounter.objects.all().delete()
                if starting_value is not None:
                    DailyBusinessNumberCounter.objects.create(
                        number_type="OUTSOURCING_ORDER", business_date=self.number_date, last_value=starting_value,
                    )
                barrier = Barrier(4)

                def allocate():
                    close_old_connections()
                    try:
                        barrier.wait(timeout=10)
                        with transaction.atomic():
                            return next_daily_business_number("OUTSOURCING_ORDER", self.number_date)
                    finally:
                        connections.close_all()

                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures = [pool.submit(allocate) for _ in range(4)]
                    numbers = [future.result(timeout=20) for future in futures]
                first_value = (starting_value or 0) + 1
                self.assertSetEqual(set(numbers), {f"WF991220{value:03d}" for value in range(first_value, first_value + 4)})
                self.assertEqual(DailyBusinessNumberCounter.objects.get().last_value, first_value + 3)
