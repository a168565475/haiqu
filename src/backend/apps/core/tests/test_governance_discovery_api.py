from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.customers.models import CustomerAccount, CustomerAssignment
from apps.organizations.models import Employee
from apps.preferences.models import SavedView


class GovernanceDiscoveryApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="discovery_user")
        self.employee = Employee.objects.create(
            user=self.user, employee_code="DISCOVERY_USER", display_name="首页测试员工"
        )
        self.user.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label__in=["customers", "preferences", "audit", "inquiries", "quotations", "samples", "workflow"]
            ).exclude(codename__in=["view_all_customer", "view_all_auditlog"])
        )
        self.customer = CustomerAccount.objects.create(
            account_code="DISCOVERY_CUSTOMER", account_name="海趣搜索客户", primary_country_code="CN"
        )
        CustomerAssignment.objects.create(
            customer_account=self.customer, employee=self.employee,
            assignment_role="PRIMARY_OWNER", effective_from=timezone.now(),
        )
        AuditLog.objects.create(
            actor_employee=self.employee, object_type="CUSTOMER_ACCOUNT", object_id=self.customer.pk,
            context_type="CUSTOMER_ACCOUNT", context_id=self.customer.pk, action="CREATED", occurred_at=timezone.now(),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_search_dashboard_saved_view_and_scoped_audit(self):
        search = self.client.get("/api/v1/search/", {"q": "海趣"})
        self.assertEqual(search.status_code, 200, search.data)
        self.assertEqual(search.data["data"][0]["type"], "CUSTOMER")

        dashboard = self.client.get("/api/v1/dashboard/me/")
        self.assertEqual(dashboard.status_code, 200, dashboard.data)
        self.assertEqual(dashboard.data["data"]["counts"]["customers"], 1)

        saved = self.client.post(
            "/api/v1/saved-views/",
            {
                "module_code": "CUSTOMER", "view_name": "中国潜客",
                "filter_definition": {"lifecycle_stage": "PROSPECT", "primary_country_code": "CN"},
                "column_definition": ["account_code", "account_name"],
                "sort_definition": ["-updated_at"], "sort_order": 10,
            }, format="json",
        )
        self.assertEqual(saved.status_code, 201, saved.data)
        self.assertTrue(SavedView.objects.filter(employee=self.employee, view_name="中国潜客").exists())

        scoped_audit = self.client.get(f"/api/v1/customers/{self.customer.pk}/audit-logs/")
        global_audit = self.client.get("/api/v1/audit-logs/")
        self.assertEqual(scoped_audit.status_code, 200, scoped_audit.data)
        self.assertEqual(scoped_audit.data["meta"]["total"], 1)
        self.assertEqual(global_audit.status_code, 403, global_audit.data)

    def test_manager_dashboard_requires_global_customer_scope(self):
        denied = self.client.get("/api/v1/dashboard/manager/")
        self.assertEqual(denied.status_code, 403, denied.data)
        self.user.user_permissions.add(Permission.objects.get(codename="view_all_customer", content_type__app_label="customers"))
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)
        allowed = self.client.get("/api/v1/dashboard/manager/")
        self.assertEqual(allowed.status_code, 200, allowed.data)
        self.assertEqual(allowed.data["meta"]["scope"], "MANAGER")
