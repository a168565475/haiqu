from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.customers.models import CustomerAccount
from apps.organizations.models import Employee
from apps.reference_data.models import Currency
from apps.production_tasks.models import ProductionTask, ProductionTaskStatus


class ProductionLoadingReadTests(APITestCase):
    """自建最小数据，验证统计去重、数据权限和轻量选项契约。"""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="loading_reader")
        self.employee = Employee.objects.create(user=self.user, employee_code="LOAD_READER", display_name="读取测试")
        self.other = Employee.objects.create(employee_code="LOAD_OTHER", display_name="其他员工")
        self.user.user_permissions.set(Permission.objects.filter(
            content_type__app_label="production_tasks", codename="view_productiontask",
        ))
        self.customer = CustomerAccount.objects.create(account_code="LOAD_CUSTOMER", account_name="加载测试客户", primary_country_code="CN")
        self.currency, _ = Currency.objects.get_or_create(code="USD", defaults={"numeric_code": "840", "chinese_name": "美元", "english_name": "US Dollar"})
        self.client.force_authenticate(self.user)
        self.tasks = []
        for index, status in enumerate(ProductionTaskStatus.values):
            task = self.create_task(str(index), status=status, delivery_method="SPLIT" if index == 0 else "SINGLE")
            task.followers.add(self.employee, self.other)
            self.tasks.append(task)
        self.create_task("HIDDEN", salesperson=self.other)
        self.create_task("ARCHIVED", archived_at=timezone.now())

    def create_task(self, suffix, **overrides):
        values = dict(task_number=f"LOAD-{suffix}", contract_number=f"CONTRACT-{suffix}", order_number=f"ORDER-{suffix}",
                      order_source="NEW", customer_account=self.customer, salesperson=self.employee, currency=self.currency,
                      order_date=date(2026, 9, 15), delivery_date=date(2026, 10, 1), includes_tax=False,
                      order_tolerance_percent=0, is_repeat_order=False, preproduction_sample_required=False, delivery_method="SINGLE")
        values.update(overrides)
        return ProductionTask.objects.create(**values)

    def get_stats(self, params=None):
        response = self.client.get("/api/v1/production-tasks/stats/", params or {}, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def test_stats_use_one_task_query_and_keep_scope_and_distinct_counts(self):
        with CaptureQueriesContext(connection) as queries:
            data = self.get_stats()
        self.assertEqual(data, dict(all=7, draft=1, pending_validation=1, ready=1, in_production=1, completed=1, paused=1, cancelled=1, split_delivery=1))
        task_queries = [item["sql"] for item in queries if 'FROM "production_task"' in item["sql"]]
        self.assertEqual(len(task_queries), 1)

    def test_stats_ignore_selected_status_but_apply_other_filters(self):
        self.assertEqual(self.get_stats({"status": "READY"})["all"], 7)
        data = self.get_stats({"search": "ORDER-0", "follower_id": str(self.employee.pk)})
        self.assertEqual(data["all"], 1)
        self.assertEqual(data["draft"], 1)
        self.assertEqual(data["split_delivery"], 1)
        self.assertEqual(self.get_stats({"search": "DOES-NOT-EXIST"})["all"], 0)

    def test_filter_options_match_full_subset_without_editor_queries(self):
        full = self.client.get("/api/v1/production-tasks/options/", HTTP_HOST="localhost")
        self.assertEqual(full.status_code, 200, full.data)
        with CaptureQueriesContext(connection) as queries:
            filtered = self.client.get("/api/v1/production-tasks/options/", {"scope": "filters"}, HTTP_HOST="localhost")
        self.assertEqual(filtered.status_code, 200, filtered.data)
        keys = {"customers", "employees", "products", "statuses", "delivery_methods", "order_sources"}
        self.assertEqual(set(filtered.data["data"]), keys)
        self.assertEqual(filtered.data["data"], {key: full.data["data"][key] for key in keys})
        self.assertTrue({"currencies", "units", "colors", "boolean_options", "detail_template"} <= full.data["data"].keys())
        sql = "\n".join(item["sql"] for item in queries)
        for table in ["reference_currency", "reference_production_unit", "reference_product_color"]:
            self.assertNotIn(f'FROM "{table}"', sql)

    def test_invalid_scope_and_filters_return_validation_errors(self):
        for path, params in [("options", {"scope": "invalid"}), ("stats", {"status": "invalid"}), ("stats", {"follower_id": "invalid"})]:
            with self.subTest(path=path, params=params):
                response = self.client.get(f"/api/v1/production-tasks/{path}/", params, HTTP_HOST="localhost")
                self.assertEqual(response.status_code, 400)

    def test_missing_permission_cannot_read_stats_or_options(self):
        user = get_user_model().objects.create_user(username="loading_no_permission")
        Employee.objects.create(user=user, employee_code="LOAD_DENIED", display_name="无权限")
        self.client.force_authenticate(user)
        for path in ["stats", "options?scope=filters"]:
            url = "/api/v1/production-tasks/options/?scope=filters" if path.startswith("options") else "/api/v1/production-tasks/stats/"
            self.assertEqual(self.client.get(url, HTTP_HOST="localhost").status_code, 403)
