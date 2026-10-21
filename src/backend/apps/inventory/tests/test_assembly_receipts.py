import uuid
from datetime import timedelta
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.workshop_config.models import Craft, Workshop
from apps.inventory.models import FinishedGoodsReceipt, AssemblyReceiptSource, WarehouseLocation
from apps.inventory.assembly_receipts import assembly_progress_for_plans
from .test_inventory_api import FinishedGoodsInventoryApiTests


class AssemblyFixture:
    def prepare(self, quantity=10, tolerance='10', report_operations=1):
        FinishedGoodsInventoryApiTests.setUp(self)
        self.line.quantity = quantity
        self.line.save(update_fields=['quantity'])
        self.task.order_tolerance_percent = tolerance
        self.task.status = 'READY'
        self.task.save(update_fields=['status', 'order_tolerance_percent'])
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='production_scheduling'))
        self.schedule=ProductionSchedule.objects.create(schedule_number='PC-ASSEMBLY-TEST',production_task=self.task,
            source_revision_hash='test',client_request_id=uuid.uuid4(),request_payload_hash='test',
            created_by_employee=self.employee,updated_by_employee=self.employee)
        today=timezone.localdate()
        self.plan=ProductionScheduleProduct.objects.create(schedule=self.schedule,product_line=self.line,line_number=1,
            planned_quantity=quantity,source_quantity_snapshot=quantity,unit=self.line.unit,unit_name_snapshot=self.line.unit.unit_name,
            material_inbound_date=today,metal_return_date=today,sewing_return_date=today,finished_inbound_date=today,
            product_snapshot={'product_name':'测试成品'},source_revision_hash='test')
        workshop, _ = Workshop.objects.get_or_create(name='装配车间')
        self.craft, _ = Craft.objects.get_or_create(plan_category='ASSEMBLY', defaults={
            'craft_type':'INTERNAL', 'name':'装配测试工序', 'workshop':workshop, 'status':'ACTIVE'})
        ProductionScheduleProductCraft.objects.create(schedule_product=self.plan,craft=self.craft,craft_type_snapshot='INTERNAL',
            craft_name_snapshot=self.craft.name,plan_category='ASSEMBLY')
        self.task.status = 'IN_PRODUCTION'
        self.task.save(update_fields=['status'])
        from .assembly_reporting_fixture import seed_reported_assembly
        self.assembly_scheme = seed_reported_assembly(self.line, self.employee, plan=self.plan, operations=report_operations)

    def preview(self):
        response=self.client.get('/api/v1/assembly-finished-receipts/preview/',{'schedule_product_id':self.plan.pk})
        self.assertEqual(response.status_code,200,response.data)
        return response.data['data']

    def payload(self,**changes):
        data=dict(request_id=str(uuid.uuid4()),schedule_product_id=str(self.plan.pk),location_id=self.location_id,
            receipt_date=str(timezone.localdate()-timedelta(days=1)),received_quantity=10,quantity_per_box=None,
            actual_color='黑色',remark='装配实收')
        data.update(changes);return data

    def post(self,data=None,etag=None):
        return self.client.post('/api/v1/assembly-finished-receipts/',data or self.payload(),format='json',
            HTTP_IF_MATCH=etag or self.preview()['etag'])


class AssemblyReceiptTests(AssemblyFixture,APITestCase):
    def setUp(self):self.prepare()

    def test_receipt_without_issue_and_net_complete_then_tolerance(self):
        response=self.post();self.assertEqual(response.status_code,201,response.data)
        self.assertTrue(assembly_progress_for_plans([self.plan])[str(self.plan.pk)]['complete'])
        self.assertEqual(self.preview()['remaining_receivable'],1)
        extra=self.post(self.payload(received_quantity=1));self.assertEqual(extra.status_code,201,extra.data)
        denied=self.post(self.payload(received_quantity=1));self.assertEqual(denied.status_code,400)
        self.task.refresh_from_db();self.assertEqual(self.task.status,'IN_PRODUCTION')
        self.assertEqual(FinishedGoodsReceipt.objects.count(),2)

    def test_replay_and_changed_content(self):
        payload=self.payload();etag=self.preview()['etag'];first=self.post(payload,etag)
        second=self.post(payload,etag);self.assertEqual(second.status_code,200,second.data)
        self.assertEqual(first.data['data']['id'],second.data['data']['id'])
        payload['received_quantity']=1
        self.assertEqual(self.post(payload,etag).status_code,409)
        self.assertEqual(AssemblyReceiptSource.objects.count(),1)

    def test_stale_preview_and_legacy_entry_share_limit(self):
        etag=self.preview()['etag']
        legacy=FinishedGoodsInventoryApiTests.receipt_payload(self,received_quantity=6,quantity_per_box=None)
        response=self.client.post('/api/v1/finished-goods-inventory/receipts/',legacy,format='json')
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(self.post(self.payload(received_quantity=5),etag).status_code,412)
        self.assertEqual(self.post(self.payload(received_quantity=5)).status_code,201)
        legacy.update(expected_received_total=11,received_quantity=1)
        self.assertEqual(self.client.post('/api/v1/finished-goods-inventory/receipts/',legacy,format='json').status_code,400)

    def test_outbound_balance_does_not_reopen_quota(self):
        self.assertEqual(self.post().status_code,201)
        FinishedGoodsReceipt.objects.update(remaining_quantity=0)
        self.assertEqual(self.preview()['remaining_receivable'],1)
        self.assertEqual(self.preview()['received_total'],10)

    def test_capacity_failure_rolls_back_source(self):
        response=self.post(self.payload(quantity_per_box=1))
        self.assertEqual(response.status_code,400)
        self.assertFalse(FinishedGoodsReceipt.objects.exists());self.assertFalse(AssemblyReceiptSource.objects.exists())

    def test_date_source_records_pagination_and_detail(self):
        response=self.post(self.payload(received_quantity=4));self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(self.post(self.payload(received_quantity=4)).status_code,201)
        result=self.client.get('/api/v1/finished-goods-records/',{'source':'ASSEMBLY','page_size':1})
        self.assertEqual(result.status_code,200,result.data);self.assertEqual(result.data['data']['total'],2)
        self.assertEqual(len(result.data['data']['items']),1)
        row=result.data['data']['items'][0];self.assertEqual(row['receipt_date'],str(timezone.localdate()-timedelta(days=1)))
        self.assertEqual(row['source_type'],'ASSEMBLY');self.assertEqual(row['schedule_number'],self.schedule.schedule_number)
        detail=self.client.get('/api/v1/finished-goods-records/'+row['id']+'/')
        self.assertEqual(detail.status_code,200);self.assertEqual(detail.data['data']['received_after'],8)
        self.assertEqual(self.client.get('/api/v1/finished-goods-records/not-a-uuid/').status_code,400)

    def test_permissions_and_wrong_stage(self):
        self.user.user_permissions.remove(Permission.objects.get(codename='add_finishedgoodsreceipt'))
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get('/api/v1/assembly-finished-receipts/preview/',{'schedule_product_id':self.plan.pk}).status_code,403)

    def test_paused_task_rejected(self):
        self.task.status='PAUSED';self.task.save(update_fields=['status'])
        self.assertEqual(self.client.get('/api/v1/assembly-finished-receipts/preview/',{'schedule_product_id':self.plan.pk}).status_code,409)

    def test_replay_succeeds_after_task_paused(self):
        payload=self.payload();etag=self.preview()['etag']
        first=self.post(payload,etag);self.assertEqual(first.status_code,201)
        self.task.status='PAUSED';self.task.save(update_fields=['status'])
        replay=self.post(payload,etag)
        self.assertEqual(replay.status_code,200,replay.data)
        self.assertEqual(replay.data['data']['id'],first.data['data']['id'])
        self.assertEqual(FinishedGoodsReceipt.objects.count(),1)

    def test_disabled_location_is_explicit_no_write_conflict(self):
        etag=self.preview()['etag']
        WarehouseLocation.objects.filter(pk=self.location_id).update(status='DISABLED')
        response=self.post(self.payload(),etag)
        self.assertEqual(response.status_code,409,response.data)
        self.assertEqual(response.data['error']['code'],'CONFLICT')
        self.assertFalse(FinishedGoodsReceipt.objects.exists())

    def test_request_content_conflict_has_distinct_code(self):
        payload=self.payload();etag=self.preview()['etag'];self.post(payload,etag)
        payload['remark']='修改内容'
        response=self.post(payload,etag)
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.data['error']['code'],'RECEIPT_REQUEST_CONFLICT')

    def test_replay_after_schedule_void_but_new_receipt_denied(self):
        payload=self.payload();etag=self.preview()['etag']
        first=self.post(payload,etag);self.assertEqual(first.status_code,201)
        ProductionSchedule.objects.filter(pk=self.schedule.pk).update(record_status='VOID',
            void_reason='独立测试作废',voided_at=timezone.now(),voided_by_employee=self.employee)
        replay=self.post(payload,etag)
        self.assertEqual(replay.status_code,200,replay.data)
        self.assertEqual(replay.data['data']['id'],first.data['data']['id'])
        self.assertEqual(self.post(self.payload(received_quantity=1),etag).status_code,404)

    def test_location_details_and_inventory_pagination(self):
        self.assertEqual(self.post(self.payload(received_quantity=4)).status_code,201)
        self.assertEqual(self.post(self.payload(received_quantity=3,actual_color='白色')).status_code,201)
        response=self.client.get('/api/v1/finished-goods-inventory/',{'page_size':1})
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data['count'],2);self.assertEqual(len(response.data['results']),1)
        row=response.data['results'][0]
        fields=['product_id','unit_id','zone_id','product_number','product_code','product_name','item_number','category','specification','actual_color']
        detail=self.client.get('/api/v1/finished-goods-records/locations/',{k:row[k] for k in fields if row[k] is not None})
        self.assertEqual(detail.status_code,200,detail.data)
        self.assertEqual(sum(r['quantity'] for r in detail.data['data']['items']),row['inventory_quantity'])

    def test_invalid_quantities_and_missing_precondition(self):
        for quantity in [0,-1,1.5]:
            response=self.post(self.payload(received_quantity=quantity))
            self.assertEqual(response.status_code,400,response.data)
        response=self.client.post('/api/v1/assembly-finished-receipts/',self.payload(),format='json')
        self.assertEqual(response.status_code,428,response.data)
        self.assertFalse(FinishedGoodsReceipt.objects.exists())

    def test_original_production_and_sample_sources_remain_queryable(self):
        payload=FinishedGoodsInventoryApiTests.receipt_payload(self,received_quantity=4,quantity_per_box=None)
        response=self.client.post('/api/v1/finished-goods-inventory/receipts/',payload,format='json')
        self.assertEqual(response.status_code,201,response.data)
        records=self.client.get('/api/v1/finished-goods-records/',{'source':'PRODUCTION_ORDER'})
        self.assertEqual(records.data['data']['total'],1)
        original=records.data['data']['items'][0]
        self.assertEqual(original['source_type'],'PRODUCTION_ORDER')
        self.assertIsNone(original['received_before'])
        FinishedGoodsReceipt.objects.filter(pk=original['id']).update(source_type='SAMPLE_INVENTORY',production_task_product=None,
            source_document_number='SYGJ-TEST-001')
        records=self.client.get('/api/v1/finished-goods-records/',{'source':'SAMPLE_INVENTORY'})
        self.assertEqual(records.data['data']['total'],1)
        self.assertEqual(records.data['data']['items'][0]['source_type_display'],'样品入库')

    def test_records_exclude_samples_before_count_and_pagination(self):
        assembly=self.post(self.payload(received_quantity=2))
        self.assertEqual(assembly.status_code,201,assembly.data)
        payload=FinishedGoodsInventoryApiTests.receipt_payload(self,received_quantity=2,quantity_per_box=None,expected_received_total=2)
        production=self.client.post('/api/v1/finished-goods-inventory/receipts/',payload,format='json')
        self.assertEqual(production.status_code,201,production.data)
        sample=self.client.post('/api/v1/finished-goods-inventory/receipts/',{**payload,'expected_received_total':4},format='json')
        self.assertEqual(sample.status_code,201,sample.data)
        FinishedGoodsReceipt.objects.filter(pk=sample.data['data']['id']).update(
            source_type='SAMPLE_INVENTORY',production_task_product=None,source_document_number='SYGJ-EXCLUDE-TEST')
        url='/api/v1/finished-goods-records/'
        self.assertEqual(self.client.get(url).data['data']['total'],3)
        sources=set()
        for page in [1,2]:
            response=self.client.get(url,{'exclude_sample':'true','page_size':1,'page':page})
            self.assertEqual(response.status_code,200,response.data)
            self.assertEqual(response.data['data']['total'],2)
            self.assertEqual(len(response.data['data']['items']),1)
            sources.add(response.data['data']['items'][0]['source_type'])
        self.assertEqual(sources,{'ASSEMBLY','PRODUCTION_ORDER'})
        samples=self.client.get(url,{'source':'SAMPLE_INVENTORY','exclude_sample':'true'})
        self.assertEqual(samples.data['data'],{'items':[],'total':0})
        self.assertEqual(self.client.get(url,{'source':'SAMPLE_INVENTORY'}).data['data']['total'],1)

    def test_records_reject_invalid_sample_exclusion(self):
        response=self.client.get('/api/v1/finished-goods-records/',{'exclude_sample':'invalid'})
        self.assertEqual(response.status_code,400,response.data)

    def test_inventory_excludes_samples_before_aggregation_and_pagination(self):
        for quantity in [2,1]:
            response=self.post(self.payload(received_quantity=quantity))
            self.assertEqual(response.status_code,201,response.data)
        payload=FinishedGoodsInventoryApiTests.receipt_payload(self,received_quantity=2,quantity_per_box=None,
            expected_received_total=3,actual_color='白色')
        response=self.client.post('/api/v1/finished-goods-inventory/receipts/',payload,format='json')
        self.assertEqual(response.status_code,201,response.data)
        sample=self.client.post('/api/v1/finished-goods-inventory/receipts/',
            {**payload,'expected_received_total':5,'actual_color':'黑色'},format='json')
        self.assertEqual(sample.status_code,201,sample.data)
        sample_id=sample.data['data']['id']
        # 保留相同汇总键，验证样品批次不会混入正式批次的数量、批次数和详情。
        FinishedGoodsReceipt.objects.filter(pk=sample_id).update(source_type='SAMPLE_INVENTORY')
        sample_only=FinishedGoodsReceipt.objects.get(pk=sample_id)
        sample_only.pk=None;sample_only.receipt_number='SAMPLE-ONLY-STOCK'
        sample_only.production_task_product=None;sample_only.actual_color='样品专用色'
        sample_only.save()
        url='/api/v1/finished-goods-inventory/'
        original=self.client.get(url)
        self.assertEqual(original.status_code,200,original.data)
        self.assertEqual(original.data['count'],3)
        black=next(row for row in original.data['results'] if row['actual_color']=='黑色')
        self.assertEqual((black['inventory_quantity'],black['batch_count']),(5,3))
        colors=set()
        fields=['product_id','unit_id','zone_id','product_number','product_code','product_name','item_number','category','specification','actual_color']
        for page in [1,2]:
            result=self.client.get(url,{'exclude_sample':'true','page_size':1,'page':page})
            self.assertEqual(result.status_code,200,result.data)
            self.assertEqual(result.data['count'],2)
            self.assertEqual(len(result.data['results']),1)
            row=result.data['results'][0];colors.add(row['actual_color'])
            self.assertNotIn(str(sample_id),[str(pk) for pk in row['receipt_ids']])
            expected=(3,2) if row['actual_color']=='黑色' else (2,1)
            self.assertEqual((row['inventory_quantity'],row['batch_count']),expected)
            detail=self.client.get('/api/v1/finished-goods-records/locations/',
                {**{key:row[key] for key in fields},'exclude_sample':'true'})
            self.assertEqual(detail.status_code,200,detail.data)
            self.assertEqual(sum(item['quantity'] for item in detail.data['data']['items']),row['inventory_quantity'])
        self.assertEqual(colors,{'黑色','白色'})
        self.assertEqual(self.client.get(url,{'exclude_sample':'true','page_size':1,'page':3}).data['results'],[])
        self.assertEqual(self.client.get(url,{'exclude_sample':'true','q':'样品专用色'}).data['count'],0)
        self.assertEqual(self.client.get(url,{'exclude_sample':'false'}).data['count'],3)
        self.assertEqual(FinishedGoodsReceipt.objects.filter(source_type='SAMPLE_INVENTORY').count(),2)

    def test_inventory_scope_validation_and_permissions(self):
        url='/api/v1/finished-goods-inventory/'
        for target in [url,'/api/v1/finished-goods-records/locations/']:
            response=self.client.get(target,{'exclude_sample':'invalid'})
            self.assertEqual(response.status_code,400,response.data)
            self.assertIn('exclude_sample',response.data['error']['field_errors'])
        self.user.user_permissions.remove(Permission.objects.get(codename='view_finishedgoodsreceipt'))
        self.client.force_authenticate(type(self.user).objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get(url,{'exclude_sample':'true'}).status_code,403)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(url,{'exclude_sample':'true'}).status_code,[401,403])

    def test_unrelated_employee_cannot_preview_or_replay_source(self):
        from django.contrib.auth import get_user_model
        from apps.organizations.models import Employee
        payload=self.payload();etag=self.preview()['etag'];self.assertEqual(self.post(payload,etag).status_code,201)
        user=get_user_model().objects.create_user(username='unrelated_warehouse')
        Employee.objects.create(user=user,employee_code='FG-OTHER',display_name='其他仓管')
        user.user_permissions.set(Permission.objects.filter(codename__in=['add_finishedgoodsreceipt','view_finishedgoodsreceipt']))
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get('/api/v1/assembly-finished-receipts/preview/',{'schedule_product_id':self.plan.pk}).status_code,404)
        self.assertEqual(self.post(payload,etag).status_code,404)
