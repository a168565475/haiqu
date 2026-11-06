"""规则存储/API 隔离测试，不替代现用系统的启用与提醒验收。"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError, transaction
from django.middleware.csrf import _get_new_csrf_string
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.material_catalog.definitions import CATEGORY_CHOICES
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.procurement.tracking_models import PurchaseTrackingPolicy
from apps.procurement.tracking_policy import get_tracking_policy


class TrackingPolicyDisabledTests(SimpleTestCase):
    @override_settings(PURCHASE_TRACKING_POLICY_ENABLED=False)
    def test_disabled_rules_do_not_query_database(self):
        self.assertIsNone(get_tracking_policy())


@override_settings(
    PURCHASE_TRACKING_POLICY_ENABLED=True, PURCHASE_TRACKING_ENABLED=False,
    ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=False, CONFIRMED_ROLE_POLICY_ENABLED=False,
)
class TrackingPolicyApiTests(APITestCase):
    url = "/api/v1/purchase-tracking-policy/"

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="tracking-policy-admin", password="test-only")
        self.employee = Employee.objects.create(user=self.user, employee_code="TRACK-POLICY", display_name="提醒规则测试")
        self.client.force_login(self.user)

    def state(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def save(self, data, etag=None):
        return self.client.patch(self.url, data, format="json", HTTP_IF_MATCH=etag or self.state()["ETag"])

    def audit(self):
        return AuditLog.objects.filter(object_type="PURCHASE_TRACKING_POLICY")

    def normal_employee(self, *, viewer=True, manager=False):
        user = get_user_model().objects.create_user(username="tracking-policy-user")
        employee = Employee.objects.create(user=user, employee_code="TRACK-USER", display_name="规则普通员工")
        if viewer:
            user.user_permissions.add(Permission.objects.get(content_type__app_label="procurement", codename="view_purchaseorder"))
        if manager:
            role = RoleProfile.objects.create(auth_group=Group.objects.create(name="tracking-policy-manager"),
                role_code="TRACK_POLICY_MANAGER", display_name="规则管理测试角色")
            EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role,
                effective_from=timezone.now() - timedelta(days=1))
            RoleActionGrant.objects.create(role=role, scope="MODULE", permission=Permission.objects.get(
                content_type__app_label="access_control", codename="manage_notifications"))
        self.client.force_login(user)
        return user, employee

    def test_migration_seeds_two_days_for_every_category(self):
        self.assertEqual(PurchaseTrackingPolicy.objects.count(), 1)
        state = self.state()
        expected = {key: 2 for key, _label in CATEGORY_CHOICES}
        self.assertEqual(state.data["data"]["bom_timeout_days"], 2)
        self.assertEqual(state.data["data"]["category_lead_days"], expected)
        self.assertEqual(state.data["data"]["categories"], [{"key": key, "label": label} for key, label in CATEGORY_CHOICES])
        self.assertEqual(state.data["data"]["etag"], state["ETag"])
        self.assertTrue(state.data["data"]["can_manage"])
        self.assertEqual(get_tracking_policy(), {"bom_timeout_days": 2, "category_lead_days": expected})

    @override_settings(PURCHASE_TRACKING_POLICY_ENABLED=False)
    def test_disabled_api_reports_unavailable_without_reading_policy_table(self):
        with patch.object(PurchaseTrackingPolicy.objects, "get", side_effect=AssertionError("不应读取新表")):
            self.assertEqual(self.client.get(self.url).status_code, 503)
            self.assertEqual(self.client.patch(self.url, {"bom_timeout_days": 3}, format="json").status_code, 503)

    def test_enabled_missing_policy_is_not_silently_defaulted(self):
        PurchaseTrackingPolicy.objects.all().delete()
        with self.assertRaises(PurchaseTrackingPolicy.DoesNotExist):
            get_tracking_policy()

    def test_partial_update_preserves_other_categories_and_records_actor_and_audit(self):
        before = self.state()
        response = self.save({"bom_timeout_days": 0, "category_lead_days": {"TUBE": 365, "FABRIC": None}}, before["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(data["bom_timeout_days"], 0)
        self.assertEqual(data["category_lead_days"]["TUBE"], 365)
        self.assertIsNone(data["category_lead_days"]["FABRIC"])
        self.assertEqual(data["category_lead_days"]["HARDWARE"], 2)
        self.assertNotEqual(response["ETag"], before["ETag"])
        self.assertEqual(PurchaseTrackingPolicy.objects.get().updated_by_employee_id, self.employee.pk)
        audit = self.audit().get()
        self.assertEqual(audit.before_data["bom_timeout_days"], 2)
        self.assertEqual(audit.after_data["bom_timeout_days"], 0)
        self.assertEqual(audit.actor_employee_id, self.employee.pk)
        self.assertEqual(self.save({"bom_timeout_days": None}).status_code, 200)
        self.assertIsNone(get_tracking_policy()["bom_timeout_days"])

    def test_invalid_days_categories_and_fields_rejected_without_changes(self):
        for payload in (
            {"bom_timeout_days": -1}, {"bom_timeout_days": 366}, {"bom_timeout_days": 1.5},
            {"bom_timeout_days": True}, {"category_lead_days": {"TUBE": -1}},
            {"category_lead_days": {"TUBE": 366}}, {"category_lead_days": {"TUBE": False}},
            {"category_lead_days": {"UNKNOWN": 2}}, {"category_lead_days": None},
            {"unknown": 2}, {},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.save(payload).status_code, 400)
        self.assertEqual(get_tracking_policy()["bom_timeout_days"], 2)
        self.assertEqual(self.audit().count(), 0)

    def test_missing_and_stale_etags_do_not_overwrite(self):
        etag = self.state()["ETag"]
        missing = self.client.patch(self.url, {"bom_timeout_days": 3}, format="json")
        self.assertEqual(missing.status_code, 428)
        self.assertEqual(self.save({"bom_timeout_days": 3}, etag).status_code, 200)
        stale = self.save({"bom_timeout_days": 4}, etag)
        self.assertEqual(stale.status_code, 412)
        self.assertEqual(get_tracking_policy()["bom_timeout_days"], 3)
        self.assertEqual(self.audit().count(), 1)

    def test_read_permission_and_management_role_are_separate(self):
        self.normal_employee()
        response = self.state()
        self.assertFalse(response.data["data"]["can_manage"])
        self.assertEqual(self.save({"bom_timeout_days": 3}).status_code, 403)
        self.assertEqual(self.audit().count(), 0)

    def test_role_authorized_manager_can_save(self):
        _user, employee = self.normal_employee(manager=True)
        self.assertTrue(self.state().data["data"]["can_manage"])
        self.assertEqual(self.save({"bom_timeout_days": 3}).status_code, 200)
        self.assertEqual(self.audit().get().actor_employee_id, employee.pk)

    def test_employee_without_purchase_view_and_anonymous_are_denied(self):
        self.normal_employee(viewer=False)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_inactive_employee_cannot_read_or_save(self):
        self.employee.status = "LEFT"
        self.employee.save(update_fields=["status"])
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.patch(self.url, {"bom_timeout_days": 3}, format="json").status_code, 403)

    def test_real_session_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        etag = client.get(self.url)["ETag"]
        self.assertEqual(client.patch(self.url, {"bom_timeout_days": 3}, format="json", HTTP_IF_MATCH=etag).status_code, 403)
        token = _get_new_csrf_string()
        client.cookies["csrftoken"] = token
        response = client.patch(self.url, {"bom_timeout_days": 3}, format="json", HTTP_IF_MATCH=etag, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200, response.data)

    @override_settings(PURCHASE_TRACKING_ENABLED=True)
    def test_save_makes_rules_readable_without_running_scan(self):
        with patch("apps.procurement.tracking_runner.recompute_tracking") as recompute:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                response = self.save({"bom_timeout_days": 3})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(callbacks, [])
            recompute.assert_not_called()
        self.assertEqual(response.data["data"]["bom_timeout_days"], 3)
        self.assertEqual(get_tracking_policy()["bom_timeout_days"], 3)
        self.assertEqual(self.state().data["data"]["bom_timeout_days"], 3)
        self.assertEqual(self.audit().get().after_data["bom_timeout_days"], 3)

    def test_audit_failure_rolls_back_settings(self):
        with patch("apps.procurement.tracking_policy.write_audit_log", side_effect=RuntimeError("审计不可用")):
            with self.assertRaisesMessage(RuntimeError, "审计不可用"):
                self.save({"bom_timeout_days": 3})
        self.assertEqual(get_tracking_policy()["bom_timeout_days"], 2)

    def test_database_enforces_singleton_and_timeout_range(self):
        for values in ({"key": "other"}, {"key": "default"}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                PurchaseTrackingPolicy.objects.create(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PurchaseTrackingPolicy.objects.filter(key="default").update(bom_timeout_days=366)
