import uuid
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.utils import timezone
from apps.material_issues.models import MaterialIssueLine, MetalProcessingSource
from apps.material_issues.processing_selectors import quantity_state
from ..models import InternalSemiFinishedReceipt, InternalSemiFinishedReceiptLine, PublicStockBalance, PublicStockMovement
from ..public_stock_services import debit_public_stock
from .test_public_stock_services import PublicStockFixture


# 本类验证旧加工来源额度入库；报工最小工序量的新口径由 test_tube_d1_receipts 覆盖。
@override_settings(TUBE_OUTSOURCING_ENABLED=False, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class InternalReceiptApiTests(PublicStockFixture, TestCase):
    url = '/api/v1/semi-finished-receipts/'

    def setUp(self):
        super().setUp()
        self.raw_material.color_snapshot = '本色'
        self.raw_material.save(update_fields=['color_snapshot'])
        self.bom_line.raw_values['source_raw_material_id'] = str(self.raw_material.pk)
        self.bom_line.specification = '20*28*0.8'
        self.bom_line.save()
        self.credit(200, identity=self.pipe(str(self.bom_line.raw_bar_length_m)))
        response = self.client.get('/api/v1/material-issues/requirements/',{
            'production_task_id':str(self.task.pk),'product_line_id':str(self.product_line.pk),'workshop_id':str(self.workshop.pk)})
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data['data']['blockers'],[],response.data)
        requirement = response.data['data']['items'][0]
        response = self.client.post('/api/v1/material-issues/',{
            'client_request_id':str(uuid.uuid4()),'schedule_product_id':str(self.schedule_product.pk),'plan_category':'METAL',
            'production_task_id':str(self.task.pk),'product_line_id':str(self.product_line.pk),'workshop_id':str(self.workshop.pk),
            'recipient_workshop_employee_id':str(self.recipient.pk),'issue_at':timezone.now().isoformat(),
            'lines':[{'requirement_id':requirement['requirement_id'],'requested_quantity':'1002'}]},format='json')
        self.assertEqual(response.status_code,201,response.data)
        issue_id = response.data['data']['id']
        for action in ['submit','confirm-issue']:
            detail = self.client.get(f'/api/v1/material-issues/{issue_id}/')
            response = self.client.post(f'/api/v1/material-issues/{issue_id}/{action}/',{'request_id':str(uuid.uuid4())},
                format='json',HTTP_IF_MATCH=detail.headers['ETag'])
            self.assertEqual(response.status_code,200,response.data)
        self.issue_line = MaterialIssueLine.objects.get(issue_id=issue_id)

    def preview(self):
        response = self.client.get(self.url+'preview/',{'schedule_product_id':str(self.schedule_product.pk),'plan_category':'METAL'})
        self.assertEqual(response.status_code,200,response.data)
        return response.data['data']

    def payload(self, quantity=100):
        return {'request_id':str(uuid.uuid4()),'schedule_product_id':str(self.schedule_product.pk),'plan_category':'METAL',
            'zone_id':str(self.semi_zone.pk),'receipt_date':str(timezone.localdate()),'remark':'开发测试入库',
            'lines':[{'bom_line_id':str(self.bom_line.pk),'quantity':str(quantity)}]}

    def receive(self, quantity=100, payload=None, etag=None):
        return self.client.post(self.url,payload or self.payload(quantity),format='json',HTTP_IF_MATCH=etag or self.preview()['etag'])

    def test_submit_is_pending_until_warehouse_confirmation(self):
        payload, etag = self.payload(100), self.preview()['etag']
        response = self.client.post(self.url, payload, format='json', HTTP_IF_MATCH=etag)
        self.assertEqual(response.status_code, 201, response.data)
        result = response.data['data']
        self.assertEqual(result['status'], 'PENDING')
        receipt = InternalSemiFinishedReceipt.objects.get(pk=result['receipt_id'])
        line = InternalSemiFinishedReceiptLine.objects.get(receipt=receipt)
        self.assertEqual(receipt.status, 'PENDING')
        self.assertIsNotNone(receipt.submitted_by_employee_id)
        self.assertIsNotNone(receipt.submitted_at)
        self.assertIsNone(receipt.confirmed_by_employee_id)
        self.assertIsNone(line.stock_movement_id)
        self.assertFalse(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').exists())

        confirmed = self.client.post(
            f'{self.url}{receipt.pk}/confirm/', {}, format='json',
            HTTP_IF_MATCH=etag,
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data['data']['status'], 'CONFIRMED')
        receipt.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(receipt.status, 'CONFIRMED')
        self.assertIsNotNone(receipt.confirmed_by_employee_id)
        self.assertIsNotNone(receipt.confirmed_at)
        self.assertIsNotNone(line.stock_movement_id)
        self.assertEqual(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').count(), 1)

    def test_receipt_credits_public_inventory_and_consumes_processing_quota(self):
        preview = self.preview()
        self.assertEqual(Decimal(preview['lines'][0]['can_receive']),1000)
        response = self.receive(400)
        self.assertEqual(response.status_code,201,response.data)
        line = InternalSemiFinishedReceiptLine.objects.get()
        self.assertRegex(line.receipt.receipt_number, rf'^BNRK{timezone.localdate():%y%m%d}[0-9]{{3,}}$')
        self.assertEqual((line.quantity,line.input_quantity,line.received_after),(400,400,400))
        self.assertEqual(line.stock_movement.balance.quantity,400)
        source = MetalProcessingSource.objects.get(issue_line=self.issue_line)
        self.assertEqual(source.internal_received_pieces,400)
        self.assertEqual(quantity_state(source,1002)['available_pieces'],0)
        # 厂内金工半成品尚未喷塑，库存身份不继承原料档案颜色。
        self.assertEqual(line.attribute_snapshot['color'],'')
        self.assertEqual(Decimal(self.preview()['lines'][0]['can_receive']),600)

    def test_retry_is_idempotent_and_changed_payload_conflicts(self):
        payload, etag = self.payload(), self.preview()['etag']
        self.assertEqual(self.receive(payload=payload,etag=etag).status_code,201)
        self.assertEqual(self.receive(payload=payload,etag=etag).status_code,200)
        payload['lines'][0]['quantity']='101'
        self.assertEqual(self.receive(payload=payload,etag=etag).status_code,409)
        self.assertEqual(InternalSemiFinishedReceipt.objects.count(),1)

    def test_stale_page_and_over_limit_do_not_credit(self):
        etag = self.preview()['etag']
        self.assertEqual(self.receive(1001).status_code,400)
        self.assertFalse(InternalSemiFinishedReceipt.objects.exists())
        self.assertEqual(self.receive(900).status_code,201)
        self.assertEqual(self.receive(100,etag=etag).status_code,412)

    def test_issue_out_does_not_reopen_receipt_quota(self):
        self.assertEqual(self.receive(1000).status_code,201)
        line = InternalSemiFinishedReceiptLine.objects.get()
        debit_public_stock(balance_id=line.stock_movement.balance_id,quantity=1000,**self.source())
        self.assertEqual(Decimal(self.preview()['lines'][0]['can_receive']),0)
        self.assertEqual(self.receive(1).status_code,400)

    def test_completed_parts_drive_plan_and_downstream_public_requirements(self):
        from apps.inventory.internal_receipt_progress import receipt_progress_for_plans
        from apps.material_issues.public_semi_requirements import build_public_semi_specs
        self.assertEqual(self.receive(1000).status_code,201)
        progress=receipt_progress_for_plans([self.schedule_product],'METAL')
        self.assertTrue(progress[str(self.schedule_product.pk)]['complete'])
        specs, blockers=build_public_semi_specs(self.task.pk,self.product_line.pk)
        self.assertEqual(blockers,[],blockers)
        self.assertEqual(len(specs),1)
        self.assertEqual(specs[0]['required_quantity'],1000)
        self.assertEqual(specs[0]['identity']['identity_key'],InternalSemiFinishedReceiptLine.objects.get().stock_movement.balance.identity_key)

    def test_changed_cutting_length_after_issue_requires_review(self):
        self.bom_line.cutting_length_mm=420; self.bom_line.save(update_fields=['cutting_length_mm'])
        response=self.client.get(self.url+'preview/',{'schedule_product_id':str(self.schedule_product.pk),'plan_category':'METAL'})
        self.assertEqual(response.status_code,409,response.data)

    def test_stock_credit_failure_rolls_back_header_and_source(self):
        with patch('apps.inventory.internal_receipt_services.credit_public_stock',side_effect=RuntimeError('模拟记账失败')):
            with self.assertRaises(RuntimeError):
                self.receive()
        self.assertFalse(InternalSemiFinishedReceipt.objects.exists())
        self.assertFalse(MetalProcessingSource.objects.filter(issue_line=self.issue_line).exists())

    def test_records_and_lazy_internal_source_details(self):
        self.assertEqual(self.receive().status_code,201)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code,200,response.data)
        row = response.data['data']['items'][0]
        self.assertEqual(row['source_display'],'厂内入库')
        self.assertNotIn('source_detail',row)
        detail = self.client.get(self.url+row['id']+'/')
        self.assertEqual(detail.status_code,200,detail.data)
        self.assertEqual(Decimal(detail.data['data']['source_detail']['received_after']),100)

    def test_rejects_cutting_and_missing_permission(self):
        payload = self.payload()
        payload['plan_category']='CUTTING'
        self.assertEqual(self.receive(payload=payload).status_code,400)
        self.user.user_permissions.clear()
        self.user = type(self.user).objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.url).status_code,403)
