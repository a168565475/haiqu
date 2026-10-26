"""列表内复用权限计算；身份、接收角色及对象检查仍逐条执行。"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.access_control import sales_policy
from apps.access_control.models import RoleActionGrant
from apps.organizations.models import EmployeeRoleAssignment
from apps.organizations.models import Employee
from apps.wecom import notification_access, notification_selectors, notification_views
from .test_notifications import NotificationFixture, SETTINGS, INBOX_URL, employee


@override_settings(MODULE_ACCESS_ENABLED=True)
class NotificationQueryReuseTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.permission = "production_tasks.view_productiontask"
        self.user = SimpleNamespace(pk=1, is_authenticated=True, is_active=True, is_superuser=False,
                                    has_perm=Mock(return_value=True))
        self.employee = SimpleNamespace(pk=uuid4(), user=self.user)
        self.snapshot = {"active": True, "is_superuser": False,
                         "actions": {self.permission: {"scopes": ["ALL"]}}, "legacy_sources": []}
        self.users = {self.user.pk: self.user}
        self.employees = {self.user.pk: self.employee}
        self.snapshots = {self.user.pk: self.snapshot}
        self.user_lookup = self.patch(get_user_model().objects, "filter", side_effect=self.find_user)
        self.employee_lookup = self.patch(Employee.objects, "filter", side_effect=lambda **kwargs:
            SimpleNamespace(first=lambda: self.employees.get(kwargs["user"].pk)))
        self.roles = Mock()
        self.roles.filter.return_value.exists.return_value = True
        self.patch("apps.access_control.selectors.current_assignments", return_value=self.roles)
        self.objects = Mock()
        self.objects.filter.return_value.exists.return_value = True
        self.object_scope = self.patch(notification_access, "_object_queryset", return_value=self.objects)
        self.effective_access = self.patch("apps.access_control.sales_policy.effective_access",
                                          side_effect=lambda user: deepcopy(self.snapshots[user.pk]))
        self.patch(notification_views, "active_employee_for", return_value=self.employee)

    def patch(self, target, name=None, **kwargs):
        patcher = patch(target, **kwargs) if name is None else patch.object(target, name, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def find_user(self, **kwargs):
        user = self.users.get(kwargs["pk"])
        return SimpleNamespace(first=lambda: user if user and user.is_active else None)

    def recipient(self, code="PRODUCTION_TASK_CONFIRMED"):
        event = SimpleNamespace(event_code=code, object_id=str(uuid4()), object_version="1",
                                status="READY", context={}, rendered_title="测试标题",
                                rendered_body="测试正文", target={"id": str(uuid4())})
        return SimpleNamespace(pk=uuid4(), event=event, role_codes=["READER"], scope="ROLE",
                               created_at=timezone.now(), read_at=None,
                               deliveries=SimpleNamespace(all=lambda: []))

    def inbox(self, recipients):
        class InboxRows(list):
            def count(self):
                return len(self)

        rows = InboxRows(recipients)
        with patch.object(notification_selectors, "inbox_queryset", return_value=rows):
            return notification_views.NotificationInboxView().get(
                SimpleNamespace(user=self.user, query_params={"page_size": 10})).data

    def test_list_reuses_permission_calculation_but_checks_each_object(self):
        rows = [self.recipient(), self.recipient()]
        result = self.inbox(rows)
        self.assertEqual(result["count"], 2)
        self.assertEqual([item["body"] for item in result["data"]], ["测试正文", "测试正文"])
        self.assertTrue(all(item["target_accessible"] for item in result["data"]))
        self.assertEqual(self.effective_access.call_count, 1)
        self.assertEqual(self.user_lookup.call_count, 2)
        self.assertEqual(self.employee_lookup.call_count, 2)
        self.assertEqual(self.roles.filter.return_value.exists.call_count, 2)
        self.assertEqual(self.objects.filter.return_value.exists.call_count, 2)

    def check(self, snapshots=None, *, user=None, code="PRODUCTION_TASK_CONFIRMED"):
        return notification_access.event_object_accessible(
            code, uuid4(), user or self.user, role_codes=["READER"], object_version="1",
            permission_snapshots=snapshots)

    def test_next_list_request_rechecks_revoked_grants(self):
        rows = [self.recipient(), self.recipient()]
        self.assertTrue(all(item["target_accessible"] for item in self.inbox(rows)["data"]))
        self.snapshot["actions"].clear()
        denied = self.inbox(rows)["data"]
        self.assertFalse(any(item["target_accessible"] for item in denied))
        self.assertTrue(all(item["target"] is None and item["body"] != "测试正文" for item in denied))
        self.assertEqual(self.effective_access.call_count, 2)

    def test_different_users_do_not_share_snapshot(self):
        other = SimpleNamespace(pk=2, is_authenticated=True, is_active=True, is_superuser=False)
        self.users[other.pk] = other
        self.employees[other.pk] = SimpleNamespace(pk=uuid4(), user=other)
        self.snapshots[other.pk] = {**self.snapshot, "actions": {}}
        snapshots = {}
        self.assertTrue(self.check(snapshots))
        self.assertFalse(self.check(snapshots, user=other))
        self.assertEqual(self.effective_access.call_count, 2)

    def test_cached_permissions_still_reject_disabled_user(self):
        snapshots = {}
        self.assertTrue(self.check(snapshots))
        self.user.is_active = False
        self.assertFalse(self.check(snapshots))
        self.assertEqual(self.user_lookup.call_count, 2)
        self.assertEqual(self.effective_access.call_count, 1)

    def test_cached_permissions_still_reject_inactive_employee(self):
        snapshots = {}
        self.assertTrue(self.check(snapshots))
        self.employees.clear()
        self.assertFalse(self.check(snapshots))
        self.assertEqual(self.employee_lookup.call_count, 2)
        self.assertEqual(self.effective_access.call_count, 1)

    def test_cached_permissions_still_reject_removed_recipient_role(self):
        snapshots = {}
        self.assertTrue(self.check(snapshots))
        self.roles.filter.return_value.exists.return_value = False
        self.assertFalse(self.check(snapshots))
        self.assertEqual(self.roles.filter.return_value.exists.call_count, 2)
        self.assertEqual(self.effective_access.call_count, 1)

    def test_cached_permissions_still_recheck_object_scope(self):
        snapshots = {}
        self.assertTrue(self.check(snapshots))
        self.objects.filter.return_value.exists.return_value = False
        self.assertFalse(self.check(snapshots))
        self.assertEqual(self.objects.filter.return_value.exists.call_count, 2)
        self.assertEqual(self.effective_access.call_count, 1)

    def test_cached_permissions_still_recheck_object_version(self):
        self.snapshot["actions"] = {"workshop_reporting.view_workreport": {"scopes": ["ALL"]}}
        snapshots = {}
        with patch("apps.wecom.workshop_notifications.current_workshop_object",
                   side_effect=[SimpleNamespace(pk=uuid4()), None]) as current_object:
            self.assertTrue(self.check(snapshots, code="WORK_REPORT_SAVED"))
            self.assertFalse(self.check(snapshots, code="WORK_REPORT_SAVED"))
        self.assertEqual(current_object.call_count, 2)
        self.assertEqual(self.effective_access.call_count, 1)

    def test_alternative_permissions_reuse_snapshot_without_reusing_action_scope(self):
        self.snapshot["actions"] = {"samples.add_sampleinventoryreceipt": {"scopes": ["ALL"]}}
        with patch("apps.samples.notification_events.current_sample_object", return_value=SimpleNamespace()):
            self.assertTrue(self.check({}, code="SAMPLE_COMPLETED"))
        self.assertEqual(self.effective_access.call_count, 1)
        self.assertEqual(self.object_scope.call_args.args[2], "samples.add_sampleinventoryreceipt")

    @override_settings(MODULE_ACCESS_ENABLED=False)
    def test_disabled_module_access_does_not_add_snapshot_computation(self):
        snapshots = {}
        self.assertTrue(self.check(snapshots))
        self.assertTrue(self.check(snapshots))
        self.assertEqual(snapshots, {})
        self.effective_access.assert_not_called()
        self.assertEqual(self.user.has_perm.call_count, 2)

    def test_callers_without_batch_context_recheck_permissions(self):
        self.assertTrue(self.check())
        self.snapshot["actions"].clear()
        self.assertFalse(self.check())
        self.assertEqual(self.effective_access.call_count, 2)


@override_settings(**SETTINGS)
class NotificationQueryReuseApiTests(NotificationFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.register()
        self.register(idempotency_key="notify:receipt:second-event:v1")
        self.client = APIClient()
        self.client.force_login(self.member.user)

    def test_real_inbox_reuses_one_snapshot_and_keeps_personal_content(self):
        with patch.object(sales_policy, "effective_access", wraps=sales_policy.effective_access) as access:
            response = self.client.get(INBOX_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertTrue(all(item["target_accessible"] for item in response.data["data"]))
        self.assertTrue(all(self.context["document_no"] in item["body"] for item in response.data["data"]))
        self.assertEqual(access.call_count, 1)
        outsider = employee("NOTIFY_QUERY_OUTSIDER")
        self.client.force_login(outsider.user)
        self.assertEqual(self.client.get(INBOX_URL).data["count"], 0)

    def test_real_next_request_masks_revoked_action_grants(self):
        self.assertTrue(all(item["target_accessible"] for item in self.client.get(INBOX_URL).data["data"]))
        RoleActionGrant.objects.filter(role=self.role).delete()
        response = self.client.get(INBOX_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertFalse(any(item["target_accessible"] for item in response.data["data"]))
        self.assertTrue(all(self.context["document_no"] not in item["body"] for item in response.data["data"]))

    def test_real_next_request_masks_removed_recipient_role(self):
        self.assertTrue(all(item["target_accessible"] for item in self.client.get(INBOX_URL).data["data"]))
        EmployeeRoleAssignment.objects.filter(employee=self.member, role_profile=self.role).delete()
        response = self.client.get(INBOX_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertFalse(any(item["target_accessible"] for item in response.data["data"]))
        self.assertTrue(all(item["target"] is None for item in response.data["data"]))
