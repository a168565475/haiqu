import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.organizations.models import Employee, EmployeeOrganizationAssignment, OrganizationUnit

from ..models import SampleRequest


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, DEV_AUTO_LOGIN_ENABLED=False)
class SampleFilterOptionsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("sample-options-admin", password="test")
        cls.admin_employee = Employee.objects.create(user=cls.admin, employee_code="SAMPLE_OPTIONS_ADMIN", display_name="管理员")
        cls.user = get_user_model().objects.create_user("sample-options-owner")
        cls.owner = Employee.objects.create(user=cls.user, employee_code="SAMPLE_OPTIONS_OWNER", display_name="业务员")
        cls.user.user_permissions.add(Permission.objects.get(content_type__app_label="samples", codename="view_samplerequest"))
        department, _ = OrganizationUnit.objects.get_or_create(unit_code="DEPT_BUSINESS", defaults={"unit_name": "业务部"})
        EmployeeOrganizationAssignment.objects.create(employee=cls.owner, organization_unit=department, effective_from=timezone.now())
        cls.historical = Employee.objects.create(employee_code="SAMPLE_OPTIONS_HISTORY", display_name="历史业务员", status="INACTIVE")
        cls.hidden = Employee.objects.create(employee_code="SAMPLE_OPTIONS_HIDDEN", display_name="不可见业务员", status="INACTIVE")
        SampleRequest.objects.create(
            request_number="OPTIONS-VISIBLE", owner_employee=cls.historical, requested_by_employee=cls.owner,
            requested_at=timezone.now(),
        )
        SampleRequest.objects.create(
            request_number="OPTIONS-HIDDEN", owner_employee=cls.hidden, requested_by_employee=cls.admin_employee,
            requested_at=timezone.now(),
        )

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_filter_scope_queries_only_minimal_owner_choices(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/v1/sample-requests/options/", {"scope": "filters"})
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(set(data), {"sample_types", "statuses", "owner_filters"})
        self.assertTrue(data["owner_filters"])
        self.assertTrue(all(set(row) == {"id", "display_name"} for row in data["owner_filters"]))
        sqls = [query["sql"] for query in queries]
        main_tables = [re.search(r'\bFROM "([^"]+)"', sql).group(1) for sql in sqls if re.search(r'\bFROM "([^"]+)"', sql)]
        self.assertNotIn("customer_account", main_tables)
        self.assertNotIn("sample_product", main_tables)
        self.assertNotIn("business_file", main_tables)
        owner_queries = [sql for sql in sqls if 'FROM "employee"' in sql and 'FROM "sample_request"' in sql and '"owner_employee_id"' in sql]
        self.assertEqual(len(owner_queries), 1)
        owner_sql = owner_queries[0]
        self.assertRegex(owner_sql.split(' FROM ', 1)[0], r'^SELECT "employee"\."id"(?: AS "id")?, "employee"\."display_name"(?: AS "display_name")?$')

    def test_filter_scope_preserves_visible_historical_owners(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/v1/sample-requests/options/", {"scope": "filters"})
        self.assertEqual(response.status_code, 200, response.data)
        ids = {str(row["id"]) for row in response.data["data"]["owner_filters"]}
        self.assertIn(str(self.owner.pk), ids)
        self.assertIn(str(self.historical.pk), ids)
        self.assertNotIn(str(self.hidden.pk), ids)

    def test_full_options_remain_compatible(self):
        full = self.client.get("/api/v1/sample-requests/options/")
        explicit = self.client.get("/api/v1/sample-requests/options/", {"scope": "full"})
        filters = self.client.get("/api/v1/sample-requests/options/", {"scope": "filters"})
        self.assertEqual(full.status_code, 200, full.data)
        self.assertEqual(full.data, explicit.data)
        self.assertEqual(set(full.data["data"]), {
            "sample_types", "statuses", "customers", "owner_filters", "owners", "fee_decisions",
            "freight_bearers", "fee_verification_statuses", "fee_approvers",
        })
        for key in ("sample_types", "statuses"):
            self.assertEqual(full.data["data"][key], filters.data["data"][key])
        self.assertEqual(set(full.data["data"]["owners"][0]), {"id", "employee_code", "display_name"})

    def test_invalid_scope_and_missing_permission_are_rejected(self):
        invalid = self.client.get("/api/v1/sample-requests/options/", {"scope": "other"})
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("scope", invalid.data["error"]["field_errors"])
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get("/api/v1/sample-requests/options/", {"scope": "filters"}).status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get("/api/v1/sample-requests/options/", {"scope": "filters"}).status_code, (401, 403))
