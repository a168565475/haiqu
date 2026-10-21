import copy
import json
import uuid
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.files.models import BusinessFile
from apps.organizations.models import Employee
from apps.inventory.models import (
    FinishedGoodsOutbound, FinishedGoodsReceipt, PublicStockBalance, PublicStockMovement,
    Warehouse, WarehouseLocation, WarehouseZone,
)
from apps.inventory.api.serializers import FinishedGoodsOutboundSerializer
from apps.inventory.selectors import finished_goods_outbounds
from .test_inventory_api import FinishedGoodsInventoryApiTests as Fixtures


class FinishedOutboundTests(APITestCase):
    setUp = Fixtures.setUp
    receipt_payload = Fixtures.receipt_payload
    create_receipt = Fixtures.create_receipt
    create_second_line = Fixtures.create_second_line
    url = '/api/v1/finished-goods-inventory/outbounds/'

    def payload(self, receipt=None, **changes):
        receipt = receipt or self.create_receipt()
        data = {'responsible_employee_id':str(self.employee.pk), 'shipment_date':str(timezone.localdate()),
            'loading_fee':'12.30', 'other_fee':'2.00', 'items':[{'receipt_id':receipt['id'],
            'expected_remaining_quantity':6, 'outbound_quantity':2, 'quantity_per_box':3}]}
        data.update(changes)
        return data

    @staticmethod
    def image(name='loading.png'):
        return SimpleUploadedFile(name, b'\x89PNG\r\n\x1a\nimage-test', content_type='image/png')

    def test_fields_material_snapshot_and_stale_submission_rollback(self):
        self.line.material_snapshot = '钢管 / 涤纶'
        self.line.save(update_fields=['material_snapshot'])
        data = self.payload()
        created = self.client.post(self.url, data, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        item = created.data['data']
        self.assertEqual(item['loading_fee'], '12.30')
        self.assertEqual(item['responsible_name_snapshot'], self.employee.display_name)
        self.assertEqual(item['lines'][0]['material_snapshot'], '钢管 / 涤纶')
        self.assertEqual(self.client.post(self.url, data, format='json').status_code, 409)
        self.assertEqual(FinishedGoodsOutbound.objects.count(), 1)
        self.assertEqual(FinishedGoodsReceipt.objects.get().remaining_quantity, 4)
        self.assertEqual(self.client.get(self.url + item['id'] + '/').status_code, 200)

    def test_required_fields_invalid_employee_date_and_fees(self):
        data = self.payload()
        for field in ['responsible_employee_id', 'shipment_date']:
            invalid = {key:value for key,value in data.items() if key != field}
            self.assertEqual(self.client.post(self.url, invalid, format='json').status_code, 400)
        for changes in [{'responsible_employee_id':str(uuid.uuid4())}, {'shipment_date':'not-a-date'},
                        {'loading_fee':'-1'}, {'other_fee':'0.001'}, {'attachment_ids':[str(uuid.uuid4())]}]:
            response = self.client.post(self.url, {**data, **changes}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(FinishedGoodsOutbound.objects.exists())
        self.assertEqual(FinishedGoodsReceipt.objects.get().remaining_quantity, 6)

    @patch('apps.files.uploads.scan_upload', return_value=('CLEAN', 'test scanner'))
    def test_multipart_multiple_images_and_permission_boundary(self, _scan):
        data = self.payload()
        data['items'] = json.dumps(data['items'])
        data['loading_images'] = [self.image(), self.image('second.png')]
        response = self.client.post(self.url, data, format='multipart')
        self.assertEqual(response.status_code, 201, response.data)
        images = response.data['data']['loading_images']
        self.assertEqual(len(images), 2)
        file_response = self.client.get(images[0]['url'])
        self.assertEqual(file_response.status_code, 200)
        # 消费测试客户端包装的文件流，让它安全关闭文件而不关闭测试事务连接。
        self.assertTrue(b''.join(file_response.streaming_content).startswith(b'\x89PNG\r\n\x1a\n'))
        anonymous = APIClient()
        anonymous_response = anonymous.get(images[0]['url'])
        self.assertEqual(anonymous_response.status_code, 401)
        self.assertEqual(anonymous_response.data['error']['code'], 'AUTHENTICATION_REQUIRED')
        unprivileged = get_user_model().objects.create_user(username='outbound-no-permission')
        Employee.objects.create(user=unprivileged, employee_code='OUTBOUND-NONE', display_name='无权限测试员工')
        self.client.force_authenticate(unprivileged)
        self.assertEqual(self.client.get(images[0]['url']).status_code, 403)

    @patch('apps.files.uploads.scan_upload', return_value=('CLEAN', 'test scanner'))
    def test_failed_stock_submission_cleans_uploaded_files(self, _scan):
        data = self.payload()
        data['items'][0]['expected_remaining_quantity'] = 5
        data['items'] = json.dumps(data['items'])
        data['loading_images'] = [self.image()]
        response = self.client.post(self.url, data, format='multipart')
        self.assertEqual(response.status_code, 409, response.data)
        file = BusinessFile.objects.get(storage_key__startswith='inventory/finished-goods-loading/')
        self.assertIsNotNone(file.archived_at)
        self.assertFalse((Path(settings.MEDIA_ROOT) / file.storage_key).exists())
        self.assertFalse(FinishedGoodsOutbound.objects.exists())
        self.assertEqual(FinishedGoodsReceipt.objects.get().remaining_quantity, 6)

    @patch('apps.files.uploads.scan_upload', return_value=('CLEAN', 'test scanner'))
    def test_invalid_second_image_cleans_first_and_does_not_deduct(self, _scan):
        data = self.payload()
        data['items'] = json.dumps(data['items'])
        data['loading_images'] = [self.image(), SimpleUploadedFile('bad.png', b'invalid', content_type='image/png')]
        response = self.client.post(self.url, data, format='multipart')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(FinishedGoodsOutbound.objects.exists())
        self.assertFalse(list((Path(settings.MEDIA_ROOT) / 'inventory').rglob('*.png')))

    def test_list_pagination_filter_and_invalid_identifier(self):
        data = self.payload()
        ids = []
        for quantity in [6, 4]:
            data['items'][0]['expected_remaining_quantity'] = quantity
            response = self.client.post(self.url, data, format='json')
            self.assertEqual(response.status_code, 201, response.data)
            ids.append(response.data['data']['id'])
        for page, expected in [(1,ids[1]), (2,ids[0])]:
            response = self.client.get(self.url, {'page':page, 'page_size':1, 'product_line_id':str(self.line.pk)})
            self.assertEqual(response.data['data']['total'], 2)
            self.assertEqual([row['id'] for row in response.data['data']['items']], [expected])
        self.assertEqual(self.client.get(self.url, {'product_line_id':str(uuid.uuid4())}).data['data']['total'], 0)
        self.assertEqual(self.client.get(self.url, {'page':0}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'production_task_id':'invalid'}).status_code, 400)

    def create_multi_product_outbound(self):
        first = self.create_receipt()
        receipt = FinishedGoodsReceipt.objects.get(pk=first['id'])
        receipt.product_code_snapshot = 'FG-ALPHA'
        receipt.product_name_snapshot = '蓝色靠背椅'
        receipt.item_number_snapshot = 'SEARCH-A01'
        receipt.specification_snapshot = '40x50x60'
        receipt.actual_color = '宝蓝色'
        receipt.save()
        second_line = self.create_second_line()
        second_line.quantity = 25
        second_line.save(update_fields=['quantity'])
        warehouse = Warehouse.objects.create(warehouse_number='CKT02', warehouse_name='测试第二仓', warehouse_type='FINISHED')
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name='二楼')
        location = WarehouseLocation.objects.create(zone=zone, location_number='B1-1-1')
        second_receipt = copy.copy(receipt)
        second_receipt.pk = uuid.uuid4()
        second_receipt._state.adding = True
        second_receipt.receipt_number = 'RK-SEARCH-B'
        second_receipt.production_task_product = second_line
        second_receipt.product_code_snapshot = 'FG-BETA'
        second_receipt.product_name_snapshot = '红色折叠桌'
        second_receipt.item_number_snapshot = 'SEARCH-B02'
        second_receipt.specification_snapshot = '80x90x100'
        second_receipt.actual_color = '砖红色'
        second_receipt.location = location
        second_receipt.received_quantity = 9
        second_receipt.remaining_quantity = 9
        second_receipt.save(force_insert=True)
        data = self.payload(first)
        data['items'].append({'receipt_id': str(second_receipt.pk), 'expected_remaining_quantity': 9,
                              'outbound_quantity': 3, 'quantity_per_box': 3})
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['data'], second_line, warehouse

    def test_list_and_detail_distinguish_order_receipt_and_outbound_quantities(self):
        outbound, _, warehouse = self.create_multi_product_outbound()
        for result in [self.client.get(self.url).data['data']['items'][0],
                       self.client.get(self.url + outbound['id'] + '/').data['data']]:
            lines = {line['product_code_snapshot']: line for line in result['lines']}
            first, second = lines['FG-ALPHA'], lines['FG-BETA']
            self.assertEqual((first['order_quantity'], first['received_quantity'], first['outbound_quantity']), (10, 6, 2))
            self.assertEqual((second['order_quantity'], second['received_quantity'], second['outbound_quantity']), (25, 9, 3))
            self.assertEqual(first['warehouse_id'], str(self.warehouse_id))
            self.assertEqual(second['warehouse_id'], str(warehouse.pk))
            self.assertEqual(first['unit_name'], self.product.unit.unit_name)
            self.assertEqual(second['warehouse_name'], '测试第二仓')

    def test_search_fields_and_warehouse_return_complete_documents(self):
        outbound, _, warehouse = self.create_multi_product_outbound()
        for keyword in [outbound['outbound_number'], self.task.task_number, 'FG-ALPHA', '靠背椅',
                        'SEARCH-A01', '40x50', '宝蓝', '  FG-BETA  ']:
            with self.subTest(keyword=keyword):
                response = self.client.get(self.url, {'q': keyword})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data['data']['total'], 1)
                self.assertEqual(len(response.data['data']['items'][0]['lines']), 2)
        for warehouse_id in [self.warehouse_id, str(warehouse.pk)]:
            response = self.client.get(self.url, {'warehouse_id': warehouse_id})
            self.assertEqual(response.data['data']['total'], 1)
            self.assertEqual(len(response.data['data']['items'][0]['lines']), 2)
        self.assertEqual(self.client.get(self.url, {'q': '不存在的产品'}).data['data']['total'], 0)
        self.assertEqual(self.client.get(self.url, {'warehouse_id': str(uuid.uuid4())}).data['data']['total'], 0)

    def test_combined_filters_must_match_the_same_product_line(self):
        outbound, second_line, warehouse = self.create_multi_product_outbound()
        for filters, total in [
            ({'q': 'FG-ALPHA', 'warehouse_id': self.warehouse_id}, 1),
            ({'q': 'FG-ALPHA', 'warehouse_id': str(warehouse.pk)}, 0),
            ({'q': 'FG-ALPHA', 'product_line_id': str(second_line.pk)}, 0),
            ({'product_line_id': str(self.line.pk), 'warehouse_id': str(warehouse.pk)}, 0),
            ({'q': outbound['outbound_number'], 'warehouse_id': str(warehouse.pk)}, 1),
            ({'q': 'FG-BETA', 'warehouse_id': str(warehouse.pk), 'production_task_id': str(self.task.pk),
              'product_line_id': str(second_line.pk)}, 1),
        ]:
            with self.subTest(filters=filters):
                response = self.client.get(self.url, filters)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data['data']['total'], total)
                if total:
                    self.assertEqual(len(response.data['data']['items'][0]['lines']), 2)

    def test_read_without_task_source_returns_null_order_quantity(self):
        response = self.client.post(self.url, self.payload(), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        outbound_id = response.data['data']['id']
        # 仅在测试库预置历史无任务关联数据；读取时不能用0冒充未知订单量。
        FinishedGoodsReceipt.objects.update(production_task_product=None)
        for result in [self.client.get(self.url).data['data']['items'][0],
                       self.client.get(self.url + outbound_id + '/').data['data']]:
            self.assertIsNone(result['lines'][0]['order_quantity'])
            self.assertEqual(result['lines'][0]['received_quantity'], 6)

    def test_read_filter_validation_and_permissions(self):
        response = self.client.post(self.url, self.payload(), format='json')
        detail_url = self.url + response.data['data']['id'] + '/'
        for filters in [{'warehouse_id': 'invalid'}, {'q': 'x' * 301}, {'page_size': '-1'}]:
            self.assertEqual(self.client.get(self.url, filters).status_code, 400)
        anonymous = APIClient()
        for url in [self.url, detail_url]:
            self.assertEqual(anonymous.get(url).status_code, 401)
        unprivileged = get_user_model().objects.create_user(username='outbound-list-no-permission')
        Employee.objects.create(user=unprivileged, employee_code='OUTBOUND-LIST-NONE', display_name='无权限测试员工')
        self.client.force_authenticate(unprivileged)
        for url in [self.url, detail_url]:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.employee.status = 'INACTIVE'
        self.employee.save(update_fields=['status'])
        self.client.force_authenticate(self.user)
        for url in [self.url, detail_url]:
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_read_prefetch_does_not_query_per_product_line(self):
        outbound, _, _ = self.create_multi_product_outbound()
        with self.assertNumQueries(3):
            result = FinishedGoodsOutboundSerializer(finished_goods_outbounds(), many=True).data
            self.assertEqual(len(result[0]['lines']), 2)
        with self.assertNumQueries(3):
            result = FinishedGoodsOutboundSerializer(finished_goods_outbounds().get(pk=outbound['id'])).data
            self.assertEqual(len(result['lines']), 2)

    def test_outbound_reader_can_use_filters_but_not_full_receipt_options(self):
        url = '/api/v1/finished-goods-inventory/options/'
        reader = get_user_model().objects.create_user(username='outbound-only-reader')
        employee = Employee.objects.create(user=reader, employee_code='OUTBOUND-ONLY', display_name='出库查看员工')
        reader.user_permissions.add(Permission.objects.get(content_type__app_label='inventory', codename='view_finishedgoodsoutbound'))
        self.client.force_authenticate(reader)
        response = self.client.get(url, {'scope': 'filters'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data['data']), {'warehouses', 'zones'})
        self.assertIn(str(self.warehouse_id), {str(row['id']) for row in response.data['data']['warehouses']})
        self.assertEqual(self.client.get(self.url).status_code, 200)
        for filters in [{}, {'scope': 'full'}, {'scope': 'invalid'}]:
            self.assertEqual(self.client.get(url, filters).status_code, 403)
        self.assertEqual(self.client.get('/api/v1/finished-goods-inventory/').status_code, 403)
        employee.status = 'INACTIVE'
        employee.save(update_fields=['status'])
        self.assertEqual(self.client.get(url, {'scope': 'filters'}).status_code, 403)
        unprivileged = get_user_model().objects.create_user(username='outbound-options-no-permission')
        Employee.objects.create(user=unprivileged, employee_code='OUTBOUND-OPTIONS-NONE', display_name='无权限员工')
        self.client.force_authenticate(unprivileged)
        self.assertEqual(self.client.get(url, {'scope': 'filters'}).status_code, 403)
        self.assertEqual(APIClient().get(url, {'scope': 'filters'}).status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(url, {'scope': 'full'}).status_code, 200)
        self.assertEqual(self.client.get(url, {'scope': 'invalid'}).status_code, 400)

    def test_different_tasks_cannot_share_outbound_or_location_totals(self):
        first = self.create_receipt()
        second_task = copy.copy(self.task)
        second_task.pk=uuid.uuid4(); second_task._state.adding=True
        second_task.task_number='HT-OTHER'; second_task.contract_number='HTC-OTHER'; second_task.order_number='OTHER'
        second_task.save(force_insert=True)
        line=self.create_second_line(); line.production_task=second_task; line.save(update_fields=['production_task'])
        receipt=FinishedGoodsReceipt.objects.get(pk=first['id']); receipt.pk=uuid.uuid4(); receipt._state.adding=True
        receipt.receipt_number='RK-OTHER'; receipt.production_task_product=line; receipt.task_number_snapshot='HT-OTHER'; receipt.save(force_insert=True)
        data=self.payload(first)
        data['items'].append({**data['items'][0], 'receipt_id':str(receipt.pk)})
        response=self.client.post(self.url,data,format='json')
        self.assertEqual(response.status_code,400,response.data)
        summary=self.client.get('/api/v1/finished-goods-inventory/', {'q':self.task.task_number}).data
        self.assertEqual(summary['count'],1)
        row=summary['results'][0]
        fields=['task_number','product_id','unit_id','zone_id','product_number','product_code','product_name','item_number','category','specification','actual_color']
        locations=self.client.get('/api/v1/finished-goods-records/locations/',{key:row[key] for key in fields})
        self.assertEqual(locations.status_code,200,locations.data)
        self.assertEqual(sum(item['quantity'] for item in locations.data['data']['items']),6)

    def test_semi_outbound_records_are_actual_movements_filtered_by_product(self):
        # 测试预置流水仅存在独占测试库，不代表真实环境的业务验收。
        balance=PublicStockBalance.objects.create(stock_kind='SEMI', identity_key='outbound-test', identity_snapshot={'part_name':'支架','unit_name':'个'},
            unit=self.product.unit, zone_id=self.zone_id, quantity=4)
        movement=PublicStockMovement.objects.create(balance=balance,direction='OUT',quantity=2,before_quantity=6,after_quantity=4,
            source_type='MATERIAL_ISSUE',source_id=uuid.uuid4(),source_line_id=uuid.uuid4(),production_task=self.task,
            product_line=self.line,actor_employee=self.employee,snapshot={'issue_number':'LL-TEST'})
        url='/api/v1/semi-finished-receipts/'
        result=self.client.get(url,{'direction':'OUT','product_line_id':str(self.line.pk)})
        self.assertEqual(result.status_code,200,result.data)
        self.assertEqual(result.data['data']['total'],1)
        self.assertEqual(result.data['data']['items'][0]['receipt_number'],'LL-TEST')
        self.assertEqual(self.client.get(url,{'direction':'OUT','product_line_id':str(uuid.uuid4())}).data['data']['total'],0)
        detail=self.client.get(url+str(movement.pk)+'/',{'direction':'OUT'})
        self.assertEqual(detail.status_code,200,detail.data)
        self.assertEqual(detail.data['data']['source_detail']['after_quantity'],'4.0000')
        self.assertEqual(self.client.get(url+str(movement.pk)+'/').status_code,404)
