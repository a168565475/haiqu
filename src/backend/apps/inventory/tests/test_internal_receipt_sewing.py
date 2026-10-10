import uuid
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.boms.models import BomLine, BomSection
from apps.material_issues.models import MaterialIssue, MaterialIssueLine, MaterialIssueAuditEvent, OrderMaterialRequirement, RequirementContribution
from apps.reference_data.models import ProductionUnit, ProductCategory
from apps.products.models import RawMaterialInformation
from apps.workshop_config.models import Craft
from ..models import InternalSemiFinishedReceiptLine, PublicStockBalance
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
    def preview(self):
        response=self.client.get(self.url+'preview/',{'schedule_product_id':str(self.schedule_product.pk),'plan_category':'SEWING'})
        self.assertEqual(response.status_code,200,response.data)
        return response.data['data']
    def receive(self, seat=0, back=0, date=None):
        payload={'request_id':str(uuid.uuid4()),'schedule_product_id':str(self.schedule_product.pk),'plan_category':'SEWING',
            'zone_id':str(self.semi_zone.pk),'receipt_date':str(date or timezone.localdate()),'remark':'车缝测试',
            'lines':[{'bom_line_id':str(line.pk),'quantity':str(quantity)} for line,quantity in zip(self.parts,[seat,back]) if quantity]}
        return self.client.post(self.url,payload,format='json',HTTP_IF_MATCH=self.preview()['etag'])

    def test_shared_fabric_sum_and_whole_sets(self):
        response=self.receive(100,101)
        self.assertEqual(response.status_code,400,response.data)
        self.assertFalse(InternalSemiFinishedReceiptLine.objects.exists())
        self.assertEqual(self.receive(100,100).status_code,201)
        self.assertEqual(sum(InternalSemiFinishedReceiptLine.objects.values_list('input_quantity',flat=True)),100)
        self.assertTrue(all(Decimal(row['can_receive'])==0 for row in self.preview()['lines']))

    def test_internal_and_external_same_piece_share_balance_and_total_cap(self):
        identity=build_semi_finished_identity(bom_line=self.parts[0],completed_craft=self.external_sewing,unit=self.set_unit)
        external=credit_public_stock(identity=identity,zone=self.semi_zone,quantity=450,actor_employee=self.employee,
            source_type='OUTSOURCING_RETURN',source_id=uuid.uuid4(),source_line_id=uuid.uuid4(),
            production_task=self.task,product_line=self.product_line,bom_line=self.parts[0])
        self.assertEqual(self.receive(51).status_code,400)
        self.assertEqual(self.receive(50).status_code,201)
        row=InternalSemiFinishedReceiptLine.objects.get()
        self.assertEqual(row.stock_movement.balance_id,external.balance_id)
        self.assertEqual(row.received_before,450)
        self.assertEqual(row.input_quantity,30)
        with self.assertRaises(ValidationError):
            credit_public_stock(identity=identity,zone=self.semi_zone,quantity=1,actor_employee=self.employee,
                source_type='OUTSOURCING_RETURN',source_id=uuid.uuid4(),source_line_id=uuid.uuid4(),
                production_task=self.task,product_line=self.product_line,bom_line=self.parts[0])
        self.assertEqual(PublicStockBalance.objects.get(pk=external.balance_id).quantity,500)

    def test_receipt_date_filter_uses_entered_date(self):
        yesterday=timezone.localdate()-timedelta(days=1)
        response=self.receive(10,date=yesterday)
        self.assertEqual(response.status_code,201,response.data)
        records=self.client.get(self.url,{'date_from':str(yesterday),'date_to':str(yesterday)}).data['data']
        self.assertEqual(records['total'],1)
        self.assertEqual(records['items'][0]['receipt_date'],str(yesterday))
        record_id=response.data['data']['record_ids'][0]
        self.assertEqual(self.client.get(self.url+record_id+'/').status_code,200)

    def test_disabled_public_flow_rejects_first_receipt(self):
        with override_settings(PUBLIC_STOCK_FLOW_ENABLED=False,PUBLIC_STOCK_ISSUES_ENABLED=False):
            response=self.client.get(self.url+'preview/',{'schedule_product_id':str(self.schedule_product.pk),'plan_category':'SEWING'})
            self.assertEqual(response.status_code,400,response.data)

    def test_legacy_issued_fabric_is_not_silently_converted(self):
        self.fabric_issue.stock_mode='LEGACY'; self.fabric_issue.save(update_fields=['stock_mode'])
        response=self.client.get(self.url+'preview/',{'schedule_product_id':str(self.schedule_product.pk),'plan_category':'SEWING'})
        self.assertEqual(response.status_code,400,response.data)
