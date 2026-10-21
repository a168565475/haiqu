"""打样管材：需求支数、采购根米、合格入库支数回写及供应商正式输出。"""
from copy import deepcopy
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
import uuid

from django.contrib.auth.models import Permission
from django.middleware.csrf import _get_new_csrf_string
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from apps.reference_data.models import ProductionUnit, ProductCategory
from apps.inventory.models import MaterialInboundLine, MaterialStockBalance, MaterialStockMovement
from apps.samples.models import SampleMaterialArrival, SampleMaterialProcurementRequest, SampleRequest
from apps.samples.material_arrival_services import receive_material_arrival, material_progress
from apps.samples.tests import test_material_api as material_fixture
from apps.procurement.models import PurchaseOrder, PurchaseOrderLine
from apps.procurement.tests import test_sample_purchase_api as sample_fixture
from apps.procurement.tests import test_pipe_purchase_flow as pipe_fixture


class SamplePipeFlowTests(APITestCase):
    receive = pipe_fixture.PipePurchaseFlowTests.receive
    receive_all = sample_fixture.SamplePurchaseApiTests.receive_all
    quality = pipe_fixture.PipePurchaseFlowTests.quality

    def setUp(self):
        sample_fixture.SamplePurchaseApiTests.setUp(self)
        self.raw_material.category = ProductCategory.objects.get(category_name='管材')
        root, _ = ProductionUnit.objects.get_or_create(unit_name='根', defaults={'unit_code': 'S5_SAMPLE_ROOT'})
        self.raw_material.unit = root
        self.raw_material.save(update_fields=['unit', 'category'])
        self.demand.update(category='tube', name=self.raw_material.material_name,
                           specification=self.raw_material.specification, material=self.raw_material.material,
                           rawMaterialId=str(self.raw_material.pk), cuttingLengthMm='500', piecesPerBar='6',
                           quantity='20', supplyQuantity='2', shortageQuantity='18', unitLabel='支')
        self.procurement.lines = [self.demand]
        self.procurement.save()
        record = self.procurement.material_request
        record.draft = {'lines': [self.demand], 'notes': ''}
        record.warehouse_draft = {'lines': [{'key': self.key, 'supplyQuantity': '2'}], 'notes': ''}
        record.save()

    def purchase_payload(self):
        source = self.client.get(self.root + 'source/', {'sample_procurement_request_id': str(self.procurement.pk)})
        self.assertEqual(source.status_code, 200, source.data)
        data = source.data['data']
        return {'source_type': 'SAMPLE', 'sample_procurement_request_id': str(self.procurement.pk),
                'source_revision': data['source_revision'], 'currency_id': str(self.currency.pk), 'is_mailed': False,
                'lines': [{'sample_line_key': self.key, 'supplier_id': str(self.supplier.pk),
                           'delivery_date': timezone.localdate().isoformat(), 'actual_bar_count': 4, 'unit_price': '2'}]}

    def create_order(self):
        result = self.client.post(self.root, self.purchase_payload(), format='json')
        self.assertEqual(result.status_code, 201, result.data)
        self.order = PurchaseOrder.objects.get(pk=result.data['data']['id'])
        self.purchase_line = self.order.lines.get()
        return result

    def generate_sheet(self):
        self.create_order()
        order_url = self.root + str(self.order.pk) + '/'
        confirmed = self.client.post(order_url + 'confirm/', {}, format='json')
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        options = self.client.get(order_url + 'sheet-options/').data['data']
        generated = self.client.post(order_url + 'generate-sheets/', {'assignments': [
            {'supplier_id': str(self.supplier.pk), 'template_version_id': str(options['templates'][0]['version_id'])}]}, format='json')
        self.assertEqual(generated.status_code, 201, generated.data)
        return '/api/v1/supplier-purchase-sheets/' + generated.data['data'][0]['id'] + '/'

    def purchasing(self):
        self.create_order()
        self.order.status = 'PURCHASING'
        self.order.save(update_fields=['status'])

    def test_source_uses_shortage_pieces_and_server_computes_amount(self):
        self.create_order()
        line = self.purchase_line
        self.assertIsNone(line.bom_line_id)
        self.assertEqual(line.calculation_snapshot['demand_pieces'], 18)
        self.assertEqual((line.suggested_bar_count, line.actual_bar_count), (4, 4))
        self.assertEqual((line.raw_bar_length_m, line.actual_purchase_quantity, line.amount),
                         (Decimal('3.05'), Decimal('12.20'), Decimal('24.40')))
        self.assertEqual((line.sample_demand_quantity, line.sample_supply_quantity), (20, 2))
        self.assertEqual(line.source_unit_text, '米')

    def test_old_or_invalid_parameters_block_without_creating_order(self):
        for field, value in [('cuttingLengthMm', ''), ('piecesPerBar', '1.5'), ('unitLabel', '米'),
                             ('rawMaterialId', str(uuid.uuid4())), ('shortageQuantity', '19')]:
            row = {**self.demand, field: value}
            self.procurement.lines = [row]
            self.procurement.save()
            source = self.client.get(self.root + 'source/', {'sample_procurement_request_id': str(self.procurement.pk)})
            self.assertFalse(source.data['data']['can_create'], source.data)
        self.assertFalse(PurchaseOrder.objects.filter(sample_procurement_request=self.procurement).exists())

    def test_changed_source_and_fractional_roots_rollback(self):
        payload = self.purchase_payload()
        payload['lines'][0]['actual_bar_count'] = '1.5'
        self.assertEqual(self.client.post(self.root, payload, format='json').status_code, 400)
        self.procurement.lines[0]['cuttingLengthMm'] = '600'
        self.procurement.save()
        payload['lines'][0]['actual_bar_count'] = 4
        self.assertEqual(self.client.post(self.root, payload, format='json').status_code, 409)

    def test_changed_roots_without_reason_uses_computed_meters(self):
        payload = self.purchase_payload()
        payload['lines'][0]['actual_bar_count'] = 5
        result = self.client.post(self.root, payload, format='json')
        self.assertEqual(result.status_code, 201, result.data)
        line = result.data['data']['lines'][0]
        self.assertEqual(line['quantity_difference_reason'], '')
        self.assertEqual(Decimal(line['actual_purchase_quantity']), Decimal('15.25'))

    def test_confirmation_rejects_changed_sample_parameters(self):
        self.create_order()
        self.procurement.lines[0]['cuttingLengthMm'] = '600'
        self.procurement.save()
        result = self.client.post(self.root + str(self.order.pk) + '/confirm/', {}, format='json')
        self.assertEqual(result.status_code, 409, result.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'DRAFT')

    def test_historical_pending_batches_replay_and_finished_sample_remain_consistent(self):
        from apps.inventory.tests.test_sample_receiving import legacy_sample_receipt
        self.purchasing()
        # 变更前已收货的三批待检记录仍可逐批完成原品质流程。
        first = legacy_sample_receipt(self, '6.10', bars=2)
        second = legacy_sample_receipt(self, '3.05', bars=1)
        third = legacy_sample_receipt(self, '3.05', bars=1)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertFalse(SampleMaterialArrival.objects.exists())
        result = self.quality(first)
        self.assertEqual(result.status_code, 200, result.data)
        self.sample.refresh_from_db()
        # 新流程到货验收完成后进入一次性领料，不再停留在采购中。
        self.assertEqual(self.sample.status, 'MATERIAL_ISSUE_PENDING')
        self.assertEqual(SampleMaterialArrival.objects.get().accepted_quantity, 12)
        self.assertEqual(Decimal(material_progress(self.sample)['lines'][0]['remainingQuantity']), 6)
        line = MaterialInboundLine.objects.get(pk=first.data['data']['lines'][0]['id'])
        request = SimpleNamespace(user=self.user, employee=self.employee, META={})
        for _ in range(2):
            receive_material_arrival(procurement_request_id=self.procurement.pk, line_key=self.key,
                                     inbound_line_id=line.pk, request=request)
        self.assertEqual(SampleMaterialArrival.objects.count(), 1)
        self.assertEqual(self.quality(second).status_code, 200)
        self.sample.refresh_from_db()
        # 到货只解除采购等待；还需样品部一次性领料后才进入金工。
        self.assertEqual(self.sample.status, 'MATERIAL_ISSUE_PENDING')
        self.sample.status = 'FINISHED'
        self.sample.save(update_fields=['status'])
        self.assertEqual(self.quality(third).status_code, 200)
        self.sample.refresh_from_db()
        self.assertEqual(self.sample.status, 'FINISHED')
        self.assertEqual(sum(SampleMaterialArrival.objects.values_list('accepted_quantity', flat=True)), 24)
        self.assertEqual(sum(MaterialStockBalance.objects.values_list('quantity', flat=True)), 4)
        self.assertEqual(sum(MaterialStockBalance.objects.values_list('meter_quantity', flat=True)), Decimal('12.20'))
        self.assertEqual(MaterialStockMovement.objects.count(), 3)

    def test_historical_quality_rejected_roots_do_not_count_as_arrived_pieces(self):
        from apps.inventory.tests.test_sample_receiving import legacy_sample_receipt
        self.purchasing()
        first = legacy_sample_receipt(self, '6.10', bars=2)
        result = self.quality(first, 1)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(SampleMaterialArrival.objects.get().accepted_quantity, 6)
        self.assertEqual(MaterialStockBalance.objects.get().meter_quantity, Decimal('3.05'))

    def test_material_rename_after_purchase_keeps_frozen_arrival_and_replay(self):
        self.purchasing()
        self.raw_material.material_name = '采购后改名'
        self.raw_material.save(update_fields=['material_name'])
        received = self.receive_all()
        self.assertEqual(received.status_code, 201, received.data)
        line_id = received.data['data']['lines'][0]['id']
        receive_material_arrival(procurement_request_id=self.procurement.pk, line_key=self.key, inbound_line_id=line_id,
                                 request=SimpleNamespace(user=self.user, employee=self.employee, META={}))
        self.assertEqual(SampleMaterialArrival.objects.get().accepted_quantity, 24)
        self.assertEqual(MaterialStockMovement.objects.count(), 1)

    def test_return_completed_then_replenished_roots_advance_only_accepted_pieces(self):
        from apps.procurement.models import PurchaseReturn
        from apps.inventory.tests.test_sample_receiving import legacy_sample_receipt
        self.purchasing()
        first = legacy_sample_receipt(self, '12.20', bars=4)
        self.assertEqual(self.quality(first, 2).status_code, 200)
        self.sample.refresh_from_db()
        # 新流程到货验收完成后进入一次性领料，不再停留在采购中。
        self.assertEqual(self.sample.status, 'MATERIAL_ISSUE_PENDING')
        self.assertEqual(self.receive_all().status_code, 409)
        returned = PurchaseReturn.objects.get(purchase_order=self.order)
        url = f'/api/v1/purchase-returns/{returned.pk}/'
        detail = self.client.get(url)
        confirmed = self.client.post(url + 'confirm/', {}, format='json', HTTP_IF_MATCH=detail['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        completed = self.client.post(url + 'complete/', {}, format='json', HTTP_IF_MATCH=confirmed['ETag'])
        self.assertEqual(completed.status_code, 200, completed.data)
        second = self.receive_all()
        self.assertEqual(second.status_code, 201, second.data)
        self.sample.refresh_from_db()
        # 到货只解除采购等待；还需样品部一次性领料后才进入金工。
        self.assertEqual(self.sample.status, 'MATERIAL_ISSUE_PENDING')
        self.assertEqual(sum(SampleMaterialArrival.objects.values_list('accepted_quantity', flat=True)), 24)

    def test_formal_publish_pdf_and_xlsx_use_same_root_meter_snapshot(self):
        from openpyxl import load_workbook
        url = self.generate_sheet()
        detail = self.client.get(url)
        row = detail.data['data']['content_snapshot']['lines'][0]
        self.assertEqual((row['actual_bar_count'], row['raw_bar_length_m'], row['actual_purchase_meters']), (4, '3.05', '12.20'))
        exported = self.client.get(url + 'download-xlsx/')
        self.assertEqual(exported.status_code, 200)
        binary = b''.join(exported.streaming_content) if exported.streaming else exported.content
        cells = '\n'.join(str(cell.value or '') for row in load_workbook(BytesIO(binary)).active for cell in row)
        self.assertIn('4 根 × 3.05 米/根 = 12.20 米', cells)
        self.assertIn('元/米', cells)
        published = self.client.post(url + 'publish/', {}, format='json', HTTP_IF_MATCH=detail['ETag'])
        self.assertEqual(published.status_code, 200, published.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'PURCHASING')
        pdf = self.client.get(url + 'preview-pdf/')
        self.assertEqual(pdf.status_code, 200)
        content = b''.join(pdf.streaming_content) if pdf.streaming else pdf.content
        self.assertTrue(content.startswith(b'%PDF'))


class SamplePipeMaterialApiTests(APITestCase):
    setUp = SamplePipeFlowTests.setUp
    def material_state(self):
        self.sample.status = 'MATERIALS_PENDING'
        self.sample.save(update_fields=['status'])
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='samples'))
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.material_url = f'/api/v1/sample-requests/{self.sample.pk}/materials/'
        return self.client.get(self.material_url)

    def test_material_submit_freezes_parameters_and_shortage(self):
        state = self.material_state()
        self.procurement.delete()
        draft = {'lines': [{**self.demand, 'name': '客户端伪造名称'}], 'notes': ''}
        result = self.client.put(self.material_url, {'draft': draft, 'submit': True}, format='json', HTTP_IF_MATCH=state['ETag'])
        self.assertEqual(result.status_code, 200, result.data)
        row = result.data['data']['draft']['lines'][0]
        self.assertEqual(row['name'], self.raw_material.material_name)
        self.assertEqual(row['unitLabel'], '支')
        self.assertEqual(row['pipeCalculation']['raw_bar_length_m'], '3.05')
        url = self.material_url.replace('/materials/', '/warehouse-review/')
        draft = {'lines': [{'key': self.key, 'supplyQuantity': '2.5'}], 'notes': ''}
        invalid = self.client.put(url, {'draft': draft, 'submit': True}, format='json', HTTP_IF_MATCH=result['ETag'])
        self.assertEqual(invalid.status_code, 400, invalid.data)
        draft['lines'][0]['supplyQuantity'] = '2'
        saved = self.client.put(url, {'draft': draft, 'submit': True}, format='json', HTTP_IF_MATCH=result['ETag'])
        self.assertEqual(saved.status_code, 200, saved.data)
        frozen = SampleMaterialProcurementRequest.objects.get(material_request__sample_request=self.sample).lines[0]
        self.assertEqual(frozen['shortageQuantity'], '18')
        self.assertEqual(frozen['piecesPerBar'], '6')

    def test_material_api_rejects_missing_parameters_and_bad_integer(self):
        state = self.material_state()
        for field, value in [('cuttingLengthMm', ''), ('piecesPerBar', '2.5'), ('quantity', '0'), ('rawMaterialId', None)]:
            result = self.client.put(self.material_url, {'draft': {'lines': [{**self.demand, field: value}], 'notes': ''},
                                     'submit': True}, format='json', HTTP_IF_MATCH=state['ETag'])
            self.assertEqual(result.status_code, 400, result.data)

    def test_material_session_csrf_and_permission(self):
        state = self.material_state()
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        payload = {'draft': {'lines': [self.demand], 'notes': ''}, 'submit': False}
        self.assertEqual(client.put(self.material_url, payload, format='json', HTTP_IF_MATCH=state['ETag']).status_code, 403)
        token = _get_new_csrf_string()
        client.cookies['csrftoken'] = token
        saved = client.put(self.material_url, payload, format='json', HTTP_IF_MATCH=state['ETag'], HTTP_X_CSRFTOKEN=token)
        self.assertEqual(saved.status_code, 200, saved.data)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='samples', codename='edit_sample_materials'))
        denied = client.put(self.material_url, payload, format='json', HTTP_IF_MATCH=saved['ETag'], HTTP_X_CSRFTOKEN=token)
        self.assertEqual(denied.status_code, 403, denied.data)
