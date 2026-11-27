import uuid
from decimal import Decimal
from datetime import timedelta
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.utils import timezone
from apps.boms.models import BomLine, BomSection
from apps.material_issues.models import MaterialIssue, MaterialIssueLine, MaterialIssueAuditEvent, OrderMaterialRequirement, RequirementContribution
from apps.reference_data.models import ProductionUnit, ProductCategory
from apps.products.models import RawMaterialInformation
from apps.workshop_config.models import Craft
from ..models import InternalSemiFinishedReceipt, InternalSemiFinishedReceiptLine, PublicStockBalance, PublicStockMovement
from ..public_stock_identity import build_semi_finished_identity
from ..public_stock_services import credit_public_stock
from .test_public_stock_services import PublicStockFixture


class SewingFixture(PublicStockFixture):
    def setUp(self):
        super().setUp()
        self.prepare_sewing()

    def prepare_sewing(self):
        self.meter,_=ProductionUnit.objects.get_or_create(unit_name='米',defaults={'unit_code':'IRMETER'})
        self.set_unit,_=ProductionUnit.objects.get_or_create(unit_name='套',defaults={'unit_code':'IRSET'})
        self.external_sewing,_=Craft.objects.get_or_create(outsourcing_code='SEWING',defaults={
            'name':'外发车缝','craft_type':'EXTERNAL','created_by_employee':self.employee})
        fabric_section=BomSection.objects.create(bom=self.bom,line_number=2,section_type='FABRIC',title='面料类')
        cutting_section=BomSection.objects.create(bom=self.bom,line_number=3,section_type='FABRIC',title='裁剪明细')
        category=ProductCategory.objects.get(category_name='面料',item_type='MATERIAL')
        self.fabric_material=RawMaterialInformation.objects.create(material_number='IR-FABRIC-001',item_type='MATERIAL',
            category=category,unit=self.meter,material_name='600D面布',material='600D',specification='150cm',color_snapshot='蓝色')
        self.fabric=BomLine.objects.create(section=fabric_section,line_number=1,category='面料',material='600D',
            part_name='面布',specification='150cm',unit='米',raw_values={'fabric_color_name':'蓝色','fabric_color_code':'5865C',
                'source_raw_material_id':str(self.fabric_material.pk)})
        self.parts=[]
        for index,(name,usage) in enumerate([('座面', '0.3'),('靠背','0.2')],1):
            self.parts.append(BomLine.objects.create(section=cutting_section,line_number=index,category='裁片',material='600D',
                part_name=name,specification='50*40',unit='套',fabric_source_line=self.fabric,
                cutting_pieces_per_set=2,fabric_meters_per_piece=Decimal(usage),cutting_sets_per_product=1))
        self.requirement=OrderMaterialRequirement.objects.create(production_task=self.task,raw_material=self.fabric_material,
            unit=self.meter,line_type='RAW',section_code='FABRIC',required_quantity=500,source_revision_hash='b'*64)
        RequirementContribution.objects.create(requirement=self.requirement,product_line=self.product_line,bom=self.bom,
            bom_line=self.fabric,required_quantity=500,source_revision_hash='c'*64)
        self.fabric_issue=MaterialIssue.objects.create(issue_number='IR-SEWING-INPUT',client_request_id=uuid.uuid4(),
            request_payload_hash='d'*64,stock_mode='PUBLIC_V2',production_task=self.task,product_line=self.product_line,
            workshop=self.workshop,status='ISSUED',created_by_employee=self.employee,updated_by_employee=self.employee,
            issued_by_employee=self.employee,issued_at=timezone.now())
        self.fabric_issue_line=MaterialIssueLine.objects.create(issue=self.fabric_issue,line_number=1,requirement=self.requirement,
            raw_material=self.fabric_material,line_type='RAW',unit=self.meter,requested_quantity=100,issued_quantity=100,
            unit_snapshot='米')
        MaterialIssueAuditEvent.objects.create(issue=self.fabric_issue,action='CREATED',issue_version=1,actor_employee=self.employee,
            snapshot={'plan_source':{'plan_category':'CUTTING','schedule_product_id':str(self.schedule_product.pk)}})


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True,PUBLIC_STOCK_ISSUES_ENABLED=True)
class InternalSewingReceiptTests(SewingFixture,TestCase):
    url='/api/v1/semi-finished-receipts/'

    def setUp(self):
        super().setUp()
        plan_permission = Permission.objects.get(
            content_type__app_label='production_scheduling', codename='view_productionschedule')
        self.user.user_permissions.add(plan_permission)
        self.user = type(self.user).objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)

    def preview(self):
        response=self.client.get(self.url+'preview/',{'schedule_product_id':str(self.schedule_product.pk),'plan_category':'SEWING'})
        self.assertEqual(response.status_code,200,response.data)
        return response.data['data']
    def receive(self, seat=0, back=0, date=None, *, with_zone=True):
        payload={'request_id':str(uuid.uuid4()),'schedule_product_id':str(self.schedule_product.pk),'plan_category':'SEWING',
            'receipt_date':str(date or timezone.localdate()),'remark':'车缝测试',
            'lines':[{'bom_line_id':str(line.pk),'quantity':str(quantity)} for line,quantity in zip(self.parts,[seat,back]) if quantity]}
        if with_zone:
            payload['zone_id'] = str(self.semi_zone.pk)
        return self.client.post(self.url,payload,format='json',HTTP_IF_MATCH=self.preview()['etag'])

    def confirm(self, submitted, zone_id=None):
        receipt_id = submitted.data['data']['receipt_id']
        detail = self.client.get(f'{self.url}{receipt_id}/')
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data['data']['status'], 'PENDING')
        payload = {'zone_id': str(zone_id)} if zone_id else {}
        return self.client.post(f'{self.url}{receipt_id}/confirm/', payload, format='json',
                                HTTP_IF_MATCH=detail.data['data']['etag'])

    def test_actual_sewing_sets_are_limited_by_order_demand_without_shared_meter_cap(self):
        response=self.receive(501,500,with_zone=False)
        self.assertEqual(response.status_code,400,response.data)
        self.assertFalse(InternalSemiFinishedReceiptLine.objects.exists())
        response=self.receive(500,500,with_zone=False)
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(set(InternalSemiFinishedReceiptLine.objects.values_list('input_per_output','input_quantity')), {(None,None)})
        receipt = InternalSemiFinishedReceipt.objects.get()
        self.assertEqual(receipt.source_snapshot['quantity_basis'],'ORDER_REMAINING')
        self.assertIsNone(receipt.zone_id)
        self.assertTrue(all(Decimal(row['can_receive'])==0 for row in self.preview()['lines']))
        self.assertEqual(response.data['data']['record_ids'], [])
        self.assertEqual(self.confirm(response).status_code, 400)
        confirmed = self.confirm(response, self.semi_zone.pk)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(len(confirmed.data['data']['record_ids']), 2)
        receipt.refresh_from_db()
        self.assertEqual(receipt.zone_id, self.semi_zone.pk)
        self.assertEqual(set(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT')
                            .values_list('balance__zone_id', flat=True)), {self.semi_zone.pk})
        self.fabric_issue_line.refresh_from_db()
        self.assertEqual(self.fabric_issue_line.issued_quantity,100)
        detail=self.client.get(self.url+response.data['data']['receipt_id']+'/')
        self.assertEqual(detail.status_code,200,detail.data)
        lines = detail.data['data']['lines']
        self.assertEqual({row['bom_line_id'] for row in lines}, {str(part.pk) for part in self.parts})
        self.assertEqual([row['progress']['input_quantity'] for row in lines], [None, None])

    def test_unissued_material_and_missing_meter_usage_do_not_limit_actual_sewing_sets(self):
        self.fabric_issue.status='DRAFT'
        self.fabric_issue.save(update_fields=['status'])
        for line in self.parts:
            line.fabric_meters_per_piece=None
            line.fabric_meters_per_set=None
            line.save(update_fields=['fabric_meters_per_piece','fabric_meters_per_set'])
        preview=self.preview()
        for row in preview['lines']:
            self.assertEqual(row['can_receive'],'500')
            self.assertEqual((row['input_remaining'],row['input_supported'],row['consumes_input']), (None,None,None))
        response=self.receive(500,500)
        self.assertEqual(response.status_code,201,response.data)
        confirmed = self.confirm(response)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

    def test_legacy_receipt_meter_values_remain_and_only_its_sets_reduce_remaining_demand(self):
        response=self.receive(100)
        self.assertEqual(response.status_code,201,response.data)
        confirmed = self.confirm(response)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        legacy=InternalSemiFinishedReceiptLine.objects.get()
        InternalSemiFinishedReceiptLine.objects.filter(pk=legacy.pk).update(input_per_output=Decimal('0.6'),input_quantity=60)
        self.parts[0].fabric_meters_per_piece=Decimal('2')
        self.parts[0].save(update_fields=['fabric_meters_per_piece'])
        response=self.receive(400)
        self.assertEqual(response.status_code,201,response.data)
        legacy.refresh_from_db()
        self.assertEqual((legacy.input_per_output,legacy.input_quantity),(Decimal('0.6'),60))
        self.assertEqual(self.receive(1).status_code,400)

    def test_missing_cutting_specification_names_part_and_preserves_error(self):
        submitted = self.receive(1)
        self.assertEqual(submitted.status_code, 201, submitted.data)
        part=self.parts[0]
        part.specification='/'
        part.save(update_fields=['specification'])
        balances=list(PublicStockBalance.objects.order_by('id').values_list('id','quantity'))
        movements=PublicStockMovement.objects.count()
        receipts=InternalSemiFinishedReceipt.objects.count()
        receipt_lines=InternalSemiFinishedReceiptLine.objects.count()
        query={'schedule_product_id':str(self.schedule_product.pk),'plan_category':'SEWING'}
        payload={**query,'request_id':str(uuid.uuid4()),'zone_id':str(self.semi_zone.pk),
            'receipt_date':str(timezone.localdate()),'lines':[{'bom_line_id':str(part.pk),'quantity':'1'}]}
        replies = {
            'preview': self.client.get(self.url+'preview/', query),
            'submit': self.client.post(self.url, payload, format='json', HTTP_IF_MATCH='"stale"'),
            'confirm': self.confirm(submitted),
        }
        for action, response in replies.items():
            with self.subTest(action=action):
                self.assertEqual(response.status_code,400,response.data)
                error=response.data['error']
                self.assertEqual(error['code'],'PUBLIC_STOCK_IDENTITY_INCOMPLETE')
                self.assertEqual(error['meta'],{'field':'specification'})
                self.assertEqual(error['field_errors']['specification'],'缺少确定的实物属性，空白和占位符不能合并库存。')
                self.assertIn(part.part_name,error['message'])
                self.assertIn('规格',error['message'])
                self.assertEqual(list(PublicStockBalance.objects.order_by('id').values_list('id','quantity')),balances)
                self.assertEqual(PublicStockMovement.objects.count(),movements)
                self.assertEqual(InternalSemiFinishedReceipt.objects.count(),receipts)
                self.assertEqual(InternalSemiFinishedReceiptLine.objects.count(),receipt_lines)

    def test_internal_and_external_same_piece_share_stock_and_internal_receipt_keeps_cap(self):
        identity=build_semi_finished_identity(bom_line=self.parts[0],completed_craft=self.external_sewing,unit=self.set_unit)
        external=credit_public_stock(identity=identity,zone=self.semi_zone,quantity=450,actor_employee=self.employee,
            source_type='OUTSOURCING_RETURN',source_id=uuid.uuid4(),source_line_id=uuid.uuid4(),
            production_task=self.task,product_line=self.product_line,bom_line=self.parts[0])
        self.assertEqual(self.receive(51).status_code,400)
        submitted = self.receive(50)
        self.assertEqual(submitted.status_code, 201, submitted.data)
        confirmed = self.confirm(submitted)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        row=InternalSemiFinishedReceiptLine.objects.get()
        self.assertEqual(row.stock_movement.balance_id,external.balance_id)
        self.assertEqual(row.received_before,450)
        self.assertIsNone(row.input_quantity)
        self.assertEqual(PublicStockBalance.objects.get(pk=external.balance_id).quantity,500)
        self.assertEqual(self.receive(1).status_code, 400)
        credit_public_stock(identity=identity,zone=self.semi_zone,quantity=1,actor_employee=self.employee,
            source_type='OUTSOURCING_RETURN',source_id=uuid.uuid4(),source_line_id=uuid.uuid4(),
            production_task=self.task,product_line=self.product_line,bom_line=self.parts[0])
        self.assertEqual(PublicStockBalance.objects.get(pk=external.balance_id).quantity,501)

    def test_receipt_date_filter_uses_entered_date(self):
        yesterday=timezone.localdate()-timedelta(days=1)
        response=self.receive(10,date=yesterday)
        self.assertEqual(response.status_code,201,response.data)
        records=self.client.get(self.url,{'date_from':str(yesterday),'date_to':str(yesterday)}).data['data']
        self.assertEqual(records['total'],1)
        self.assertEqual(records['items'][0]['receipt_date'],str(yesterday))
        receipt_id = response.data['data']['receipt_id']
        self.assertEqual(records['items'][0]['id'], receipt_id)
        confirmed = self.confirm(response)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        records = self.client.get(self.url, {'date_from': str(yesterday), 'date_to': str(yesterday)}).data['data']
        self.assertEqual([(row['id'], row['receipt_date']) for row in records['items']], [(receipt_id, str(yesterday))])
        self.assertEqual(self.client.get(self.url+receipt_id+'/').status_code,200)

    def test_disabled_public_flow_rejects_first_receipt(self):
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False,PUBLIC_STOCK_ISSUES_ENABLED=False):
            response=self.client.get(self.url+'preview/',{'schedule_product_id':str(self.schedule_product.pk),'plan_category':'SEWING'})
            self.assertEqual(response.status_code,400,response.data)

    def test_legacy_issued_fabric_is_not_read_or_converted_for_sewing_set_count(self):
        self.fabric_issue.stock_mode='LEGACY'; self.fabric_issue.save(update_fields=['stock_mode'])
        response=self.client.get(self.url+'preview/',{'schedule_product_id':str(self.schedule_product.pk),'plan_category':'SEWING'})
        self.assertEqual(response.status_code,200,response.data)
        self.fabric_issue.refresh_from_db()
        self.assertEqual(self.fabric_issue.stock_mode,'LEGACY')
