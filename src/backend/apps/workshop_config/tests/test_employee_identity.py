"""车间字段直接归属行政员工后的身份、权限与事务边界。"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase, APIClient

from apps.core.api.concurrency import etag_for_instance
from apps.organizations.models import Employee
from . import test_master_employee as fixtures
from .factories import production_employee


@override_settings(DEV_AUTO_LOGIN_ENABLED=False, ACCESS_MANAGEMENT_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class WorkshopEmployeeIdentityTests(APITestCase):
    setUp = fixtures.MasterWorkshopEmployeeTests.setUp
    configure = fixtures.MasterWorkshopEmployeeTests.configure

    def test_same_name_employees_remain_distinct_master_ids(self):
        other = production_employee(workshop=self.workshop, position="操作工", name=self.worker.display_name)
        rows = self.client.get("/api/v1/workshop-config/employees/").data["data"]
        self.assertEqual({row["id"] for row in rows}, {str(other.pk), str(self.worker.pk)})

    def test_second_arrangement_overwrites_same_employee_without_creating_rows(self):
        count = Employee.objects.count()
        self.assertEqual(self.configure().status_code, 200)
        self.worker.refresh_from_db()
        response = self.client.patch(self.url, {"position": "组长", "is_supervisor": True}, format="json", HTTP_IF_MATCH=etag_for_instance(self.worker))
        self.assertEqual(response.status_code, 200, response.data)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.workshop_position, "组长")
        self.assertTrue(self.worker.workshop_is_supervisor)
        self.assertEqual(Employee.objects.count(), count)

    def test_account_status_does_not_replace_employee_status(self):
        self.worker.user = get_user_model().objects.create_user("disabled-worker", is_active=False)
        self.worker.save()
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.worker.status = "LEFT"
        self.worker.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_current_name_is_read_from_master_without_truncation(self):
        self.worker.display_name = "名" * 150
        self.worker.save()
        response = self.configure()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["name"], self.worker.display_name)

    def test_session_csrf_and_version_are_required(self):
        self.assertEqual(self.client.patch(self.url, {"workshop": str(self.workshop.pk), "position": "新岗位"}, format="json").status_code, 428)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.actor.user)
        self.assertEqual(csrf.patch(self.url, {"position": "新岗位"}, format="json", HTTP_IF_MATCH=etag_for_instance(self.worker)).status_code, 403)
        self.client.logout()
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_audit_failure_rolls_back_all_workshop_fields(self):
        with patch("apps.workshop_config.services.write_audit_log", side_effect=RuntimeError("audit failed")):
            with self.assertRaisesMessage(RuntimeError, "audit failed"):
                self.configure()
        self.worker.refresh_from_db()
        self.assertIsNone(self.worker.workshop_id)
        self.assertEqual(self.worker.workshop_position, "")

    def test_source_change_invalidates_shared_employee_version(self):
        old = etag_for_instance(self.worker)
        self.worker.display_name = "已改名"
        self.worker.save()
        response = self.client.patch(self.url, {"workshop": str(self.workshop.pk), "position": "操作工"}, format="json", HTTP_IF_MATCH=old)
        self.assertEqual(response.status_code, 412, response.data)
