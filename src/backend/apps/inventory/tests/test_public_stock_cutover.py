import io
import threading
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection, connections, transaction
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from ..cutover_middleware import PublicStockCutoverMiddleware
from ..models import PublicStockCutoverControl
from ..public_stock_cutover import (allow_opening_stock_credit, assert_cutover_target,
    begin_cutover_maintenance, current_cutover_target, get_cutover_control,
    require_business_stock_write, require_transition_maintenance)
from ..public_stock_mode import public_flow_enabled, require_document_stock_mode
from ..stock_services import InventoryStockValidationError


class CutoverFixture:
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="cutover-admin", is_superuser=True, is_staff=True)
        self.employee = Employee.objects.create(employee_code="CUTOVER_ADMIN", display_name="切换管理员", user=self.user)
        self.target = current_cutover_target()
        override = self.settings(PUBLIC_STOCK_CUTOVER_ALLOWED_TARGETS=[self.target], PUBLIC_STOCK_FLOW_ENABLED=False)
        override.enable()
        self.addCleanup(override.disable)

    def begin(self, **overrides):
        arguments = dict(actor_employee=self.employee, reason="隔离验收", expected_target=self.target)
        arguments.update(overrides)
        return begin_cutover_maintenance(**arguments)


class PublicStockCutoverTests(CutoverFixture, TestCase):
    def test_default_command_is_read_only(self):
        output = io.StringIO()
        call_command("public_stock_cutover", stdout=output)
        self.assertIn("NOT_STARTED", output.getvalue())
        self.assertFalse(PublicStockCutoverControl.objects.exists())

    def test_target_and_operator_are_required(self):
        with self.settings(PUBLIC_STOCK_CUTOVER_ALLOWED_TARGETS=[]):
            with self.assertRaises(InventoryStockValidationError):
                self.begin()
        with self.assertRaises(InventoryStockValidationError):
            self.begin(expected_target={**self.target, "database": "other"})
        self.user.is_superuser = False
        self.user.save(update_fields=["is_superuser"])
        with self.assertRaises(InventoryStockValidationError):
            self.begin()
        self.assertFalse(PublicStockCutoverControl.objects.exists())

    def test_maintenance_persists_and_start_is_idempotent(self):
        first = self.begin()
        self.assertEqual(self.begin().pk, first.pk)
        self.assertEqual(get_cutover_control().state, "MAINTENANCE")
        self.assertEqual(AuditLog.objects.filter(action="MAINTENANCE_STARTED").count(), 1)
        with self.assertRaises(InventoryStockValidationError):
            require_business_stock_write()
        with self.assertRaises(InventoryStockValidationError):
            require_document_stock_mode(SimpleNamespace(stock_mode="LEGACY"))

    def test_only_opening_credit_can_bypass_maintenance(self):
        self.begin()
        with allow_opening_stock_credit():
            require_business_stock_write(source_type="PUBLIC_STOCK_OPENING", direction="IN")
            with self.assertRaises(InventoryStockValidationError):
                require_business_stock_write(source_type="PUBLIC_STOCK_OPENING", direction="OUT")
            with self.assertRaises(InventoryStockValidationError):
                require_business_stock_write(source_type="MATERIAL_INBOUND", direction="IN")
        with self.assertRaises(InventoryStockValidationError):
            require_business_stock_write(source_type="PUBLIC_STOCK_OPENING", direction="IN")

    def test_public_state_cannot_fall_back_to_legacy_on_env_change(self):
        control = self.begin()
        control.state = "PUBLIC"
        control.save(update_fields=["state"])
        self.assertTrue(public_flow_enabled())
        with self.assertRaises(InventoryStockValidationError):
            require_document_stock_mode(SimpleNamespace(stock_mode="LEGACY"))
        with self.assertRaises(InventoryStockValidationError):
            self.begin()

    def test_middleware_read_allowed_write_blocked_without_entering_view(self):
        self.begin()
        reached = []
        middleware = PublicStockCutoverMiddleware(lambda request: reached.append(request.method) or HttpResponse("ok"))
        factory = RequestFactory()
        callback = SimpleNamespace(view_class=SimpleNamespace(__module__="apps.inventory.api.views"))
        with patch("apps.inventory.cutover_middleware.resolve", return_value=SimpleNamespace(func=callback)):
            self.assertEqual(middleware(factory.get("/api/test/")).status_code, 200)
            result = middleware(factory.post("/api/test/"))
            self.assertEqual(result.status_code, 503)
            self.assertContains(result, "PUBLIC_STOCK_CUTOVER_MAINTENANCE", status_code=503)
        self.assertEqual(reached, ["GET"])

    def test_direct_business_services_stop_before_permissions_and_row_locks(self):
        from apps.material_issues import p4_services, processing_services, original_order_services, services
        from apps.inventory import services as inventory_services
        from apps.outsourcing import services as outsourcing_services
        self.begin()
        operations = [p4_services.confirm_original_good_return, p4_services.create_original_handoff,
            p4_services.create_unsprayed_return, p4_services.create_rework, p4_services.create_external_order,
            p4_services.confirm_external_handoff, p4_services.confirm_external_good_return,
            p4_services.close_external_order, processing_services.record_processing,
            original_order_services.write_original_order_closure, services.confirm_issue,
            inventory_services.confirm_material_quality, outsourcing_services.confirm_dispatch,
            outsourcing_services.confirm_return]
        for operation in operations:
            with self.subTest(operation=operation.__name__), CaptureQueriesContext(connection) as queries:
                with self.assertRaises(InventoryStockValidationError):
                    operation()
                self.assertFalse(any("FOR UPDATE" in query["sql"].upper() for query in queries))


class PublicStockCutoverConcurrencyTests(CutoverFixture, TransactionTestCase):
    serialized_rollback = True

    def test_real_p4_service_holds_shared_lock_before_its_first_business_lock(self):
        import uuid
        from apps.material_issues.p4_services import confirm_original_good_return
        reached, release, completed = threading.Event(), threading.Event(), threading.Event()
        errors = []
        class StopTestService(Exception):
            pass
        def pause_at_request_lock(*args):
            Employee.objects.select_for_update().get(pk=self.employee.pk)
            reached.set()
            if not release.wait(10):
                raise RuntimeError("实际服务等待释放超时")
            raise StopTestService()
        def direct_service():
            try:
                with patch("apps.material_issues.p4_services.lock_request", side_effect=pause_at_request_lock):
                    confirm_original_good_return(request=SimpleNamespace(user=self.user), handoff_id=uuid.uuid4(),
                        request_id=uuid.uuid4(), good_pieces=1, zone_id=uuid.uuid4(),
                        received_by_employee_id=self.employee.pk, return_date="2026-09-28", remark="并发测试")
            except StopTestService:
                pass
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()
        def maintenance():
            try:
                self.begin()
                completed.set()
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()
        first, second = threading.Thread(target=direct_service), threading.Thread(target=maintenance)
        first.start()
        try:
            self.assertTrue(reached.wait(5))
            second.start()
            self.assertFalse(completed.wait(0.2))
        finally:
            release.set()
            first.join(10)
            if second.ident:
                second.join(10)
        self.assertFalse(errors, errors)
        self.assertTrue(completed.is_set())

    def test_maintenance_waits_for_active_writer_then_blocks_following_writer(self):
        writer_ready, release_writer, maintenance_done = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def writer():
            try:
                with transaction.atomic():
                    require_business_stock_write()
                    writer_ready.set()
                    if not release_writer.wait(10):
                        raise RuntimeError("等待释放写事务超时")
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()
        def maintenance():
            try:
                self.begin()
                maintenance_done.set()
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()
        first = threading.Thread(target=writer)
        second = threading.Thread(target=maintenance)
        first.start()
        try:
            self.assertTrue(writer_ready.wait(5))
            second.start()
            self.assertFalse(maintenance_done.wait(0.2))
        finally:
            release_writer.set()
            first.join(10)
            if second.ident:
                second.join(10)
        self.assertFalse(errors, errors)
        self.assertTrue(maintenance_done.is_set())
        with self.assertRaises(InventoryStockValidationError):
            require_business_stock_write()
