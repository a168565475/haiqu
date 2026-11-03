"""基础与高级筛选分别读取所需数据，保留历史选项的可见任务边界。"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.organizations.models import (
    Employee, EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile,
)
from apps.product_catalog.models import ProductCatalog, ProductCatalogCategory, ProductCatalogName
from apps.products.models import ProductInformation
from apps.reference_data.models import Currency, ProductCategory, ProductItem, ProductionUnit

from ..models import ProductionTask, ProductionTaskProduct


class ProductionTaskFilterOptionsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="filter-options-reader")
        cls.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="production_tasks", codename="view_productiontask",
        ))
        cls.reader = Employee.objects.create(user=cls.user, employee_code="FILTER-READER", display_name="筛选读取员工")
        cls.current_sales = Employee.objects.create(employee_code="FILTER-SALES", display_name="当前业务员")
        cls.current_follower = Employee.objects.create(employee_code="FILTER-FOLLOWER", display_name="当前跟单员")
        cls.historical_sales = Employee.objects.create(
            employee_code="FILTER-OLD-SALES", display_name="历史业务员", status="INACTIVE",
        )
        cls.historical_follower = Employee.objects.create(
            employee_code="FILTER-OLD-FOLLOW", display_name="历史跟单员", status="LEFT",
        )
        cls.hidden_employee = Employee.objects.create(
            employee_code="FILTER-HIDDEN", display_name="不可见历史员工", status="INACTIVE",
        )
        department, _ = OrganizationUnit.objects.get_or_create(
            unit_code="DEPT_BUSINESS", defaults={"unit_name": "业务部"},
        )
        EmployeeOrganizationAssignment.objects.create(
            employee=cls.current_sales, organization_unit=department, effective_from=timezone.now() - timedelta(days=1),
        )
        group, _ = Group.objects.get_or_create(name="FILTER-OPTIONS-MERCHANDISER")
        role, _ = RoleProfile.objects.get_or_create(
            role_code="MERCHANDISER", defaults={"display_name": "跟单", "auth_group": group},
        )
        EmployeeRoleAssignment.objects.create(
            employee=cls.current_follower, role_profile=role, effective_from=timezone.now() - timedelta(days=1),
        )
        cls.currency, _ = Currency.objects.get_or_create(code="CNY", defaults={
            "numeric_code": "156", "chinese_name": "人民币", "english_name": "Yuan Renminbi",
        })
        cls.unit = ProductionUnit.objects.create(unit_code="FILTER-UNIT", unit_name="筛选专用单位")
        cls.visible_task = cls.create_task("VISIBLE", cls.historical_sales, cls.reader)
        cls.visible_task.followers.add(cls.historical_follower)
        cls.hidden_task = cls.create_task("HIDDEN", cls.hidden_employee, cls.hidden_employee)
        cls.hidden_task.followers.add(cls.hidden_employee)

        category = ProductCategory.objects.create(item_type="FINISHED", category_name="筛选专用成品类别")
        item = ProductItem.objects.create(category=category, item_number="FILTER-LEGACY-ITEM")
        cls.legacy_product = ProductInformation.objects.create(
            product_number="FILTER-LEGACY", product_code="FILTER-LEGACY-CODE", category=category,
            product_name="历史产品主档", specification="历史规格", unit=cls.unit, product_item=item, scale="REGULAR",
        )
        catalog_category = ProductCatalogCategory.objects.create(name="筛选专用目录类别")
        cls.catalog_name = ProductCatalogName.objects.create(category=catalog_category, name="目录产品")
        cls.active_catalog = cls.create_catalog("ACTIVE")
        cls.visible_catalog = cls.create_catalog("VISIBLE", archived_at=timezone.now())
        cls.hidden_catalog = cls.create_catalog("HIDDEN", archived_at=timezone.now())
        cls.unused_catalog = cls.create_catalog("UNUSED", archived_at=timezone.now())
        for task, catalog in ((cls.visible_task, cls.visible_catalog), (cls.hidden_task, cls.hidden_catalog)):
            ProductionTaskProduct.objects.create(
                production_task=task, line_number=1, product_catalog=catalog, product_name_snapshot="目录产品",
                quantity=1, unit=cls.unit, currency=cls.currency, unit_price=1, total_amount=1, exchange_rate=1,
            )

    @classmethod
    def create_task(cls, suffix, salesperson, creator):
        return ProductionTask.objects.create(
            task_number=f"FILTER-{suffix}", contract_number=f"FILTER-{suffix}", order_source="NEW",
            order_date=date(2026, 11, 1), delivery_date=date(2026, 11, 30), salesperson=salesperson,
            created_by_employee=creator, currency=cls.currency, includes_tax=False, order_tolerance_percent=0,
            is_repeat_order=False, preproduction_sample_required=False, delivery_method="SINGLE",
        )

    @classmethod
    def create_catalog(cls, suffix, **extra):
        return ProductCatalog.objects.create(
            name=cls.catalog_name, product_code=f"FILTER-{suffix}", item_number=f"ITEM-{suffix}",
            specification=f"规格 {suffix}", unit="仅详情单位", materials=["仅详情材质"], thicknesses=["1"], **extra,
        )

    def setUp(self):
        self.client.force_authenticate(self.user)

    def options(self, scope=None, **params):
        if scope is not None:
            params["scope"] = scope
        response = self.client.get("/api/v1/production-tasks/options/", params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def test_basic_scope_only_reads_salespeople_and_preserves_visible_history(self):
        with CaptureQueriesContext(connection) as queries:
            data = self.options("filters")
        self.assertEqual(set(data), {"salespeople"})
        ids = {item["id"] for item in data["salespeople"]}
        self.assertTrue({str(self.current_sales.pk), str(self.historical_sales.pk)} <= ids)
        self.assertNotIn(str(self.hidden_employee.pk), ids)
        for item in data["salespeople"]:
            self.assertEqual(set(item), {"id", "display_name"})
        sql = "\n".join(item["sql"] for item in queries)
        for table in ("product_information", "product_catalog", "reference_production_unit", "reference_currency"):
            self.assertNotIn(f'"{table}"', sql)
        self.assertNotIn("MERCHANDISER", sql)
        # 权限子查询可涉及客户归属，但不应另行加载客户选项。
        self.assertFalse(any(item["sql"].startswith('SELECT "customer_account".') for item in queries))
        employee_query = next(item["sql"] for item in queries if "DEPT_BUSINESS" in item["sql"])
        self.assertRegex(employee_query.split(' FROM "employee"', 1)[0],
                         r'^SELECT "employee"\."id"(?: AS "id")?, "employee"\."display_name"(?: AS "display_name")?$')

    def test_advanced_scope_only_returns_required_choices_and_columns(self):
        with CaptureQueriesContext(connection) as queries:
            data = self.options("advanced_filters")
        self.assertEqual(set(data), {"employees", "products", "product_catalogs", "order_sources", "delivery_methods"})
        for item in data["employees"]:
            self.assertEqual(set(item), {"id", "display_name"})
        for item in [*data["products"], *data["product_catalogs"]]:
            self.assertEqual(set(item), {"id", "product_code", "item_number", "product_name", "specification"})
        legacy = next(item for item in data["products"] if item["id"] == str(self.legacy_product.pk))
        self.assertEqual(legacy, {
            "id": str(self.legacy_product.pk), "product_code": "FILTER-LEGACY-CODE",
            "item_number": "FILTER-LEGACY-ITEM", "product_name": "历史产品主档", "specification": "历史规格",
        })
        sql = "\n".join(item["sql"] for item in queries)
        for table in ("reference_production_unit", "reference_currency", "reference_product_color"):
            self.assertNotIn(f'"{table}"', sql)
        self.assertNotIn("DEPT_BUSINESS", sql)
        self.assertFalse(any(item["sql"].startswith('SELECT "customer_account".') for item in queries))
        catalog_query = next(item["sql"] for item in queries if 'FROM "product_catalog"' in item["sql"])
        for field in ("source_raw_fields", "materials", "thicknesses", "unit", "scale"):
            self.assertNotIn(f'"product_catalog"."{field}"', catalog_query)
        employee_query = next(item["sql"] for item in queries if "MERCHANDISER" in item["sql"])
        self.assertRegex(employee_query.split(' FROM "employee"', 1)[0],
                         r'^SELECT "employee"\."id"(?: AS "id")?, "employee"\."display_name"(?: AS "display_name")?$')

    def test_advanced_scope_keeps_only_visible_historical_followers_and_catalogs(self):
        data = self.options("advanced_filters")
        employee_ids = {item["id"] for item in data["employees"]}
        self.assertTrue({str(self.current_follower.pk), str(self.historical_follower.pk)} <= employee_ids)
        self.assertNotIn(str(self.hidden_employee.pk), employee_ids)
        catalog_ids = {item["id"] for item in data["product_catalogs"]}
        self.assertTrue({str(self.active_catalog.pk), str(self.visible_catalog.pk)} <= catalog_ids)
        self.assertNotIn(str(self.hidden_catalog.pk), catalog_ids)
        self.assertNotIn(str(self.unused_catalog.pk), catalog_ids)
        empty_history = self.options("advanced_filters", search="DOES-NOT-EXIST")
        self.assertNotIn(str(self.visible_catalog.pk), {item["id"] for item in empty_history["product_catalogs"]})
        self.assertNotIn(str(self.historical_follower.pk), {item["id"] for item in empty_history["employees"]})

    def test_default_and_explicit_full_keep_editor_contract(self):
        default = self.options()
        self.assertEqual(default, self.options("full"))
        self.assertTrue({"customers", "employees", "salespeople", "products", "statuses", "categories",
                         "currencies", "units", "colors", "boolean_options", "detail_template", "recent_task_numbers"} <= set(default))
        salesperson = next(item for item in default["salespeople"] if item["id"] == str(self.current_sales.pk))
        self.assertEqual(set(salesperson), {"id", "employee_code", "display_name"})
        self.assertNotIn(str(self.historical_sales.pk), {item["id"] for item in default["salespeople"]})
        self.assertNotIn(str(self.historical_follower.pk), {item["id"] for item in default["employees"]})
        legacy = next(item for item in default["products"] if item["id"] == str(self.legacy_product.pk))
        self.assertTrue({"product_number", "default_unit_id", "category_id", "unit_code", "unit_name"} <= set(legacy))

    def test_filter_scopes_require_login_and_task_permission(self):
        anonymous = APIClient()
        denied = get_user_model().objects.create_user(username="filter-options-denied")
        Employee.objects.create(user=denied, employee_code="FILTER-DENIED", display_name="无权限")
        self.client.force_authenticate(denied)
        for scope in ("filters", "advanced_filters"):
            with self.subTest(scope=scope):
                self.assertIn(anonymous.get("/api/v1/production-tasks/options/", {"scope": scope}).status_code, (401, 403))
                self.assertEqual(self.client.get("/api/v1/production-tasks/options/", {"scope": scope}).status_code, 403)

    def test_invalid_scope_returns_validation_error(self):
        for scope in ("invalid", "", "FILTERS"):
            with self.subTest(scope=scope):
                response = self.client.get("/api/v1/production-tasks/options/", {"scope": scope})
                self.assertEqual(response.status_code, 400)
