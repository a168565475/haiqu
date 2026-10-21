from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.exceptions import APIException

from apps.access_control.organization_services import create_department, set_role_department
from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee, OrganizationUnit, RoleProfile


@override_settings(ACCESS_MANAGEMENT_ENABLED=True)
class OrganizationConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin", "admin@example.test", "test-secret")
        Employee.objects.create(user=self.user, employee_code="ORG_CONCURRENT_ADMIN", display_name="管理员")
        self.root, _ = OrganizationUnit.objects.get_or_create(unit_code="HAIQU", defaults={"unit_name": "海趣"})
        self.unit = OrganizationUnit.objects.create(unit_code="ORG_CONCURRENT", unit_name="并发部门", parent=self.root)
        self.role = RoleProfile.objects.create(auth_group=Group.objects.create(name="ORG_CONCURRENT"),
            role_code="ORG_CONCURRENT", display_name="并发角色")

    def run_writers(self, operation):
        barrier = Barrier(2)
        user_id = self.user.pk

        def worker():
            close_old_connections()
            try:
                request = SimpleNamespace(user=get_user_model().objects.get(pk=user_id), META={},
                                          headers={"If-Match": etag_for_instance(self.role)})
                barrier.wait(timeout=8)
                try:
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL lock_timeout = '5s'")
                        operation(request)
                    return 200
                except APIException as exc:
                    return exc.status_code
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(worker), pool.submit(worker)
            return sorted([a.result(timeout=20), b.result(timeout=20)])

    def test_simultaneous_department_creation_reuses_no_duplicates(self):
        statuses = self.run_writers(lambda request: create_department(request, {
            "unit_code": "CONCURRENT_NEW", "unit_name": "并发新部门", "parent_id": self.root.pk,
        }))
        self.assertEqual(statuses, [200, 409])
        self.assertEqual(OrganizationUnit.objects.filter(unit_name="并发新部门").count(), 1)

    def test_simultaneous_role_classification_rejects_stale_version(self):
        statuses = self.run_writers(lambda request: set_role_department(request, self.role.pk, self.unit.pk))
        self.assertEqual(statuses, [200, 412])
        self.role.refresh_from_db()
        self.assertEqual(self.role.department_id, self.unit.pk)
