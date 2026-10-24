"""真实隔离数据库/API：超级管理员可自审，通知仍按配置角色与当前身份解析。"""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.organizations.models import Employee, EmployeeRoleAssignment
from apps.wecom.models import NotificationEvent
from apps.wecom.notification_access import event_object_accessible
from apps.wecom.notification_selectors import recipient_payload

from .test_notifications import SETTINGS, create_rule, employee, grant_role


class SelfApprovalNotificationChecks:
    def configure_recipient(self, *, superuser):
        self.f.user.is_superuser = superuser
        self.f.user.save(update_fields=["is_superuser"])
        self.f.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label__in=["material_issues", "workshop_reporting", "production_scheduling", "production_tasks"],
        ))
        self.role = grant_role(self.f.employee, self.role_code, self.permission)
        create_rule(self.event_code, self.f.employee, [self.role.role_code])
        # 使用重新读取的身份，避免沿用夹具中超级管理员的权限缓存。
        self.f.user = get_user_model().objects.get(pk=self.f.user.pk)
        self.f.client.force_authenticate(self.f.user)

    def event(self):
        return NotificationEvent.objects.get(event_code=self.event_code)

    def assert_self_recipient(self):
        event = self.event()
        self.assertEqual(list(event.recipients.values_list("employee_id", flat=True)), [self.f.employee.pk])
        self.assertEqual(event.recipients.get().deliveries.count(), 2)
        self.assertTrue(recipient_payload(event.recipients.get(), self.f.user)["target_accessible"])
        return event

    def assert_current_access_guards(self, event):
        def accessible(**changes):
            arguments = dict(role_codes=[self.role.role_code], object_version=event.object_version)
            arguments.update(changes)
            return event_object_accessible(event.event_code, event.object_id, self.f.user, **arguments)

        self.assertTrue(accessible())
        self.assertFalse(accessible(role_codes=[]))
        self.assertFalse(accessible(object_version="obsolete"))
        self.assertFalse(event_object_accessible(event.event_code, uuid4(), self.f.user))
        get_user_model().objects.filter(pk=self.f.user.pk).update(is_active=False)
        self.assertFalse(accessible())
        get_user_model().objects.filter(pk=self.f.user.pk).update(is_active=True)
        Employee.objects.filter(pk=self.f.employee.pk).update(status="INACTIVE")
        self.assertFalse(accessible())
        Employee.objects.filter(pk=self.f.employee.pk).update(status="ACTIVE", archived_at=timezone.now())
        self.assertFalse(accessible())
        Employee.objects.filter(pk=self.f.employee.pk).update(archived_at=None)
        assignments = EmployeeRoleAssignment.objects.filter(employee=self.f.employee, role_profile=self.role)
        assignments.update(effective_to=timezone.now())
        self.assertFalse(accessible())
        assignments.update(effective_to=None)
        self.assertTrue(accessible())
        # 会话里仍是超级管理员，数据库降权必须立即恢复禁止自审的通知限制。
        get_user_model().objects.filter(pk=self.f.user.pk).update(is_superuser=False)
        self.assertFalse(accessible())

    def create_unselected_superuser(self):
        other = employee(self.role_code + "_OTHER")
        other.user.is_superuser = True
        other.user.save(update_fields=["is_superuser"])
        grant_role(other, self.role_code + "_UNSELECTED", self.permission)

    def create_other_reviewer(self):
        other = employee(self.role_code + "_REVIEWER")
        EmployeeRoleAssignment.objects.create(
            employee=other, role_profile=self.role, effective_from=timezone.now(),
        )
        return other


@override_settings(**SETTINGS, PUBLIC_STOCK_FLOW_ENABLED=False, PUBLIC_STOCK_ISSUES_ENABLED=False)
class MaterialSelfApprovalNotificationTests(SelfApprovalNotificationChecks, APITestCase):
    event_code = "MATERIAL_ISSUE_SUBMITTED"
    role_code = "U24_ISSUE_SELF_REVIEW"
    permission = "material_issues.review_materialissue"

    def setUp(self):
        from apps.material_issues.tests.test_material_issue_api import MaterialIssueApiTests
        self.f = MaterialIssueApiTests()
        self.f.setUp()

    def submit(self):
        created = self.f._create_issue("10")
        response = self.f.client.post(
            f"/api/v1/material-issues/{created.data['data']['id']}/submit/", {},
            format="json", HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def review(self, submitted):
        return self.f.client.post(
            f"/api/v1/material-issues/{submitted.data['data']['id']}/confirm-issue/",
            {"request_id": str(uuid4())}, format="json", HTTP_IF_MATCH=submitted["ETag"],
        )

    def test_selected_superuser_receives_notice_and_confirms_own_issue(self):
        self.configure_recipient(superuser=True)
        self.create_unselected_superuser()
        submitted = self.submit()
        event = self.assert_self_recipient()
        response = self.review(submitted)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["status"], "ISSUED")
        from apps.inventory.models import MaterialStockBalance
        self.assertEqual(MaterialStockBalance.objects.get(raw_material=self.f.raw_material).quantity, 590)
        self.assertFalse(recipient_payload(event.recipients.get(), self.f.user)["target_accessible"])

    def test_ordinary_submitter_is_excluded_and_self_review_stays_forbidden(self):
        self.configure_recipient(superuser=False)
        reviewer = self.create_other_reviewer()
        submitted = self.submit()
        self.assertEqual(list(self.event().recipients.values_list("employee_id", flat=True)), [reviewer.pk])
        response = self.review(submitted)
        self.assertEqual(response.status_code, 403, response.data)
        self.assertIn("提交人不能审批", str(response.data))

    def test_superuser_notification_rechecks_role_account_employee_and_object(self):
        self.configure_recipient(superuser=True)
        self.submit()
        self.assert_current_access_guards(self.assert_self_recipient())


@override_settings(**SETTINGS)
class WageSelfApprovalNotificationTests(SelfApprovalNotificationChecks, APITestCase):
    event_code = "WAGE_SCHEME_SUBMITTED"
    role_code = "U24_WAGE_SELF_REVIEW"
    permission = "workshop_reporting.approve_wagescheme"

    def setUp(self):
        from apps.workshop_reporting.tests.test_workshop_reporting_api import WorkshopReportingApiTests
        self.f = WorkshopReportingApiTests()
        self.f.setUp()

    def submit(self):
        created = self.f.client.post(
            "/api/v1/workshop-reporting/wage-schemes/", self.f.scheme_payload(), format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        response = self.f.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{created.data['data']['id']}/submit/",
            {}, format="json", HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def review(self, submitted):
        return self.f.client.post(
            f"/api/v1/workshop-reporting/wage-schemes/{submitted.data['data']['id']}/approve/",
            {}, format="json", HTTP_IF_MATCH=submitted["ETag"],
        )

    def test_selected_superuser_receives_notice_and_approves_own_scheme(self):
        self.configure_recipient(superuser=True)
        self.create_unselected_superuser()
        submitted = self.submit()
        event = self.assert_self_recipient()
        response = self.review(submitted)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["status"], "APPROVED")
        self.assertFalse(recipient_payload(event.recipients.get(), self.f.user)["target_accessible"])

    def test_ordinary_submitter_is_excluded_and_self_review_stays_forbidden(self):
        self.configure_recipient(superuser=False)
        reviewer = self.create_other_reviewer()
        submitted = self.submit()
        self.assertEqual(list(self.event().recipients.values_list("employee_id", flat=True)), [reviewer.pk])
        response = self.review(submitted)
        self.assertEqual(response.status_code, 403, response.data)
        self.assertIn("提交人不能审批", str(response.data))

    def test_superuser_notification_rechecks_role_account_employee_and_object(self):
        self.configure_recipient(superuser=True)
        self.submit()
        self.assert_current_access_guards(self.assert_self_recipient())
