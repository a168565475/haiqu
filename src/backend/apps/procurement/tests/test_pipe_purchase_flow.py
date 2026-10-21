"""S5 通过真实采购、到货与质检接口核对根米金额及库存。"""
from copy import deepcopy
from decimal import Decimal
import uuid
import threading
from datetime import timedelta
from django.utils import timezone

from django.db import IntegrityError, transaction
from django.db import connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from rest_framework.exceptions import ValidationError

from apps.boms.material_flow_calculations import pipe_plan
from apps.inventory.models import MaterialStockBalance, MaterialStockMovement
from apps.inventory.tests import test_inventory_api as inventory_fixture
from apps.reference_data.models import ProductionUnit
from apps.procurement.models import PurchaseReturnLine
from apps.procurement.pipe_purchase import pipe_source_snapshot, purchase_pipe_values, pipe_sheet_fields
from apps.procurement.purchase_sheet_services import normalize_sheet_content
from apps.procurement.tests import test_purchase_order_api as purchase_fixture


class PipePurchaseFlowTests(APITestCase):
    def setUp(self):
        inventory_fixture.MaterialInventoryApiTests.setUp(self)
        root, _ = ProductionUnit.objects.get_or_create(unit_name='根', defaults={'unit_code': 'S5_ROOT'})
        self.raw_material.unit = root
        self.raw_material.save(update_fields=['unit'])
        plan = pipe_plan(cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=6, order_quantity=10)
        for field in ('cutting_length_mm', 'pieces_per_product', 'pieces_per_bar', 'raw_bar_length_m', 'suggested_bar_count', 'suggested_purchase_meters'):
            setattr(self.bom_line, field, plan[field])
        self.bom_line.raw_values['pipe_plan_version'] = 3
        self.bom_line.save()
        self.bom_line.refresh_from_db()
        snapshot = pipe_source_snapshot(self.bom_line)
        for key, value in purchase_pipe_values(snapshot, {'actual_bar_count': 4}).items():
            setattr(self.purchase_line, key, value)
        self.purchase_line.actual_purchase_quantity = Decimal('12.20')
        self.purchase_line.required_quantity = Decimal('12.20')
        self.purchase_line.amount = Decimal('24.40')
        self.purchase_line.source_unit_text = '米'
        self.purchase_line.save()
        self.purchase_line.refresh_from_db()

    def receive(self, roots=2, remaining='12.2000', **extra):
        return self.client.post('/api/v1/material-inventory/receipts/', {
            'items': [{'purchase_order_line_id': str(self.purchase_line.pk), 'zone_id': self.zone_id,
                       'expected_remaining_quantity': remaining, 'received_bar_count': roots, **extra}],
        }, format='json')

    def quality(self, response, returned=0):
        data = response.data['data']
        return self.client.post(f"/api/v1/material-inventory/quality-batches/{data['id']}/confirm/", {
            'items': [{'line_id': line['id'], 'expected_received_quantity': line['received_quantity'],
                       'return_bar_count': returned, 'quality_remark': '按整根检验'} for line in data['lines']],
        }, format='json')

    def test_pending_receipt_does_not_credit_and_quality_creates_root_meter_balance(self):
        received = self.receive()
        self.assertEqual(received.status_code, 201, received.data)
        self.assertFalse(MaterialStockBalance.objects.filter(measurement_kind='PIPE').exists())
        result = self.quality(received, returned=1)
        self.assertEqual(result.status_code, 200, result.data)
        balance = MaterialStockBalance.objects.get(measurement_kind='PIPE')
        self.assertEqual((balance.quantity, balance.meter_quantity), (1, Decimal('3.05')))
        self.assertEqual(PurchaseReturnLine.objects.get().quantity, Decimal('3.05'))
        self.assertEqual(MaterialStockMovement.objects.filter(balance=balance).count(), 1)
        retried = self.quality(received, returned=1)
        self.assertIn(retried.status_code, [200, 409])
        self.assertEqual(MaterialStockMovement.objects.filter(balance=balance).count(), 1)

    def test_read_detail_exposes_stored_roots_and_preserves_meter_amounts(self):
        first = self.receive(2)
        self.assertEqual(first.status_code, 201, first.data)
        pending = self.receive(1, remaining='6.1000')
        self.assertEqual(pending.status_code, 201, pending.data)
        self.assertEqual(self.quality(first, returned=1).status_code, 200)
        response = self.client.get(f'/api/v1/purchase-orders/{self.order.pk}/details/')
        self.assertEqual(response.status_code, 200, response.data)
        line = response.data['data']['lines'][0]
        self.assertEqual((line['received_bar_count'], line['accepted_bar_count'], line['return_bar_count']), (3, 1, 1))
        self.assertEqual(tuple(Decimal(line[key]) for key in ('received_quantity', 'accepted_quantity', 'return_quantity')),
                         (Decimal('9.15'), Decimal('3.05'), Decimal('3.05')))
        self.assertEqual(Decimal(line['amount']), Decimal('24.40'))
        self.assertTrue(all(row['measurement_kind'] == 'PIPE' for batch in response.data['data']['inbounds'] for row in batch['lines']))

    def test_receipt_rejects_half_root_missing_root_and_different_length(self):
        for roots, extra in [(1.5, {}), (0, {}), (None, {}), (2, {'raw_bar_length_m': '3.06'})]:
            result = self.receive(roots, **extra)
            self.assertEqual(result.status_code, 400, result.data)

    def test_receipt_computes_meters_even_if_client_supplies_false_total(self):
        result = self.receive(2, received_quantity='1.0000')
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(Decimal(result.data['data']['lines'][0]['received_quantity']), Decimal('6.10'))

    def test_over_receipt_and_stale_remaining_rollback(self):
        first = self.receive(2)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(self.receive(1).status_code, 409)
        self.assertEqual(self.receive(3, remaining='6.1000').status_code, 400)
        self.assertEqual(self.purchase_line.material_inbound_lines.count(), 1)

    def test_all_rejected_creates_return_without_available_stock(self):
        first = self.receive(2)
        result = self.quality(first, 2)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertFalse(MaterialStockBalance.objects.filter(measurement_kind='PIPE').exists())
        self.assertEqual(PurchaseReturnLine.objects.get().quantity, Decimal('6.10'))

    def test_two_confirmed_batches_are_summed_once_with_meters(self):
        first = self.receive(2)
        self.assertEqual(self.quality(first).status_code, 200)
        second = self.receive(2, remaining='6.1000')
        self.assertEqual(self.quality(second).status_code, 200)
        response = self.client.get('/api/v1/material-inventory/')
        self.assertEqual(response.status_code, 200, response.data)
        row = next(row for row in response.data['results'] if str(row['stock_item_id']) == str(self.raw_material.pk))
        self.assertEqual((row['inventory_quantity'], row['meter_quantity']), (4, Decimal('12.20')))

    def test_database_rejects_inconsistent_purchase_snapshot(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(self.purchase_line).objects.filter(pk=self.purchase_line.pk).update(actual_purchase_meters=99)

    def test_actual_roots_difference_allows_empty_reason_and_uses_meters(self):
        snapshot = self.purchase_line.calculation_snapshot
        values = purchase_pipe_values(snapshot, {'actual_bar_count': 5})
        self.assertEqual(values['quantity_difference_reason'], '')
        self.assertEqual(values['actual_purchase_meters'], Decimal('15.25'))
        values = purchase_pipe_values(snapshot, {'actual_bar_count': 5, 'quantity_difference_reason': '备用'})
        self.assertEqual(values['quantity_difference_reason'], '备用')
        self.assertEqual(values['actual_purchase_meters'], Decimal('15.25'))

    def test_pipe_sheet_rejects_weight_and_modified_quantity(self):
        from apps.procurement.pipe_purchase import normalize_pipe_sheet_line
        original = {**pipe_sheet_fields(self.purchase_line), 'quantity': '12.2000', 'unit': '米', 'unit_price': '2.0000'}
        with self.assertRaises(ValidationError):
            normalize_pipe_sheet_line(original, original, 'ACTUAL_WEIGHT')
        with self.assertRaises(ValidationError):
            normalize_pipe_sheet_line(original, {**original, 'quantity': '10'}, 'NORMAL')
        normalized = normalize_pipe_sheet_line(original, deepcopy(original), 'NORMAL')
        self.assertEqual(normalized['actual_bar_count'], 4)

    def test_no_permission_cannot_receive(self):
        self.user.user_permissions.clear()
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.receive().status_code, 403)

    def test_manual_inbound_retries_once_and_conflicting_length_rejected(self):
        payload = {'client_request_id': str(uuid.uuid4()), 'remark': '盘点新增整根管材', 'inbound_date': timezone.localdate().isoformat(),
                   'items': [{'raw_material_id': str(self.raw_material.pk), 'zone_id': self.zone_id,
                              'received_bar_count': 3, 'raw_bar_length_m': '3.05'}]}
        first = self.client.post('/api/v1/material-inventory/manual-receipts/', payload, format='json')
        self.assertEqual(first.status_code, 201, first.data)
        retry = self.client.post('/api/v1/material-inventory/manual-receipts/', payload, format='json')
        self.assertIn(retry.status_code, [200, 201], retry.data)
        self.assertEqual(first.data['data']['id'], retry.data['data']['id'])
        self.assertEqual(MaterialStockMovement.objects.count(), 1)
        payload['items'][0]['raw_bar_length_m'] = '3.06'
        self.assertEqual(self.client.post('/api/v1/material-inventory/manual-receipts/', payload, format='json').status_code, 409)

    def test_confirmed_purchase_receives_original_snapshot_after_bom_changes(self):
        self.bom_line.cutting_length_mm = 501
        self.bom_line.save(update_fields=['cutting_length_mm'])
        received = self.receive(2)
        self.assertEqual(received.status_code, 201, received.data)
        self.assertEqual(received.data['data']['lines'][0]['raw_bar_length_m'], '3.05')


class PipePurchaseOrderApiTests(APITestCase):
    make_task = purchase_fixture.PurchaseOrderApiTests.make_task
    make_product_line = purchase_fixture.PurchaseOrderApiTests.make_product_line
    make_bom = purchase_fixture.PurchaseOrderApiTests.make_bom
    get_source = purchase_fixture.PurchaseOrderApiTests.get_source
    create_payload = staticmethod(purchase_fixture.PurchaseOrderApiTests.create_payload)

    def setUp(self):
        from apps.reference_data.models import ProductCategory
        purchase_fixture.PurchaseOrderApiTests.setUp(self)
        root, _ = ProductionUnit.objects.get_or_create(unit_name='根', defaults={'unit_code': 'S5_PO_ROOT'})
        self.inventory_material.unit = root
        self.inventory_material.category = ProductCategory.objects.get(category_name='管材', item_type='MATERIAL')
        self.inventory_material.item_type = 'MATERIAL'
        self.inventory_material.save()
        self.task = self.make_task('S5')
        product = self.make_product_line(self.task, quantity=1000)
        self.bom, self.line = self.make_bom(product)
        plan = pipe_plan(cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=6, order_quantity=1000)
        for key in ('cutting_length_mm', 'pieces_per_product', 'pieces_per_bar', 'raw_bar_length_m', 'suggested_bar_count', 'suggested_purchase_meters'):
            setattr(self.line, key, plan[key])
        self.line.raw_values['pipe_plan_version'] = 3
        self.line.save()

    def create(self, **overrides):
        source = self.get_source(self.task)
        self.assertEqual(source.status_code, 200, source.data)
        values = {'actual_bar_count': 337, 'unit_price': '2.0000', 'supplier_id': str(self.supplier.pk),
                  'delivery_date': (timezone.localdate() + timedelta(days=10)).isoformat(), **overrides}
        payload = self.create_payload(self.task, source.data['data'], **values)
        payload['currency_id'] = str(self.cny.pk)
        return self.client.post('/api/v1/purchase-orders/', payload, format='json')

    def test_create_calculates_root_meter_and_price_then_confirms(self):
        created = self.create()
        self.assertEqual(created.status_code, 201, created.data)
        line = created.data['data']['lines'][0]
        self.assertEqual(line['actual_bar_count'], 337)
        self.assertEqual(Decimal(line['actual_purchase_quantity']), Decimal('1027.85'))
        self.assertEqual(Decimal(line['amount']), Decimal('2055.70'))
        order_id = created.data['data']['id']
        result = self.client.post(f'/api/v1/purchase-orders/{order_id}/confirm/', {}, format='json')
        self.assertEqual(result.status_code, 200, result.data)

    def test_new_pipe_source_has_no_percent_allowance_and_confirms_normal_purchase(self):
        source = self.get_source(self.task)
        self.assertEqual(source.status_code, 200, source.data)
        self.assertEqual(source.data['data']['lines'][0]['suggested_bar_count'], 334)
        created = self.create(actual_bar_count=334)
        self.assertEqual(created.status_code, 201, created.data)
        line = created.data['data']['lines'][0]
        self.assertEqual(line['calculation_snapshot']['schema_version'], 2)
        self.assertEqual(line['calculation_snapshot']['calculation_version'], 3)
        self.assertEqual(Decimal(line['amount']), Decimal('2037.40'))
        self.assertEqual(self.client.post(f"/api/v1/purchase-orders/{created.data['data']['id']}/confirm/", {}, format='json').status_code, 200)
        from types import SimpleNamespace
        from apps.outsourcing.dispatch_services import ready_snapshot
        from apps.outsourcing.material_flow import processing_basis
        self.line.refresh_from_db()
        snapshot = processing_basis(self.line)
        self.assertEqual(ready_snapshot(SimpleNamespace(conversion_snapshot=snapshot))['allowance_pieces'], 2004)

    def test_legacy_bom_and_purchase_source_keep_original_snapshot(self):
        self.line.raw_values.pop('pipe_plan_version')
        plan = pipe_plan(cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=6,
                         order_quantity=1000, calculation_version=2)
        self.line.suggested_bar_count = plan['suggested_bar_count']
        self.line.suggested_purchase_meters = plan['suggested_purchase_meters']
        self.line.save()
        self.line.refresh_from_db()
        before = deepcopy(pipe_source_snapshot(self.line))
        created = self.create()
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['data']['lines'][0]['calculation_snapshot'], before)
        self.assertEqual(before['allowance_pieces'], 2022)
        self.assertEqual(self.client.post(f"/api/v1/purchase-orders/{created.data['data']['id']}/confirm/", {}, format='json').status_code, 200)

    def test_changed_roots_without_reason_can_create_and_confirm(self):
        created = self.create(actual_bar_count=338)
        self.assertEqual(created.status_code, 201, created.data)
        line = created.data['data']['lines'][0]
        self.assertEqual(line['quantity_difference_reason'], '')
        self.assertEqual(Decimal(line['actual_purchase_quantity']), Decimal('1030.90'))
        self.assertEqual(Decimal(line['amount']), Decimal('2061.80'))
        confirmed = self.client.post(f"/api/v1/purchase-orders/{created.data['data']['id']}/confirm/", {}, format='json')
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

    def test_update_without_reason_keeps_saved_reason(self):
        created = self.create(quantity_difference_reason='备用采购')
        self.assertEqual(created.status_code, 201, created.data)
        order_id = created.data['data']['id']
        original_line = created.data['data']['lines'][0]
        line_payload = {
            'id': original_line['id'],
            'actual_bar_count': 338,
            'supplier_id': str(self.supplier.pk),
            'delivery_date': original_line['delivery_date'],
            'unit_price': '2.0000',
        }
        updated = self.client.patch(
            f'/api/v1/purchase-orders/{order_id}/',
            {'lines': [line_payload]}, format='json', HTTP_IF_MATCH=created.headers['ETag'],
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        line = updated.data['data']['lines'][0]
        self.assertEqual(line['actual_bar_count'], 338)
        self.assertEqual(line['quantity_difference_reason'], '备用采购')
        self.assertEqual(Decimal(line['actual_purchase_quantity']), Decimal('1030.90'))

        line_payload['quantity_difference_reason'] = '客户改量'
        updated_again = self.client.patch(
            f'/api/v1/purchase-orders/{order_id}/',
            {'lines': [line_payload]}, format='json', HTTP_IF_MATCH=updated.headers['ETag'],
        )
        self.assertEqual(updated_again.status_code, 200, updated_again.data)
        self.assertEqual(updated_again.data['data']['lines'][0]['quantity_difference_reason'], '客户改量')

    def test_fractional_roots_rejected(self):
        created = self.create(actual_bar_count='1.5')
        self.assertEqual(created.status_code, 400, created.data)

    def test_changed_bom_blocks_draft_confirmation(self):
        created = self.create()
        self.assertEqual(created.status_code, 201, created.data)
        self.line.cutting_length_mm = 501
        self.line.save()
        order_id = created.data['data']['id']
        result = self.client.post(f'/api/v1/purchase-orders/{order_id}/confirm/', {}, format='json')
        self.assertEqual(result.status_code, 409, result.data)

    def test_sheet_pdf_and_xlsx_share_root_meter_snapshot(self):
        from apps.procurement.models import PurchaseOrder, PurchaseContractTemplateVersion
        from apps.procurement.purchase_sheet_services import _default_content
        from apps.procurement.purchase_sheet_xlsx import _line_values
        created = self.create()
        self.assertEqual(created.status_code, 201, created.data)
        order = PurchaseOrder.objects.get(pk=created.data['data']['id'])
        version = PurchaseContractTemplateVersion.objects.exclude(content_config__settlement_mode='ACTUAL_WEIGHT').first()
        content = _default_content(order, self.supplier, list(order.lines.all()), version, 'S5-SHEET')
        line = content['lines'][0]
        self.assertEqual(line['actual_bar_count'], 337)
        self.assertEqual(line['actual_purchase_meters'], '1027.85')
        values = _line_values('GENERAL', line, 1, 'S5', False)
        self.assertIn('337 根 × 3.05 米/根 = 1027.85 米', values[2])
        from types import SimpleNamespace
        from apps.procurement.purchase_sheet_pdf import build_supplier_purchase_sheet_pdf
        empty_images = SimpleNamespace(select_related=lambda *args: SimpleNamespace(all=lambda: []))
        printable = SimpleNamespace(content_snapshot=content, sheet_number='S5-SHEET', version_number=1, line_images=empty_images)
        self.assertTrue(build_supplier_purchase_sheet_pdf(printable).startswith(b'%PDF'))
        normalized, _ = normalize_sheet_content(SimpleNamespace(content_snapshot=content, sheet_number='S5-SHEET'), content)
        self.assertEqual(normalized['lines'][0]['calculation_snapshot'], line['calculation_snapshot'])
        for key in ('quantity', 'unit', 'unit_price'):
            partial = deepcopy(content)
            del partial['lines'][0][key]
            saved, _ = normalize_sheet_content(SimpleNamespace(content_snapshot=content, sheet_number='S5-SHEET'), partial)
            self.assertEqual(saved['lines'][0][key], normalized['lines'][0][key])

    def test_legacy_pipe_sheet_cannot_bypass_publish_guard(self):
        from types import SimpleNamespace
        from apps.procurement.pipe_purchase import validate_pipe_sheet_source
        created = self.create()
        self.assertEqual(created.status_code, 201, created.data)
        fake_sheet = SimpleNamespace(purchase_order_id=created.data['data']['id'], supplier_id=self.supplier.pk,
                                     content_snapshot={'lines': [{'source_purchase_order_line_id': created.data['data']['lines'][0]['id'],
                                        'quantity': '337', 'unit': '根', 'unit_price': '2'}], 'settlement_mode': 'ACTUAL_WEIGHT'})
        with self.assertRaisesMessage(ValidationError, '旧单位'):
            validate_pipe_sheet_source(fake_sheet)


class PipeReceiptConcurrencyTests(TransactionTestCase):
    receive = PipePurchaseFlowTests.receive

    def setUp(self):
        PipePurchaseFlowTests.setUp(self)

    def test_manual_and_quality_with_shared_unit_and_zone_do_not_deadlock(self):
        received = self.receive(2)
        self.assertEqual(received.status_code, 201, received.data)
        batch = received.data['data']
        other = type(self.raw_material).objects.get(pk=self.raw_material.pk)
        other.pk = None
        other.material_number = 'S5-SECOND-PIPE'
        other.save()
        manual = {'client_request_id': str(uuid.uuid4()), 'inbound_date': timezone.localdate().isoformat(),
                  'remark': '同库区并发额外入库', 'items': [{'raw_material_id': str(other.pk), 'zone_id': self.zone_id,
                  'received_bar_count': 3, 'raw_bar_length_m': '3.05'}]}
        quality = {'items': [{'line_id': row['id'], 'expected_received_quantity': row['received_quantity'],
                             'return_bar_count': 0} for row in batch['lines']]}
        barrier = threading.Barrier(2)
        results = []

        def execute(url, payload):
            try:
                with connections['default'].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                client = APIClient()
                client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
                barrier.wait(timeout=8)
                response = client.post(url, payload, format='json')
                results.append((response.status_code, response.data))
            except Exception as error:
                results.append((0, repr(error)))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=execute, args=(url, payload)) for url, payload in [
            ('/api/v1/material-inventory/manual-receipts/', manual),
            (f"/api/v1/material-inventory/quality-batches/{batch['id']}/confirm/", quality),
        ]]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertCountEqual([item[0] for item in results], [200, 201], results)
        self.assertEqual(MaterialStockBalance.objects.filter(measurement_kind='PIPE').count(), 2)


class NonPipeInventoryRegressionTests(inventory_fixture.MaterialInventoryApiTests):
    """通用收货测试使用非管材，保留小数单位路径的原有行为。"""
    def setUp(self):
        from apps.reference_data.models import ProductCategory
        super().setUp()
        self.raw_material.category = ProductCategory.objects.get(category_name='五金', item_type='MATERIAL')
        self.raw_material.save(update_fields=['category'])
        self.bom_line.section.section_type = 'ACCESSORY'
        self.bom_line.section.save(update_fields=['section_type'])
        self.purchase_line.section_type_snapshot = 'ACCESSORY'
        self.purchase_line.save(update_fields=['section_type_snapshot'])
