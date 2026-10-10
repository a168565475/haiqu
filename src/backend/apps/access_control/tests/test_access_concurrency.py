from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings

from apps.access_control import services
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, RoleProfile


@override_settings(ACCESS_MANAGEMENT_ENABLED=True)
class AccessConcurrencyTests(TransactionTestCase):
    def test_admin_employee_assignment_does_not_deadlock_with_role_grant_audit(self):
        user = get_user_model().objects.create_superuser("admin", "admin@example.test", "test-secret")
        employee = Employee.objects.create(user=user, employee_code="CONCURRENT_ADMIN", display_name="管理员")
        role = RoleProfile.objects.create(auth_group=Group.objects.create(name="Concurrent"), role_code="CONCURRENT", display_name="并发角色")
        role_locked, employee_locked = Event(), Event()
        original_etag_check = services.require_matching_etag

        def checked_etag(request, instance):
            original_etag_check(request, instance)
            if isinstance(instance, Employee):
                employee_locked.set()

        def request(etag):
            return SimpleNamespace(user=get_user_model().objects.get(pk=user.pk), headers={"If-Match": etag}, META={})

        def grants_writer():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as c:
                        c.execute("SET LOCAL lock_timeout = '4s'")
                    RoleProfile.objects.select_for_update().get(pk=role.pk)
                    role_locked.set()
                    if not employee_locked.wait(5): raise AssertionError("employee transaction did not start")
                    services.replace_grants(request(etag_for_instance(role)), role.pk, [
                        {"permission": "sales_orders.view_salesorder", "scope": "OWN"},
                    ])
                return "grants committed"
            finally: close_old_connections()

        def assignment_writer():
            close_old_connections()
            try:
                if not role_locked.wait(5): raise AssertionError("role transaction did not start")
                with transaction.atomic():
                    with connection.cursor() as c:
                        c.execute("SET LOCAL lock_timeout = '4s'")
                    services.replace_employee_roles(request(etag_for_instance(employee)), employee.pk, [role.pk])
                return "assignment committed"
            finally: close_old_connections()

        with patch.object(services, "require_matching_etag", checked_etag), ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(grants_writer), pool.submit(assignment_writer)
            self.assertEqual(first.result(timeout=15), "grants committed")
            self.assertEqual(second.result(timeout=15), "assignment committed")
        self.assertEqual(role.action_grants.count(), 1)
        self.assertEqual(employee.role_assignments.count(), 1)
