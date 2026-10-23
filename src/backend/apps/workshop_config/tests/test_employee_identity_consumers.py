from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.material_issues.models import MaterialIssue
from apps.material_issues.services import _validate_relations
from apps.organizations.models import Employee
from . import test_master_employee as fixtures


@override_settings(DEV_AUTO_LOGIN_ENABLED=False, ACCESS_MANAGEMENT_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class WorkshopEmployeeConsumerTests(APITestCase):
    setUp = fixtures.MasterWorkshopEmployeeTests.setUp
    configure = fixtures.MasterWorkshopEmployeeTests.configure

    def test_reporting_and_material_choices_use_master_ids_and_current_state(self):
        self.assertEqual(self.configure().status_code, 200)
        for status, archived, allowed in (("ACTIVE", None, True), ("LEFT", None, False), ("INACTIVE", None, False), ("ACTIVE", timezone.now(), False)):
            Employee.objects.filter(pk=self.worker.pk).update(status=status, archived_at=archived)
            for url, params, field in (("/api/v1/workshop-reporting/context/", {"purpose": "work_report"}, "employees"), ("/api/v1/material-issues/options/", {}, "recipients")):
                response = self.client.get(url, params)
                self.assertEqual(response.status_code, 200, response.data)
                ids = {str(row["id"]) for row in response.data["data"][field]}
                self.assertEqual(str(self.worker.pk) in ids, allowed)
                self.assertNotIn(str(self.actor.pk), ids)

    def test_department_removal_is_rechecked_for_material_recipient(self):
        self.assertEqual(self.configure().status_code, 200)
        self.worker.refresh_from_db()
        issue = MaterialIssue(workshop=self.workshop, recipient_workshop_employee=self.worker)
        self.assignment.effective_to = timezone.now()
        self.assignment.save()
        with self.assertRaises(ValidationError):
            _validate_relations(issue, lock_employee=True)

    def test_wrong_workshop_is_rejected(self):
        self.assertEqual(self.configure().status_code, 200)
        from apps.workshop_config.models import Workshop
        issue = MaterialIssue(workshop=Workshop.objects.get(name="装配车间"), recipient_workshop_employee=self.worker)
        with self.assertRaises(ValidationError):
            _validate_relations(issue, lock_employee=True)
