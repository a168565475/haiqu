from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.customers.models import CustomerAccount
from apps.organizations.models import Employee
from apps.products.models import ProductInformation
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.reference_data.models import Currency, ProductCategory, ProductItem, ProductionUnit
from apps.boms.api.serializers import BomDetailSerializer, BomListSerializer
from apps.boms.models import Bom, BomLine, BomSection
from apps.boms.selectors import boms_with_context


class BomLoadingReadTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="bom_loading_reader")
        self.employee = Employee.objects.create(user=self.user, employee_code="BOM_LOAD", display_name="BOM 读取测试")
        self.other = Employee.objects.create(employee_code="BOM_OTHER", display_name="其他员工")
        self.user.user_permissions.set(Permission.objects.filter(codename__in=["view_bom", "view_productiontask"]))
        self.customer = CustomerAccount.objects.create(account_code="BOM_LOAD_CUSTOMER", account_name="BOM 加载客户", primary_country_code="CN")
        self.currency, _ = Currency.objects.get_or_create(code="USD", defaults={"numeric_code": "840", "chinese_name": "美元", "english_name": "US Dollar"})
        self.category = ProductCategory.objects.create(item_type="FINISHED", category_name="加载测试成品")
        self.unit = ProductionUnit.objects.create(unit_code="BOM_LOAD_UNIT", unit_name="个")
        self.item = ProductItem.objects.create(item_number="BOM_LOAD_ITEM", category=self.category)
        self.product = ProductInformation.objects.create(product_number="BOM_LOAD_PRODUCT", product_code="BOM_LOAD_CODE", category=self.category,
                                                        product_item=self.item, unit=self.unit, product_name="加载产品", specification="测试", scale="REGULAR")
        self.task, self.product_line = self.create_task("OWN", self.employee)
        self.old = self.create_bom("OLD", self.task, self.product_line, version_number=1, maintenance_match_count=2)
        self.create_bom("PENDING", self.task, self.product_line, version_number=2, maintenance_match_count=2)
        self.create_bom("VERIFIED", self.task, self.product_line, version_number=3, maintenance_match_count=2, status="VERIFIED")
        self.current = self.create_bom("CURRENT", self.task, self.product_line, version_number=4, copied_from=self.old,
                                       maintenance_match_count=2, status="VERIFIED", confirmed_by_employee=self.employee)
        self.create_bom("ARCHIVED", self.task, self.product_line, version_number=5, archived_at=timezone.now(), maintenance_match_count=100)
        hidden_task, hidden_line = self.create_task("HIDDEN", self.other)
        self.hidden = self.create_bom("HIDDEN", hidden_task, hidden_line, maintenance_match_count=100)
        section = BomSection.objects.create(bom=self.current, line_number=1, section_type="FABRIC", title="裁剪明细")
        BomLine.objects.create(section=section, line_number=1, part_name="裁剪原料", raw_values={"cutting_item_type": "SEMI_FINISHED", "cutting_item_type_display": "半成品", "cutting_category": "裁片", "cutting_color": "蓝色"})
        self.client.force_authenticate(self.user)

    def create_task(self, suffix, employee):
        task = ProductionTask.objects.create(task_number=f"BOM-{suffix}", contract_number=f"BOM-CONTRACT-{suffix}", order_number=f"ORDER-{suffix}",
                                             order_source="NEW", customer_account=self.customer, salesperson=employee, currency=self.currency,
                                             order_date=date(2026, 9, 16), delivery_date=date(2026, 10, 1), includes_tax=False, order_tolerance_percent=0,
                                             is_repeat_order=False, preproduction_sample_required=False, delivery_method="SINGLE")
        line = ProductionTaskProduct.objects.create(production_task=task, line_number=1, product=self.product, product_number_snapshot=self.product.product_number,
                                                    product_code_snapshot=self.product.product_code, item_number_snapshot=self.item.item_number,
                                                    product_name_snapshot=self.product.product_name, specification_snapshot=self.product.specification,
                                                    quantity=10, unit=self.unit, currency=self.currency, unit_price=1, total_amount=10, exchange_rate=1)
        return task, line

    def create_bom(self, suffix, task, line, **overrides):
        values = dict(bom_number=f"BOM-LOAD-{suffix}", production_task=task, product_line=line, creation_method="BLANK",
                      product_number_snapshot=line.product_number_snapshot, product_code_snapshot=line.product_code_snapshot,
                      product_name_snapshot=line.product_name_snapshot, specification_snapshot=line.specification_snapshot,
                      order_quantity=9, created_by_employee=self.employee, updated_by_employee=self.employee)
        values.update(overrides)
        return Bom.objects.create(**values)

    def test_stats_use_one_query_and_keep_scope_and_duplicate_values_in_sum(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/v1/boms/stats/', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data'], dict(total=4, pending_confirmation=2, verified=2, maintenance_reference_count=8))
        self.assertEqual(sum('FROM "bom"' in item['sql'] for item in queries), 1)

    def test_stats_filters_empty_and_status_independence(self):
        for params, expected in [({'status': 'VERIFIED'}, 4), ({'q': 'BOM-LOAD-CURRENT'}, 1), ({'q': 'NO-MATCH'}, 0), ({'product_category_id': str(self.category.pk)}, 4)]:
            with self.subTest(params=params):
                response = self.client.get('/api/v1/boms/stats/', params, HTTP_HOST='localhost')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['data'], dict(
                    total=expected,
                    pending_confirmation=2 if expected == 4 else 0,
                    verified=2 if expected == 4 else expected,
                    maintenance_reference_count=expected * 2,
                ))

    def test_filter_options_only_read_active_finished_categories(self):
        ProductCategory.objects.create(item_type="MATERIAL", category_name="非成品类别")
        ProductCategory.objects.create(item_type="FINISHED", category_name="停用类别", status="INACTIVE")
        ProductCategory.objects.create(item_type="FINISHED", category_name="归档类别", archived_at=timezone.now())
        full = self.client.get('/api/v1/boms/options/', HTTP_HOST='localhost')
        self.assertEqual(full.status_code, 200, full.data)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/v1/boms/options/', {'scope': 'filters'}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data'], {'product_categories': full.data['data']['product_categories']})
        self.assertEqual([row['category_name'] for row in response.data['data']['product_categories']], ['加载测试成品'])
        sql = '\n'.join(item['sql'] for item in queries)
        for table in ['bom', 'production_task', 'product_information', 'reference_currency']:
            self.assertNotIn(f'FROM "{table}"', sql)
        self.assertIn('production_task_products', full.data['data'])
        self.assertIn('history_boms', full.data['data'])

    def test_compact_relations_preserve_complete_list_and_detail_payloads(self):
        for include_lines, serializer in [(False, BomListSerializer), (True, BomDetailSerializer)]:
            with self.subTest(include_lines=include_lines):
                before = boms_with_context(Bom.objects.filter(pk__in=[self.old.pk, self.current.pk]), include_lines=include_lines)
                after = boms_with_context(Bom.objects.filter(pk__in=[self.old.pk, self.current.pk]), include_lines=include_lines, read_optimized=True)
                expected = serializer(before, many=True).data
                with CaptureQueriesContext(connection) as queries:
                    actual = serializer(after, many=True).data
                self.assertEqual(actual, expected)
                self.assertEqual(len(queries), 5 if include_lines else 3)
                sql = queries[0]['sql']
                self.assertNotIn('JOIN "product_information"', sql)
                self.assertNotIn('JOIN "reference_product_category"', sql)
                self.assertNotIn('JOIN "business_file"', sql)
        detail = BomDetailSerializer(boms_with_context(Bom.objects.filter(pk=self.current.pk), include_lines=True, read_optimized=True).get()).data
        self.assertEqual(detail['copied_from_number'], self.old.bom_number)
        self.assertTrue(detail['is_order_quantity_outdated'])
        self.assertEqual(detail['sections'][0]['lines'][0]['cutting_color'], '蓝色')

    def test_read_api_rejects_invalid_parameters_and_hidden_detail(self):
        for action, params in [('options', {'scope': 'bad'}), ('stats', {'status': 'bad'}), ('stats', {'product_category_id': 'bad'}), ('stats', {'updated_after': '2026-10-01', 'updated_before': '2026-09-01'})]:
            with self.subTest(action=action, params=params):
                self.assertEqual(self.client.get(f'/api/v1/boms/{action}/', params, HTTP_HOST='localhost').status_code, 400)
        self.assertEqual(self.client.get(f'/api/v1/boms/{self.hidden.pk}/', HTTP_HOST='localhost').status_code, 404)

    def test_missing_bom_permission_cannot_read(self):
        user = get_user_model().objects.create_user(username="bom_loading_denied")
        Employee.objects.create(user=user, employee_code="BOM_LOAD_DENIED", display_name="无权限")
        self.client.force_authenticate(user)
        for suffix in ['', 'stats/', 'options/?scope=filters', f'{self.current.pk}/']:
            self.assertEqual(self.client.get('/api/v1/boms/' + suffix, HTTP_HOST='localhost').status_code, 403)
