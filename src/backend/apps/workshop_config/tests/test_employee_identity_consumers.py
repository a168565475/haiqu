import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.material_issues.models import MaterialIssue
from apps.material_issues.services import _validate_relations
from apps.organizations.models import Employee
from apps.workshop_reporting.models import WorkReport, WorkReportLine, WorkshopReportingScope
from apps.workshop_reporting.tests import test_workshop_reporting_api as reporting_fixtures

from ..models import Workshop, WorkshopEmployee


@override_settings(DEV_AUTO_LOGIN_ENABLED=False, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class WorkshopEmployeeConsumerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="identity-consumer", password="test")
        self.actor = Employee.objects.create(user=self.user, employee_code="IDENTITY-CONSUMER", display_name="联动管理员")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.workshop = Workshop.objects.get(name="金工车间")
        self.source = Employee.objects.create(employee_code="IDENTITY-RECIPIENT", display_name="统一领料员工")
        self.linked = WorkshopEmployee.objects.create(
            workshop=self.workshop, employee=self.source, name="领料历史姓名", position="操作工", is_supervisor=False,
        )
        self.legacy = WorkshopEmployee.objects.create(
            workshop=self.workshop, name="未关联历史员工", position="操作工", is_supervisor=False,
        )

    def test_reporting_and_material_options_filter_source_status_and_keep_legacy(self):
        local_left = WorkshopEmployee.objects.create(
            workshop=self.workshop, name="岗位已离职", position="操作工", is_supervisor=False, status="LEFT",
        )
        for status, archived, allowed in (
            ("ACTIVE", None, True), ("LEFT", None, False), ("INACTIVE", None, False),
            ("ACTIVE", timezone.now(), False),
        ):
            Employee.objects.filter(pk=self.source.pk).update(status=status, archived_at=archived)
            for url, params, field in (
                ("/api/v1/workshop-reporting/context/", {"purpose": "work_report"}, "employees"),
                ("/api/v1/material-issues/options/", {}, "recipients"),
            ):
                with self.subTest(status=status, archived=bool(archived), url=url):
                    response = self.client.get(url, params)
                    self.assertEqual(response.status_code, 200, response.data)
                    ids = {row["id"] for row in response.data["data"][field]}
                    self.assertEqual(str(self.linked.pk) in ids, allowed)
                    self.assertIn(str(self.legacy.pk), ids)
                    self.assertNotIn(str(local_left.pk), ids)

    def test_material_relation_validation_rejects_stale_invalid_identity(self):
        issue = MaterialIssue(workshop=self.workshop, recipient_workshop_employee=self.linked)
        for status, archived in (("LEFT", None), ("INACTIVE", None), ("ACTIVE", timezone.now())):
            with self.subTest(status=status, archived=bool(archived)):
                Employee.objects.filter(pk=self.source.pk).update(status=status, archived_at=archived)
                with self.assertRaises(ValidationError) as caught:
                    _validate_relations(issue, lock_employee=True)
                self.assertIn("recipient_workshop_employee_id", caught.exception.detail)
        self.assertFalse(MaterialIssue.objects.exists())

    def test_material_relation_validation_accepts_unlinked_legacy_identity(self):
        issue = MaterialIssue(workshop=self.workshop, recipient_workshop_employee=self.legacy)
        _validate_relations(issue, lock_employee=True)
        self.assertEqual(issue.recipient_workshop_employee_id, self.legacy.pk)

    def test_material_detail_keeps_historical_recipient_after_source_deactivation(self):
        issue = MaterialIssue.objects.create(
            issue_number="IDENTITY-ISSUE-001", client_request_id=uuid.uuid4(), request_payload_hash="a" * 64,
            workshop=self.workshop, recipient_workshop_employee=self.linked,
            created_by_employee=self.actor, updated_by_employee=self.actor,
        )
        Employee.objects.filter(pk=self.source.pk).update(status="LEFT", display_name="更新后的姓名", archived_at=timezone.now())
        response = self.client.get(f"/api/v1/material-issues/{issue.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["recipient"], {"id": str(self.linked.pk), "name": "领料历史姓名"})
        issue.refresh_from_db()
        self.assertEqual(issue.recipient_workshop_employee_id, self.linked.pk)


@override_settings(DEV_AUTO_LOGIN_ENABLED=False, MODULE_ACCESS_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class WorkshopEmployeeReportingIdentityTests(TestCase):
    # 只复用原报工用例的数据准备，不继承测试类，避免重复执行整套历史用例。
    setUp = reporting_fixtures.WorkshopReportingApiTests.setUp
    scheme_payload = reporting_fixtures.WorkshopReportingApiTests.scheme_payload

    def create_approved_scheme(self):
        approver_user = get_user_model().objects.create_user(username="identity-wage-approver", password="test")
        approver = Employee.objects.create(
            user=approver_user, employee_code="IDENTITY-WAGE-APPROVER", display_name="独立工价审批员",
        )
        approver_user.user_permissions.set(Permission.objects.filter(
            content_type__app_label="workshop_reporting",
            codename__in=["view_wagescheme", "approve_wagescheme"],
        ))
        WorkshopReportingScope.objects.create(
            employee=approver, workshop=self.workshop, created_by_employee=self.employee,
        )
        reviewer = APIClient()
        reviewer.force_authenticate(approver_user)
        created = self.client.post("/api/v1/workshop-reporting/wage-schemes/", self.scheme_payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        url = f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/"
        submitted = self.client.post(f"{url}submit/", {}, format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        approved = reviewer.post(
            f"{url}approve/", {"effective_from": timezone.localdate().isoformat()},
            format="json", HTTP_IF_MATCH=submitted["ETag"],
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["data"]["approved_by"], approver.display_name)
        return approved

    def report_payload(self, approved):
        return {
            "client_request_id": str(uuid.uuid4()), "production_date": timezone.localdate().isoformat(),
            "schedule_product_id": str(self.schedule_product.pk), "scheme_id": approved.data["data"]["id"],
            "scheme_revision": approved.data["data"]["revision"],
            "lines": [{"scheme_line_id": approved.data["data"]["lines"][0]["id"],
                       "workshop_employee_id": str(self.worker.pk), "quantity": "1.0000"}],
        }

    def link_worker(self):
        source = Employee.objects.create(employee_code="IDENTITY-REPORT-WORKER", display_name="主档报工员工")
        self.worker.employee = source
        self.worker.save(update_fields=["employee", "updated_at"])
        return source

    def test_report_api_rejects_left_inactive_or_archived_source(self):
        source = self.link_worker()
        approved = self.create_approved_scheme()
        for status, archived in (("LEFT", None), ("INACTIVE", None), ("ACTIVE", timezone.now())):
            with self.subTest(status=status, archived=bool(archived)):
                Employee.objects.filter(pk=source.pk).update(status=status, archived_at=archived)
                response = self.client.post("/api/v1/workshop-reporting/work-reports/", self.report_payload(approved), format="json")
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("lines", response.data["error"]["field_errors"])
        self.assertFalse(WorkReport.objects.exists())
        self.assertFalse(WorkReportLine.objects.exists())

    def test_report_api_keeps_unlinked_legacy_worker_usable(self):
        approved = self.create_approved_scheme()
        response = self.client.post("/api/v1/workshop-reporting/work-reports/", self.report_payload(approved), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        line = WorkReportLine.objects.get()
        self.assertEqual(line.workshop_employee_id, self.worker.pk)
        self.assertEqual(line.employee_name_snapshot, self.worker.name)

    def test_report_detail_preserves_identity_and_name_snapshot_after_source_changes(self):
        source = self.link_worker()
        approved = self.create_approved_scheme()
        created = self.client.post("/api/v1/workshop-reporting/work-reports/", self.report_payload(approved), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        Employee.objects.filter(pk=source.pk).update(display_name="主档新姓名", status="LEFT", archived_at=timezone.now())
        response = self.client.get(f"/api/v1/workshop-reporting/work-reports/{created.data['data']['id']}/")
        self.assertEqual(response.status_code, 200, response.data)
        line = response.data["data"]["lines"][0]
        self.assertEqual(line["workshop_employee_id"], str(self.worker.pk))
        self.assertEqual(line["employee_name"], "计件员工甲")
        self.assertEqual(WorkReportLine.objects.get().workshop_employee_id, self.worker.pk)
