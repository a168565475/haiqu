from decimal import Decimal
import json
from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.renderers import JSONRenderer
from ..models import ProductionTaskProduct
from ..api.serializers import ProductionTaskCreateFromSalesOrderSerializer, ProductionTaskProductReadSerializer, ProductionSalesSourceLineSerializer


class PricingContractTests(SimpleTestCase):
    def test_local_money_is_four_decimal_string_in_rendered_json(self):
        names = ('local_unit_price', 'unit_price_base', 'local_total_amount', 'line_amount_base')
        for price, total, rate, expected_price, expected_total in (
            ('15', '40', '1', '15.0000', '40.0000'),
            ('0.0025', '0.0075', '1', '0.0025', '0.0075'),
            ('0', '0', '1', '0.0000', '0.0000'),
            ('99999999999999.9999', '9007199254740993.1234', '1',
             '99999999999999.9999', '9007199254740993.1234'),
            ('1.2345', '2.4690', '2', '2.4690', '4.9380'),
        ):
            with self.subTest(price=price, total=total, rate=rate):
                serializer = ProductionTaskProductReadSerializer(instance=SimpleNamespace(
                    unit_price=Decimal(price), total_amount=Decimal(total), exchange_rate=Decimal(rate),
                ))
                for field in list(serializer.fields):
                    if field not in names:
                        serializer.fields.pop(field)
                rendered = json.loads(JSONRenderer().render(serializer.data))
                self.assertEqual(rendered, dict(local_unit_price=expected_price, unit_price_base=expected_price,
                                               local_total_amount=expected_total, line_amount_base=expected_total))

    def test_exchange_rate_model_preserves_eight_places(self):
        field = ProductionTaskProduct._meta.get_field('exchange_rate')
        self.assertEqual(field.decimal_places, 8)
        self.assertEqual(field.max_digits, 25)
        self.assertEqual(field.validators[0].limit_value, Decimal('0.00000001'))

    def test_manual_snapshot_identifiers_can_be_blank(self):
        for name in ['product_number_snapshot', 'item_number_snapshot']:
            self.assertTrue(ProductionTaskProduct._meta.get_field(name).blank)

    def test_source_creation_requires_independent_business_fields(self):
        serializer = ProductionTaskCreateFromSalesOrderSerializer(data={})
        self.assertFalse(serializer.is_valid())
        for field in ['follower_ids', 'delivery_date', 'includes_tax', 'order_tolerance_percent', 'is_repeat_order', 'delivery_method']:
            self.assertIn(field, serializer.errors)

    def test_source_lines_include_real_units_and_original_prices(self):
        fields = ProductionSalesSourceLineSerializer().fields
        for field in ['unit_id', 'unit_code', 'unit_name', 'unit_price', 'line_total']:
            self.assertIn(field, fields)

    def test_source_summary_preserves_order_currency_and_total(self):
        from ..api.serializers import ProductionSalesSourceSummarySerializer
        fields = ProductionSalesSourceSummarySerializer().fields
        self.assertIn("currency_code", fields)
        self.assertIn("total_amount", fields)

    def test_product_detail_exposes_auditable_rate_snapshot(self):
        fields = ProductionTaskProductReadSerializer().fields
        self.assertIn('exchange_rate_record_id', fields)
        self.assertIn('exchange_rate_snapshot', fields)
        self.assertIn('unit_price_base', fields)
        self.assertIn('line_amount_base', fields)

from datetime import timedelta
from uuid import uuid4
from django.utils import timezone
from rest_framework.test import APITestCase
from apps.reference_data.models import Currency, ExchangeRate
from apps.sales_orders.tests import test_sales_order_api as sales_fixtures


class SourcePricingTests(APITestCase):
    def setUp(self):
        sales_fixtures.SalesOrderApiTests.setUp(self)
        ExchangeRate.objects.update(status='INACTIVE')

    direct_payload = sales_fixtures.SalesOrderApiTests.direct_payload
    create_direct = sales_fixtures.SalesOrderApiTests.create_direct

    def source(self, currency='CNY'):
        record = ExchangeRate.objects.filter(base_currency__code=currency, quote_currency__code='CNY', status='ACTIVE').first()
        created = self.create_direct(currency_code=currency, exchange_rate_record_id=str(record.pk) if record else None)
        self.assertEqual(created.status_code, 201, created.data)
        response = self.client.post(f"/api/v1/sales-orders/{created.data['data']['id']}/confirm/", {}, format='json', HTTP_IF_MATCH=created['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def payload(self, source, **changes):
        data = {
            'task_number': 'HT26301', 'request_key': str(uuid4()),
            'delivery_batch_line_id': source['delivery_batches'][0]['lines'][0]['id'], 'quantity': 10,
            'follower_ids': [str(self.employee.pk)], 'delivery_date': (timezone.localdate() + timedelta(days=8)).isoformat(),
            'includes_tax': True, 'tax_rate': 5, 'order_tolerance_percent': '4.00',
            'is_repeat_order': True, 'delivery_method': 'SINGLE',
        }
        data.update(changes)
        return data

    def test_source_uses_independent_followers_and_writes_delivery_atomically(self):
        from ..models import ProductionTask
        source = self.source()
        payload = self.payload(source)
        created = self.client.post('/api/v1/production-tasks/create-from-sales-order/', payload, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        task = ProductionTask.objects.get(pk=created.data['data']['id'])
        self.assertEqual(list(task.followers.all()), [self.employee])
        self.assertEqual(task.tax_rate, 5)
        self.assertTrue(task.is_repeat_order)
        self.assertEqual(str(task.order_tolerance_percent), '4.00')
        self.assertEqual(task.delivery_date, task.sales_order_delivery_batch.planned_delivery_date)
        retry = self.client.post('/api/v1/production-tasks/create-from-sales-order/', {**payload, 'tax_rate': 7}, format='json')
        self.assertEqual(retry.status_code, 409, retry.data)

    def test_source_detail_resolves_units_and_preserves_prices(self):
        source = self.source()
        response = self.client.get('/api/v1/production-tasks/sales-order-sources/', {'sales_order_id': source['id']})
        self.assertEqual(response.status_code, 200, response.data)
        line = response.data['data']['lines'][0]
        self.assertEqual(line['unit_name'], self.product.unit.unit_name)
        self.assertEqual(str(line['unit_id']), str(self.product.unit_id))
        self.assertEqual(Decimal(line['unit_price']), Decimal('20'))
        self.assertEqual(Decimal(line['line_total']), Decimal('200'))
        self.assertEqual(response.data['data']['production_exchange_rate']['rate'], '1.00000000')

    def test_foreign_sales_price_is_frozen_before_partial_production_creation(self):
        foreign = Currency.objects.exclude(code='CNY').filter(status='ACTIVE', archived_at__isnull=True).first()
        cny = Currency.objects.get(code='CNY')
        record = ExchangeRate.objects.create(base_currency=foreign, quote_currency=cny, rate='0.00012345', effective_date=timezone.localdate(), source_name='人工维护', source_version='v1')
        source = self.source(foreign.code)
        preview = self.client.get('/api/v1/production-tasks/sales-order-sources/', {'sales_order_id': source['id']}).data['data']
        self.assertEqual(preview['production_exchange_rate']['record_id'], str(record.pk))
        record.status = 'INACTIVE'
        record.save()
        ExchangeRate.objects.create(base_currency=foreign, quote_currency=cny, rate='9', effective_date=timezone.localdate(), source_name='更新后')
        payload = self.payload(source, quantity=3)
        response = self.client.post('/api/v1/production-tasks/create-from-sales-order/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        product = response.data['data']['products'][0]
        self.assertEqual(product['currency_code'], 'CNY')
        self.assertEqual(Decimal(product['exchange_rate']), Decimal('1'))
        self.assertEqual(product['exchange_rate_snapshot']['source_sales_exchange_rate']['source_version'], 'v1')
        self.assertEqual(Decimal(product['unit_price_base']), Decimal('0.0025'))
        self.assertEqual(Decimal(product['unit_price']), Decimal('0.0025'))
        self.assertEqual(Decimal(product['total_amount']), Decimal('0.0075'))
        retried = self.client.post('/api/v1/production-tasks/create-from-sales-order/', payload, format='json')
        self.assertEqual(retried.status_code, 201, retried.data)
        self.assertEqual(retried.data['data']['id'], response.data['data']['id'])

    def test_legacy_source_without_frozen_cny_is_rejected(self):
        from apps.sales_orders.models import SalesOrder
        source = self.source()
        self.assertIn('total_amount_cny', source)
        SalesOrder.objects.filter(pk=source['id']).update(total_amount_cny=None, exchange_rate_snapshot={})
        response = self.client.post('/api/v1/production-tasks/create-from-sales-order/', self.payload(source), format='json')
        self.assertEqual(response.status_code, 400, response.data)

    def test_source_summary_shows_names_and_specification_separately(self):
        from apps.sales_orders.models import SalesOrderLine
        source = self.source()
        SalesOrderLine.objects.filter(pk=source['lines'][0]['id']).update(
            customer_product_name_snapshot='客户椅子名称',
            customer_specification_snapshot='45*52*47；颜色：酒红色；材质：尼龙',
            customer_color_snapshot='酒红色', material_snapshot='尼龙',
        )
        summary = self.client.get('/api/v1/production-tasks/sales-order-sources/').data['data'][0]
        self.assertIn('product_names', summary)
        self.assertEqual(summary['product_names'], ['客户椅子名称'])
        detail = self.client.get('/api/v1/production-tasks/sales-order-sources/', {'sales_order_id': source['id']}).data['data']
        self.assertEqual(detail['lines'][0]['specification_display'], '45*52*47')
        self.assertEqual(SalesOrderLine.objects.get(pk=source['lines'][0]['id']).customer_specification_snapshot,
                         '45*52*47；颜色：酒红色；材质：尼龙')

    def test_source_color_cannot_be_replaced(self):
        from apps.reference_data.models import ProductColor
        source = self.source()
        color = ProductColor.objects.exclude(pk=source['lines'][0].get('product_color_id')).filter(status='ACTIVE').first()
        payload = self.payload(source, product_color_id=str(color.pk))
        response = self.client.post('/api/v1/production-tasks/create-from-sales-order/', payload, format='json')
        self.assertEqual(response.status_code, 400, response.data)
    def test_allocation_cannot_use_tolerance_and_idempotent_retry_matches(self):
        source = self.source()
        payload = self.payload(source, quantity=11)
        rejected = self.client.post('/api/v1/production-tasks/create-from-sales-order/', payload, format='json')
        self.assertEqual(rejected.status_code, 400, rejected.data)
        payload['quantity'] = 10
        created = self.client.post('/api/v1/production-tasks/create-from-sales-order/', payload, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        retried = self.client.post('/api/v1/production-tasks/create-from-sales-order/', payload, format='json')
        self.assertEqual(retried.status_code, 201, retried.data)
        self.assertEqual(created.data['data']['id'], retried.data['data']['id'])

    def test_creation_failure_rolls_back_source_delivery_date(self):
        from unittest.mock import patch
        from apps.sales_orders.models import SalesOrderDeliveryBatch
        source = self.source()
        batch = SalesOrderDeliveryBatch.objects.get(pk=source['delivery_batches'][0]['id'])
        before = batch.planned_delivery_date
        with patch('apps.production_tasks.services.write_audit_log', side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):
                self.client.post('/api/v1/production-tasks/create-from-sales-order/', self.payload(source), format='json')
        batch.refresh_from_db()
        self.assertEqual(batch.planned_delivery_date, before)

    def test_inactive_production_follower_is_rejected(self):
        source = self.source()
        payload = self.payload(source)
        self.employee.status = 'INACTIVE'
        self.employee.save()
        response = self.client.post('/api/v1/production-tasks/create-from-sales-order/', payload, format='json')
        self.assertIn(response.status_code, [400, 403], response.data)


class ProductionOnlyOptionsTests(APITestCase):
    def test_production_user_reads_product_categories_units_without_product_permission(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from apps.organizations.models import Employee
        from apps.products.models import ProductInformation
        user = get_user_model().objects.create_user(username="production_options_only")
        Employee.objects.create(user=user, employee_code="PRODUCTION_OPTIONS_ONLY", display_name="生产选项")
        user.user_permissions.set(Permission.objects.filter(content_type__app_label="production_tasks", codename__in=["add_productiontask", "view_productiontask"]))
        self.client.force_authenticate(user)
        self.assertFalse(user.has_perm("products.view_productinformation"))
        response = self.client.get('/api/v1/production-tasks/options/')
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data['data']
        product = ProductInformation.objects.filter(status='ACTIVE', archived_at__isnull=True).select_related('unit').first()
        option = next(p for p in data['products'] if p['id'] == str(product.pk))
        self.assertEqual(option['category_id'], str(product.category_id))
        self.assertEqual(option['unit_code'], product.unit.unit_code)
        self.assertEqual(option['unit_name'], product.unit.unit_name)
        self.assertIn({'id': str(product.category_id), 'category_name': product.category.category_name}, data['categories'])
        self.assertNotIn('customer_name', option)

class ProductionOptionsShapeTests(SimpleTestCase):
    def test_full_options_exposes_categories_without_extra_module_permission(self):
        from unittest.mock import MagicMock, patch
        from rest_framework.test import APIRequestFactory
        from ..api.views import ProductionTaskViewSet
        request = APIRequestFactory().get('/api/v1/production-tasks/options/')
        request.query_params = {}
        names = ['Employee', 'ProductInformation', 'Currency', 'ProductionUnit', 'ProductColor', 'ProductCategory']
        replacements = {name: MagicMock() for name in names}
        with patch.multiple('apps.production_tasks.api.views', **replacements), patch.object(ProductionTaskViewSet, '_customer_references', return_value=MagicMock()), patch('apps.production_tasks.api.views.accessible_production_tasks', return_value=MagicMock()), patch('apps.production_tasks.api.views.load_sampling_detail_template', return_value=[]):
            response = ProductionTaskViewSet().options(request)
        self.assertIn('categories', response.data['data'])
