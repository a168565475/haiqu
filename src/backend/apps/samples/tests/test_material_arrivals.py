import uuid
from decimal import Decimal
from types import SimpleNamespace
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase
from apps.core.api.exceptions import Conflict
from apps.inventory.tests import test_inventory_api as inventory_tests
from apps.inventory.models import MaterialInboundLine
from apps.products.models import ProductInformation
from apps.reference_data.models import Currency, ProductCategory, ProductItem, ProductionUnit
from ..models import SampleRequest, SampleMaterialRequest, SampleMaterialProcurementRequest, SampleMaterialArrival, SampleMaterialPurchaseSource
from ..material_arrival_services import receive_material_arrival, material_progress
from ..procurement_status import sample_status_display


class MaterialArrivalTests(APITestCase):
    payload = inventory_tests.MaterialInventoryApiTests.payload
    confirm_quality = inventory_tests.MaterialInventoryApiTests.confirm_quality

    def setUp(self):
        # 独立运行也可创建真实采购/入库前置数据，不依赖迁移种子或其他测试的顺序。
        if not Currency.objects.filter(status='ACTIVE', archived_at__isnull=True).exists():
            Currency.objects.create(code='CNY', numeric_code='156', chinese_name='人民币')
        if not ProductInformation.objects.filter(status='ACTIVE', archived_at__isnull=True).exists():
            category = ProductCategory.objects.create(item_type='FINISHED', category_name='样品到货验收类别')
            unit = ProductionUnit.objects.create(unit_code='SAM-TEST', unit_name='样品验收单位')
            item = ProductItem.objects.create(item_number='SAM-ARRIVAL', category=category)
            ProductInformation.objects.create(product_number='SAM-ARRIVAL-001', category=category,
                product_name='到货验收产品', specification='60×80', unit=unit, product_item=item, scale='REGULAR')
        inventory_tests.MaterialInventoryApiTests.setUp(self)
        # 这些通用回写用例校验原单位小数链路，管材改用独立根米专项。
        self.raw_material.category, _ = ProductCategory.objects.get_or_create(category_name='五金', defaults={'item_type': 'MATERIAL'})
        self.raw_material.save(update_fields=['category'])
        self.bom_line.section.section_type = 'ACCESSORY'
        self.bom_line.section.save(update_fields=['section_type'])
        self.purchase_line.section_type_snapshot = 'ACCESSORY'
        self.purchase_line.save(update_fields=['section_type_snapshot'])
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='samples', codename='review_sample_materials'))
        self.request = SimpleNamespace(user=type(self.user).objects.get(pk=self.user.pk), employee=self.employee, META={})
        self.sample = SampleRequest.objects.create(customer_account=self.customer, owner_employee=self.employee,
            request_number='ARRIVAL-TEST', status='PROCUREMENT_PENDING', application_payload_hash='new-application', requested_at=timezone.now())
        self.key = str(uuid.uuid4())
        self.demand = {'key': self.key, 'name': '测试钢管', 'specification': 'Φ25×1.0', 'material': '测试钢管',
                       'color': '黑色', 'category': 'hardware', 'quantity': '4', 'unitLabel': self.purchase_line.source_unit_text, 'unitId': '', 'notes': '',
                       'supplyQuantity': '0', 'shortageQuantity': '4'}
        record = SampleMaterialRequest.objects.create(sample_request=self.sample, draft={'lines': [self.demand], 'notes': ''},
            warehouse_draft={'lines': [{'key': self.key, 'supplyQuantity': '0'}], 'notes': ''}, submitted_at=timezone.now(), reviewed_at=timezone.now())
        self.procurement = SampleMaterialProcurementRequest.objects.create(material_request=record, lines=[self.demand])
        SampleMaterialPurchaseSource.objects.create(procurement_request=self.procurement, line_key=self.key, purchase_order_line=self.purchase_line)

    def receipt(self, quantity, expected, rejected='0'):
        result = self.client.post('/api/v1/material-inventory/receipts/', self.payload(quantity=quantity, expected=expected), format='json')
        self.assertEqual(result.status_code, 201, result.data)
        line = MaterialInboundLine.objects.get(pk=result.data['data']['lines'][0]['id'])
        with self.assertRaises(Conflict):
            self.receive(line)
        confirmed = self.confirm_quality(result, return_quantity=rejected)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        if Decimal(rejected) > 0:
            from apps.procurement.models import PurchaseReturn
            returned = PurchaseReturn.objects.get(purchase_order=self.purchase_line.purchase_order)
            url = f'/api/v1/purchase-returns/{returned.pk}/'
            detail = self.client.get(url)
            confirm = self.client.post(url + 'confirm/', {}, format='json', HTTP_IF_MATCH=detail['ETag'])
            self.assertEqual(confirm.status_code, 200, confirm.data)
            complete = self.client.post(url + 'complete/', {}, format='json', HTTP_IF_MATCH=confirm['ETag'])
            self.assertEqual(complete.status_code, 200, complete.data)
        line.refresh_from_db()
        return line

    def receive(self, line):
        return receive_material_arrival(procurement_request_id=self.procurement.pk, line_key=self.key,
                                        inbound_line_id=line.pk, request=self.request)

    def test_order_creation_display_filters_and_waiting_count(self):
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='samples', codename__in=['view_samplerequest', 'view_sample_procurement']))
        self.client.force_authenticate(user=type(self.user).objects.get(pk=self.user.pk))
        order = self.purchase_line.purchase_order
        order.status = 'DRAFT'
        order.save(update_fields=['status'])
        self.assertEqual(sample_status_display(self.sample), '采购中')
        root = '/api/v1/sample-requests/'
        ordered = self.client.get(root, {'status': 'PROCUREMENT_IN_PROGRESS'})
        self.assertEqual(ordered.status_code, 200, ordered.data)
        self.assertEqual([row['id'] for row in ordered.data['data']], [str(self.sample.pk)])
        self.assertEqual(ordered.data['data'][0]['status_display'], '采购中')
        self.assertEqual(ordered.data['data'][0]['material_summary']['label'], '采购中')
        self.assertEqual(self.client.get(root, {'status': 'PROCUREMENT_PENDING'}).data['data'], [])
        self.assertEqual(self.client.get(root + 'summary/').data['data']['pending_procurement'], 0)
        detail = self.client.get(root + str(self.sample.pk) + '/')
        self.assertEqual(detail.data['data']['status_display'], '采购中')
        warehouse = self.client.get(root + str(self.sample.pk) + '/warehouse-review/')
        self.assertEqual(warehouse.data['data']['statusLabel'], '采购中')
        self.assertFalse(warehouse.data['data']['canEdit'])
        self.assertEqual(self.client.get(root, {'status': 'INVALID'}).status_code, 400)

        # 已归档订单不算正在采购，等待数量与列表筛选保持一致。
        order.archived_at = timezone.now()
        order.save(update_fields=['archived_at'])
        waiting = self.client.get(root, {'status': 'PROCUREMENT_PENDING'})
        self.assertEqual(waiting.data['data'][0]['status_display'], '等待采购')
        self.assertEqual(self.client.get(root + 'summary/').data['data']['pending_procurement'], 1)
        self.assertEqual(self.client.get(root, {'status': 'PROCUREMENT_IN_PROGRESS'}).data['data'], [])

    def test_unrelated_order_does_not_change_waiting_status(self):
        self.procurement.purchase_sources.all().delete()
        self.assertEqual(sample_status_display(self.sample), '等待采购')
        self.assertEqual(material_progress(self.sample)['label'], '等待采购')

    def test_purchase_does_not_override_later_production_status(self):
        self.sample.status = 'METALWORK_PENDING'
        self.assertEqual(sample_status_display(self.sample), '待上传金工参数')

    def test_partial_accepted_arrival_and_duplicate_then_full_arrival(self):
        first = self.receipt('3', '10.5000', rejected='1')
        self.assertEqual(first.accepted_quantity, Decimal('2'))
        sample = self.receive(first)
        self.assertEqual(sample.status, 'MATERIAL_ISSUE_PENDING')
        progress = material_progress(sample)
        self.assertEqual(sample_status_display(sample), '待发起领料')
        self.assertEqual(progress['label'], '部分入库')
        self.assertEqual(Decimal(progress['lines'][0]['remainingQuantity']), Decimal('2'))
        version = sample.updated_at
        self.assertEqual(self.receive(first).updated_at, version)
        self.assertEqual(SampleMaterialArrival.objects.count(), 1)
        second = self.receipt('2', '8.5000')
        sample = self.receive(second)
        self.assertEqual(sample.status, 'MATERIAL_ISSUE_PENDING')
        self.assertEqual(material_progress(sample)['label'], '材料齐备，待领料')
        self.assertEqual(SampleMaterialArrival.objects.count(), 2)
        self.assertEqual(self.receive(second).status, 'MATERIAL_ISSUE_PENDING')

    def test_foreign_line_unit_mismatch_and_zero_accepted_do_not_advance(self):
        from rest_framework.exceptions import ValidationError
        line = self.receipt('2', '10.5000')
        with self.assertRaises(ValidationError):
            receive_material_arrival(procurement_request_id=self.procurement.pk, line_key=uuid.uuid4(), inbound_line_id=line.pk, request=self.request)
        line.source_unit_text_snapshot = '千克'
        line.save(update_fields=['source_unit_text_snapshot'])
        with self.assertRaises(ValidationError):
            self.receive(line)
        # 品质确认已自动回写一次；错误重放不能新增或改写到货。
        self.assertEqual(SampleMaterialArrival.objects.count(), 1)
        self.sample.refresh_from_db()
        self.assertEqual(self.sample.status, 'MATERIAL_ISSUE_PENDING')

    def test_unmapped_purchase_and_unauthorized_replay_are_rejected(self):
        from django.contrib.auth.models import AnonymousUser
        from rest_framework.exceptions import PermissionDenied
        line = self.receipt('2', '10.5000')
        source = SampleMaterialPurchaseSource.objects.get(procurement_request=self.procurement)
        source.delete()
        with self.assertRaises(Conflict):
            self.receive(line)
        self.assertEqual(SampleMaterialArrival.objects.count(), 1)
        SampleMaterialPurchaseSource.objects.create(procurement_request=self.procurement, line_key=self.key, purchase_order_line=self.purchase_line)
        self.receive(line)
        self.request.user = AnonymousUser()
        with self.assertRaises(PermissionDenied):
            self.receive(line)
        self.assertEqual(SampleMaterialArrival.objects.count(), 1)
