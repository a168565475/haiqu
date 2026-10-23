from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

from django.db import close_old_connections, connections, transaction
from django.test import TransactionTestCase
from rest_framework.exceptions import APIException

from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee
from apps.workshop_config.models import Workshop
from apps.workshop_config.selectors import locked_active_employees
from apps.workshop_config.services import update_employee_workshop
from .factories import production_employee


class WorkshopEmployeeIdentityConcurrencyTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.workshop, _ = Workshop.objects.get_or_create(name="装配车间")
        self.actor = Employee.objects.create(employee_code="MASTER_LOCK_ACTOR", display_name="操作人")
        self.worker = production_employee(workshop=self.workshop, position="原岗位", name="并发员工")

    def test_same_version_concurrent_updates_only_one_succeeds(self):
        barrier = Barrier(2)
        tag = etag_for_instance(self.worker)
        def write(position):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                request = SimpleNamespace(headers={"If-Match": tag}, META={})
                try:
                    update_employee_workshop(instance_id=self.worker.pk, validated_data={"workshop_position": position}, actor_employee=self.actor, request=request)
                    return 200
                except APIException as exc:
                    return exc.status_code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(write, ["岗位甲", "岗位乙"]))
        self.assertEqual(sorted(results), [200, 412])
        self.assertEqual(Employee.objects.filter(pk=self.worker.pk).count(), 1)

    def test_locked_choices_reject_inactive_master(self):
        self.worker.status = "LEFT"
        self.worker.save()
        with transaction.atomic():
            self.assertEqual(locked_active_employees(Employee.objects.filter(pk=self.worker.pk)), [])
