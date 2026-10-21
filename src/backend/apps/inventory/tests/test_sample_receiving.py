"""样品全部入库 API：真实测试库中的数量、权限、事务和重复提交边界。"""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.middleware.csrf import _get_new_csrf_string
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase, APIClient

from apps.audit.models import AuditLog
from apps.inventory.models import MaterialInbound, MaterialInboundLine, MaterialStockBalance, PublicStockBalance, PublicStockMovement
from apps.procurement.models import PurchaseOrder
from apps.organizations.models import Employee
from apps.procurement.tests import test_sample_purchase_api as purchase_fixture
from apps.procurement.tests import test_sample_pipe_flow as pipe_fixture
from apps.samples.material_arrival_services import material_progress
from apps.samples.models import SampleMaterialArrival, SampleMaterialIssue


def legacy_sample_receipt(test, quantity, expected=None, *, bars=None):
    """仅建立变更前已经存在的待检批次；生产 API 不再新建样品待检单。"""
    from apps.inventory.pipe_receipts import receipt_pipe_values
    from apps.inventory.public_stock_mode import new_stock_mode
    from apps.inventory.services import _freeze_public_pipe_values

    line = test.purchase_line
    inbound = MaterialInbound.objects.create(purchase_order=line.purchase_order,
        inbound_number='LEGACY-' + uuid.uuid4().hex[:16], inbound_date=timezone.localdate(),
        stock_mode=new_stock_mode(), status='PENDING_QUALITY', received_by_employee=test.employee)
    values = {'received_quantity': Decimal(quantity)}
    if bars is not None:
        values['received_bar_count'] = bars
    pipe = _freeze_public_pipe_values(receipt_pipe_values(values, purchase_line=line), inbound.stock_mode)
    snapshots = {field: getattr(line, field) for field in [
        'supplier_number_snapshot', 'supplier_name_snapshot', 'bom_number_snapshot', 'product_name_snapshot',
        'section_type_snapshot', 'section_title_snapshot', 'category_snapshot', 'material_snapshot',
        'part_name_snapshot', 'specification_snapshot', 'raw_material_snapshot', 'material_attributes_snapshot']}
    created = MaterialInboundLine.objects.create(inbound=inbound, purchase_order_line=line,
        zone_id=test.zone_id, received_quantity=values['received_quantity'], accepted_quantity=values['received_quantity'],
        purchase_order_number_snapshot=line.purchase_order.order_number, source_unit_text_snapshot=line.source_unit_text,
        purchased_quantity_snapshot=line.actual_purchase_quantity, **snapshots, **pipe)
    return SimpleNamespace(status_code=201, data={'data': {'id': str(inbound.pk), 'lines': [{
        'id': str(created.pk), 'received_quantity': str(created.received_quantity),
        'received_bar_count': created.received_bar_count}]}})


class SampleReceivingHelpers:
    purchase_payload = purchase_fixture.SamplePurchaseApiTests.purchase_payload
    create_order = purchase_fixture.SamplePurchaseApiTests.create_order
    url = '/api/v1/material-inventory/sample-receivings/'

    def prepare(self):
        self.create_order()
        self.order = PurchaseOrder.objects.get(pk=self.sample_order_id)
        self.order.status = 'PURCHASING'
        self.order.save(update_fields=['status', 'updated_at'])

    def receipt_payload(self):
        return {'purchase_order_id': str(self.order.pk), 'client_request_id': str(uuid.uuid4()),
                'items': [{'purchase_order_line_id': str(self.purchase_line.pk), 'zone_id': self.zone_id}]}

    def receipt_etag(self):
        response = self.client.get('/api/v1/material-inventory/eligible-lines/', {'purchase_order_id': str(self.order.pk)})
        self.assertEqual(response.status_code, 200, response.data)
        return response['ETag']

    def receive_all(self, payload=None, etag=None):
        return self.client.post(self.url, payload or self.receipt_payload(), format='json',
                                HTTP_IF_MATCH=etag or self.receipt_etag())


class SampleReceivingApiTests(SampleReceivingHelpers, APITestCase):
    def setUp(self):
        purchase_fixture.SamplePurchaseApiTests.setUp(self)
        self.prepare()

    def test_full_receipt_uses_frozen_quantity_without_quality_permission(self):
        self.user.user_permissions.remove(*Permission.objects.filter(content_type__app_label='samples'))
        self.user.user_permissions.remove(Permission.objects.get(codename='quality_confirm_material'))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        result = self.receive_all()
        self.assertEqual(result.status_code, 201, result.data)
        inbound = MaterialInbound.objects.get(pk=result.data['data']['id'])
        self.assertEqual(inbound.status, 'CONFIRMED')
        self.assertIsNone(inbound.quality_confirmed_at)
        self.assertIsNone(inbound.quality_confirmed_by_employee_id)
        self.assertEqual(inbound.lines.get().accepted_quantity, Decimal('4'))
        self.assertEqual(MaterialStockBalance.objects.get(raw_material=self.raw_material).quantity, 4)
        self.assertEqual(SampleMaterialArrival.objects.get().accepted_quantity, 4)
        self.assertTrue(AuditLog.objects.filter(object_id=inbound.pk, action='SAMPLE_DIRECT_CONFIRMED').exists())
        self.sample.refresh_from_db()
        row = material_progress(self.sample)['lines'][0]
        self.assertEqual(Decimal(row['procurementQuantity']), 4)
        self.assertEqual(Decimal(row['remainingQuantity']), 0)
        self.assertEqual(self.sample.status, 'MATERIAL_ISSUE_PENDING')

    def test_same_request_replay_and_new_request_never_duplicate_stock(self):
        payload, etag = self.receipt_payload(), self.receipt_etag()
        first = self.receive_all(payload, etag)
        self.assertEqual(first.status_code, 201, first.data)
        missing_header = self.client.post(self.url, payload, format='json')
        self.assertEqual(missing_header.status_code, 428, missing_header.data)
        replay = self.receive_all(payload, etag)
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(first.data, replay.data)
        self.assertEqual(self.receive_all().status_code, 409)
        changed = deepcopy(payload)
        changed['remark'] = 'different'
        self.assertEqual(self.receive_all(changed, etag).status_code, 409)
        self.assertEqual(MaterialInbound.objects.count(), 1)
        self.assertEqual(MaterialStockBalance.objects.get().quantity, 4)

    def test_pending_history_blocks_direct_receipt_and_still_can_be_quality_confirmed(self):
        legacy = legacy_sample_receipt(self, '2')
        old_etag = self.receipt_etag()
        self.assertEqual(self.receive_all().status_code, 409)
        self.assertFalse(MaterialStockBalance.objects.exists())
        quality = purchase_fixture.SamplePurchaseApiTests.confirm_quality(self, legacy)
        self.assertEqual(quality.status_code, 200, quality.data)
        self.assertEqual(self.receive_all(etag=old_etag).status_code, 412)
        current = self.receive_all()
        self.assertEqual(current.status_code, 201, current.data)
        self.assertEqual(current.data['data']['total_received_quantity'], '2.0000')
        self.assertEqual(MaterialStockBalance.objects.get().quantity, 4)

    def test_quantity_injection_missing_lines_old_endpoint_and_normal_order_rejected(self):
        payload = self.receipt_payload()
        payload['received_quantity'] = '1'
        invalid = self.receive_all(payload)
        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.assertFalse(MaterialInbound.objects.exists())
        payload = self.receipt_payload()
        payload['items'][0]['received_quantity'] = '1'
        self.assertEqual(self.receive_all(payload).status_code, 400)
        payload = self.receipt_payload()
        payload['items'].append(deepcopy(payload['items'][0]))
        self.assertEqual(self.receive_all(payload).status_code, 400)
        old = purchase_fixture.SamplePurchaseApiTests.payload(self, '2', '4')
        self.assertEqual(self.client.post('/api/v1/material-inventory/receivings/', old, format='json').status_code, 409)
        normal = PurchaseOrder.objects.get(source_type='PRODUCTION')
        payload = self.receipt_payload()
        payload['purchase_order_id'] = str(normal.pk)
        self.assertEqual(self.receive_all(payload).status_code, 400)
        self.assertFalse(MaterialInbound.objects.exists())

    def test_etag_session_csrf_and_receiving_permission_are_required(self):
        payload, etag = self.receipt_payload(), self.receipt_etag()
        self.assertEqual(self.client.post(self.url, payload, format='json').status_code, 428)
        self.order.save(update_fields=['updated_at'])
        self.assertEqual(self.receive_all(payload, etag).status_code, 412)
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, payload, format='json', HTTP_IF_MATCH=self.receipt_etag()).status_code, 403)
        token = _get_new_csrf_string()
        client.cookies['csrftoken'] = token
        current_etag = self.receipt_etag()
        self.user.user_permissions.remove(Permission.objects.get(codename='receive_material'))
        self.assertEqual(client.post(self.url, payload, format='json', HTTP_IF_MATCH=current_etag,
                                     HTTP_X_CSRFTOKEN=token).status_code, 403)
        self.assertFalse(MaterialInbound.objects.exists())
        self.user.user_permissions.add(Permission.objects.get(codename='receive_material'))
        allowed = client.post(self.url, payload, format='json', HTTP_IF_MATCH=current_etag, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(allowed.status_code, 201, allowed.data)

    def test_data_scope_and_inactive_zone_cannot_create_stock(self):
        from apps.inventory.models import WarehouseZone
        payload, etag = self.receipt_payload(), self.receipt_etag()
        outsider = get_user_model().objects.create_user(username='outside_direct_receipt')
        Employee.objects.create(user=outsider, employee_code='OUTSIDE_DIRECT', display_name='范围外仓库')
        outsider.user_permissions.set(Permission.objects.filter(content_type__app_label='inventory'))
        self.client.force_authenticate(outsider)
        self.assertEqual(self.receive_all(payload, etag).status_code, 404)
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        WarehouseZone.objects.filter(pk=self.zone_id).update(status='DISABLED')
        self.assertEqual(self.receive_all(payload, etag).status_code, 409)
        self.assertFalse(MaterialInbound.objects.exists())

    def test_failed_arrival_rolls_back_receipt_stock_and_audit(self):
        with patch('apps.samples.material_arrival_services.receive_material_arrival', side_effect=ValidationError('到货衔接失败')):
            failed = self.receive_all()
        self.assertEqual(failed.status_code, 400, failed.data)
        self.assertFalse(MaterialInbound.objects.exists())
        self.assertFalse(MaterialStockBalance.objects.exists())
        self.assertFalse(SampleMaterialArrival.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action='SAMPLE_DIRECT_CONFIRMED').exists())


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class SamplePublicPipeReceivingTests(SampleReceivingHelpers, APITestCase):
    def setUp(self):
        pipe_fixture.SamplePipeFlowTests.setUp(self)
        self.demand.pop('cuttingLengthMm')
        self.demand.pop('piecesPerBar')
        self.demand.update(pipeInputMode='TOTAL_METERS', quantity='8', supplyQuantity='0', shortageQuantity='8', unitLabel='米')
        self.procurement.lines = [self.demand]
        self.procurement.save(update_fields=['lines'])
        record = self.procurement.material_request
        record.draft = {'lines': [self.demand], 'notes': ''}
        record.warehouse_draft = {'lines': [{'key': self.key, 'supplyQuantity': '0'}], 'notes': ''}
        record.save(update_fields=['draft', 'warehouse_draft'])
        self.prepare()

    def purchase_payload(self):
        payload = purchase_fixture.SamplePurchaseApiTests.purchase_payload(self)
        payload['lines'][0].pop('actual_purchase_quantity')
        payload['lines'][0].update(actual_bar_count=2, raw_bar_length_m='6')
        return payload

    def test_purchase_two_six_meter_bars_credits_twelve_meters_without_quality(self):
        received = self.receive_all()
        self.assertEqual(received.status_code, 201, received.data)
        line = MaterialInboundLine.objects.get()
        self.assertEqual((line.accepted_bar_count, line.raw_bar_length_m, line.accepted_quantity), (2, Decimal('6'), Decimal('12')))
        balance = PublicStockBalance.objects.get(raw_material=self.raw_material, stock_kind='RAW_PIPE')
        self.assertEqual((balance.quantity, balance.meter_quantity), (2, Decimal('12')))
        self.assertEqual(PublicStockMovement.objects.count(), 1)
        self.assertFalse(MaterialStockBalance.objects.exists())
        self.assertEqual(SampleMaterialArrival.objects.get().accepted_quantity, 12)


class SampleReceivingAfterIssueTests(SampleReceivingHelpers, APITestCase):
    def setUp(self):
        purchase_fixture.SamplePurchaseApiTests.setUp(self)
        self.demand.update(quantity='6', supplyQuantity='2', shortageQuantity='4')
        self.procurement.lines = [self.demand]
        self.procurement.save(update_fields=['lines'])
        record = self.procurement.material_request
        record.draft = {'lines': [self.demand], 'notes': ''}
        record.warehouse_draft = {'lines': [{'key': self.key, 'supplyQuantity': '2'}], 'notes': ''}
        record.save(update_fields=['draft', 'warehouse_draft'])
        self.prepare()
        MaterialStockBalance.objects.create(raw_material=self.raw_material, unit=self.raw_material.unit,
            zone_id=self.zone_id, quality='AVAILABLE', quantity=2)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='samples'))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        path = f'/api/v1/sample-requests/{self.sample.pk}/material-issue/'
        current = self.client.get(path)
        self.assertEqual(current.status_code, 200, current.data)
        initiated = self.client.post(path + 'initiate/', {'client_request_id': str(uuid.uuid4())},
            format='json', HTTP_IF_MATCH=current['ETag'])
        self.assertEqual(initiated.status_code, 200, initiated.data)
        confirmed = self.client.post(path + 'confirm/', {'request_id': str(uuid.uuid4())},
            format='json', HTTP_IF_MATCH=initiated['ETag'])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

    def verify_later_receipt(self, stage):
        self.sample.refresh_from_db()
        self.assertEqual(self.sample.status, 'METALWORK_PENDING')
        if stage == 'FINISHED':
            # 后续生产阶段由生产模块测试；本用例只验证已结束样品的剩余采购衔接。
            self.sample.status = stage
            self.sample.save(update_fields=['status', 'updated_at'])
        received = self.receive_all()
        self.assertEqual(received.status_code, 201, received.data)
        self.sample.refresh_from_db()
        self.assertEqual(self.sample.status, stage)
        self.assertEqual(MaterialStockBalance.objects.get().quantity, 4)
        issue = SampleMaterialIssue.objects.get()
        self.assertEqual(issue.status, 'ISSUED')
        self.assertEqual(issue.lines.get().issued_quantity, 2)
        self.assertEqual(SampleMaterialArrival.objects.get().accepted_quantity, 4)

    def test_all_arriving_purchase_is_received_after_existing_materials_were_issued(self):
        self.verify_later_receipt('METALWORK_PENDING')

    def test_late_purchase_does_not_reopen_finished_sample_or_issue_again(self):
        self.verify_later_receipt('FINISHED')


class SampleReceivingConcurrencyTests(SampleReceivingHelpers, TransactionTestCase):
    # 保持迁移种子，并避免结束 flush 重发 post_migrate 干扰后续序列化回滚用例。
    serialized_rollback = True

    def setUp(self):
        purchase_fixture.SamplePurchaseApiTests.setUp(self)
        self.prepare()

    def test_simultaneous_same_request_records_one_receipt_and_one_stock_credit(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections, connection, connections

        payload, etag = self.receipt_payload(), self.receipt_etag()
        ready = Barrier(2)

        def submit():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
                ready.wait(timeout=10)
                response = client.post(self.url, payload, format='json', HTTP_IF_MATCH=etag)
                return response.status_code, response.data
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(sorted(code for code, _ in results), [200, 201], results)
        self.assertEqual(MaterialInbound.objects.count(), 1)
        self.assertEqual(SampleMaterialArrival.objects.count(), 1)
        self.assertEqual(MaterialStockBalance.objects.get().quantity, 4)
