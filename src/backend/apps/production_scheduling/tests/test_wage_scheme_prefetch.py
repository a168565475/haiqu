from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.db.models.query import ModelIterable
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.workshop_reporting.models import WageScheme, WageSchemeLine, WageSchemeStatus

from ..list_amounts import schedule_list_amounts
from . import test_detail_reporting as detail_fixtures


@contextmanager
def capture_loaded_wage_rows():
    loaded = {"schemes": [], "line_schemes": []}
    original_iter = ModelIterable.__iter__

    def record_rows(iterable):
        # 保留真实查询和预取，仅观察实际从数据库实例化的行，不匹配 SQL 文本。
        for row in original_iter(iterable):
            if isinstance(row, WageScheme):
                loaded["schemes"].append(row.pk)
            elif isinstance(row, WageSchemeLine):
                loaded["line_schemes"].append(row.scheme_id)
            yield row

    with patch.object(ModelIterable, "__iter__", record_rows):
        yield loaded


@override_settings(
    MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False, TIME_ZONE="Asia/Shanghai",
)
class WageSchemePrefetchTests(APITestCase):
    # 只复用夹具方法，避免继承并重复发现已有详情测试。
    setUp = detail_fixtures.DetailReportingTests.setUp
    scheme_payload = detail_fixtures.DetailReportingTests.scheme_payload
    create_approved_scheme = detail_fixtures.DetailReportingTests.create_approved_scheme
    copy_values = detail_fixtures.DetailReportingTests.copy_values
    copy_row = detail_fixtures.DetailReportingTests.copy_row
    summary = detail_fixtures.DetailReportingTests.summary

    def expired_scheme(self):
        approved = self.create_approved_scheme().data["data"]
        scheme = WageScheme.objects.get(pk=approved["id"])
        scheme.effective_from = timezone.localdate() - timedelta(days=2)
        scheme.effective_to = timezone.localdate() - timedelta(days=1)
        scheme.save(update_fields=["effective_from", "effective_to", "updated_at"])
        return scheme

    def next_version(self, previous, **changes):
        scheme = self.copy_row(
            previous, scheme_number=f"GJ-PREFETCH-V{previous.version + 1}",
            parent_scheme_id=previous.pk, version=previous.version + 1, **changes,
        )
        self.copy_row(previous.lines.get(), scheme_id=scheme.pk)
        return scheme

    def version_chain(self, *, open_ended=False):
        expired = self.expired_scheme()
        today = timezone.localdate()
        current = self.next_version(
            expired, effective_from=today, effective_to=None if open_ended else today,
        )
        schemes = [expired, current]
        # 开放结束日已覆盖未来日期，不能再创建同范围的未来批准版本。
        if not open_ended:
            schemes.append(self.next_version(
                current, effective_from=today + timedelta(days=1), effective_to=None,
            ))
        schemes.append(self.next_version(
            schemes[-1], status=WageSchemeStatus.DRAFT,
            effective_from=None, effective_to=None, approved_at=None, approved_by_employee_id=None,
        ))
        return current, schemes

    def list_summary(self):
        self.schedule_product.active_crafts = list(
            self.schedule_product.crafts.filter(removed_at__isnull=True).select_related("craft__workshop")
        )
        self.schedule.active_products = [self.schedule_product]
        request = SimpleNamespace(user=self.user, employee=self.employee)
        return schedule_list_amounts(request, [self.schedule])[str(self.schedule.pk)]

    def assert_current_version_loads(self, current, schemes):
        for path in ("list", "detail"):
            with self.subTest(path=path):
                with capture_loaded_wage_rows() as loaded:
                    result = self.list_summary() if path == "list" else self.summary()
                if path == "list":
                    self.assertEqual(result["estimated_wage"], "469.00")
                    self.assertCountEqual(loaded["schemes"], [current.pk])
                else:
                    self.assertEqual(result["estimated_wage"], "469.0000")
                    row = result["internal_plans"][0]
                    self.assertEqual(row["scheme_id"], str(current.pk))
                    self.assertEqual(row["wage_status"], "APPROVED")
                    self.assertEqual(row["estimated_amount_status"], "READY")
                    self.assertCountEqual(loaded["schemes"], [scheme.pk for scheme in schemes])
                self.assertEqual(result["reported_amount"], "0.00")
                self.assertCountEqual(loaded["line_schemes"], [current.pk])

    def test_only_today_effective_version_loads_lines_in_list_and_detail(self):
        current, schemes = self.version_chain()
        self.assert_current_version_loads(current, schemes)

    def test_open_ended_effective_version_keeps_its_lines_in_list_and_detail(self):
        current, schemes = self.version_chain(open_ended=True)
        self.assert_current_version_loads(current, schemes)

    def test_detail_keeps_latest_scheme_metadata_without_loading_inapplicable_lines(self):
        latest = self.expired_scheme()
        schemes = [latest]
        for state, changes, expected_status in (
            ("expired", None, "NO_EFFECTIVE_VERSION"),
            ("future", {
                "effective_from": timezone.localdate() + timedelta(days=1), "effective_to": None,
            }, "NO_EFFECTIVE_VERSION"),
            ("draft", {
                "status": WageSchemeStatus.DRAFT, "effective_from": None, "effective_to": None,
                "approved_at": None, "approved_by_employee_id": None,
            }, "DRAFT"),
        ):
            if changes is not None:
                latest = self.next_version(latest, **changes)
                schemes.append(latest)
            with self.subTest(state=state):
                with capture_loaded_wage_rows() as loaded:
                    result = self.summary()
                row = result["internal_plans"][0]
                self.assertEqual(row["scheme_id"], str(latest.pk))
                self.assertEqual(row["wage_status"], expected_status)
                self.assertEqual(row["estimated_amount_status"], "NOT_CONFIGURED")
                self.assertIsNone(result["estimated_wage"])
                self.assertIsNone(row["progress_percent"])
                self.assertCountEqual(loaded["schemes"], [scheme.pk for scheme in schemes])
                self.assertEqual(loaded["line_schemes"], [])
