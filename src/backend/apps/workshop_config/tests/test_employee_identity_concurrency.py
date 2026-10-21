import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.organizations.models import Employee
from apps.workshop_reporting.tests import test_workshop_reporting_api as reporting_fixtures

from ..models import Workshop, WorkshopEmployee
from ..selectors import locked_active_employees
from ..services import create_config


@skipUnless(connection.vendor == "postgresql", "员工行锁验证需要 PostgreSQL")
class WorkshopEmployeeIdentityConcurrencyTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.workshop, _ = Workshop.objects.get_or_create(name="装配车间")
        self.actor = Employee.objects.create(employee_code="IDENTITY-LOCK-ACTOR", display_name="并发管理员")
        self.source = Employee.objects.create(employee_code="IDENTITY-LOCK-SOURCE", display_name="并发员工")

    def create_in_connection(self, *, barrier=None, started=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
            if barrier:
                barrier.wait(timeout=10)
            if started:
                started.set()
            try:
                result = create_config(
                    model_class=WorkshopEmployee, actor_employee=self.actor,
                    validated_data={"workshop": self.workshop, "employee": self.source,
                                    "position": "装配工", "is_supervisor": False},
                )
            except ValidationError:
                return "REJECTED"
            return str(result.pk)
        finally:
            connections.close_all()

    def test_concurrent_identical_assignments_create_only_one_record(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.create_in_connection, barrier=barrier) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(results.count("REJECTED"), 1, results)
        self.assertEqual(WorkshopEmployee.objects.filter(employee=self.source).count(), 1)

    def test_committed_source_deactivation_is_rechecked_after_lock_wait(self):
        started = Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                source = Employee.objects.select_for_update(no_key=True).get(pk=self.source.pk)
                source.status = "LEFT"
                source.save(update_fields=["status", "updated_at"])
                future = executor.submit(self.create_in_connection, started=started)
                self.assertTrue(started.wait(timeout=10))
            self.assertEqual(future.result(timeout=20), "REJECTED")
        self.assertFalse(WorkshopEmployee.objects.exists())

    def test_material_recipient_preview_validation_does_not_require_transaction(self):
        from apps.material_issues.models import MaterialIssue
        from apps.material_issues.services import _validate_relations

        row = WorkshopEmployee.objects.create(
            workshop=self.workshop, employee=self.source, name="历史领料姓名", position="装配工", is_supervisor=False,
        )
        self.assertFalse(connection.in_atomic_block)
        issue = MaterialIssue(workshop=self.workshop, recipient_workshop_employee=row)
        _validate_relations(issue)
        self.assertEqual(issue.recipient_workshop_employee_id, row.pk)

    def test_production_employee_lock_rechecks_source_after_deactivation_wait(self):
        row = WorkshopEmployee.objects.create(
            workshop=self.workshop, employee=self.source, name="生产历史姓名", position="装配工", is_supervisor=False,
        )
        source_lock_requested = Event()

        def select_in_connection():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")

                def observe_source_lock(execute, sql, params, many, context):
                    if 'FROM "employee"' in sql and "FOR NO KEY UPDATE" in sql:
                        source_lock_requested.set()
                    return execute(sql, params, many, context)

                with transaction.atomic(), connection.execute_wrapper(observe_source_lock):
                    return [item.pk for item in locked_active_employees(
                        WorkshopEmployee.objects.filter(pk=row.pk),
                    )]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                source = Employee.objects.select_for_update(no_key=True).get(pk=self.source.pk)
                source.status = "INACTIVE"
                source.save(update_fields=["status", "updated_at"])
                future = executor.submit(select_in_connection)
                self.assertTrue(source_lock_requested.wait(timeout=10))
                self.assertFalse(future.done())
            self.assertEqual(future.result(timeout=20), [])
        row.refresh_from_db()
        self.assertEqual(row.status, "ACTIVE")
        self.assertEqual(row.employee_id, self.source.pk)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class WorkshopEmployeePreviewTransactionTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        # 排产的延迟完整性约束须在产品、工艺全部建好后才检查。
        with transaction.atomic():
            reporting_fixtures.WorkshopReportingApiTests.setUp(self)

    def test_legacy_and_public_previews_can_read_linked_recipient_without_atomic(self):
        from apps.material_issues.models import MaterialIssue
        from apps.material_issues.services import preview_issue

        source = Employee.objects.create(employee_code="IDENTITY-PREVIEW", display_name="预览员工")
        self.worker.employee = source
        self.worker.save(update_fields=["employee", "updated_at"])
        self.assertFalse(connection.in_atomic_block)
        for stock_mode in ("LEGACY", "PUBLIC_V2"):
            with self.subTest(stock_mode=stock_mode):
                issue = MaterialIssue.objects.create(
                    stock_mode=stock_mode, issue_number=f"IDENTITY-PREVIEW-{stock_mode}",
                    client_request_id=uuid.uuid4(), request_payload_hash="a" * 64,
                    production_task=self.task, product_line=self.product_line, workshop=self.workshop,
                    recipient_workshop_employee=self.worker, issue_at=timezone.now(), status="PENDING_REVIEW",
                    created_by_employee=self.employee, updated_by_employee=self.employee,
                )
                result = preview_issue(issue)
                self.assertFalse(result["can_confirm"])
                self.assertEqual(result["lines"], [])
                self.assertFalse(issue.lines.exists())
                self.assertFalse(issue.audit_events.exists())
                issue.refresh_from_db()
                self.assertEqual(issue.status, "PENDING_REVIEW")
