"""仓库委外入口使用操作范围，不能借查看或其他动作的范围扩大权限。"""
import uuid
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.files.models import BusinessFile, FileScanStatus
from apps.material_issues.tests.test_metal_processing_p4 import MetalProcessingP4Fixture
from apps.organizations.models import EmployeeOrganizationAssignment, OrganizationUnit
from apps.workshop_config.models import Craft

from ..models import TubeOutsourcingAction, TubeOutsourcingOrder
from ..warehouse_access import DISPATCH_PERMISSION, RETURN_PERMISSION, RAW_RETURN_PERMISSION, REWORK_RETURN_PERMISSION
from .test_material_flow import MaterialFlowFixture
from .test_unified_tube_orders import UnifiedTubeFixture


URL = '/api/v1/unified-outsourcing-orders/'
WAREHOUSE = {'warehouse_stage': 'all'}
SCOPES = dict(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
              SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)


class WarehouseResponseMixin:
    def warehouse_rows(self, **filters):
        response = self.client.get(URL, {**WAREHOUSE, **filters})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def warehouse_get(self, url):
        response = self.client.get(url, WAREHOUSE)
        self.assertEqual(response.status_code, 200, response.data)
        return response


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, **SCOPES)
class WarehouseTubeOrdersTests(WarehouseResponseMixin, ScopedActorMixin, UnifiedTubeFixture, APITestCase):
    def test_dispatch_only_reads_stock_orders_without_view_and_keeps_direct_handoff_in_workshop(self):
        stock = self.saved_order('RAW_PIPE')
        direct = self.saved_order('METAL')
        self.scoped_actor()
        self.grant(DISPATCH_PERMISSION, 'MODULE')
        rows = self.warehouse_rows()
        self.assertEqual([row['id'] for row in rows], [stock['id']])
        self.assertEqual(rows[0]['warehouse_actions'], ['dispatch'])
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.warehouse_get(URL + 'options/')
        self.warehouse_get(f"/api/v1/tube-outsourcing-orders/{stock['id']}/")
        self.assertEqual(self.client.get(f"/api/v1/tube-outsourcing-orders/{stock['id']}/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/v1/tube-outsourcing-orders/{direct['id']}/", WAREHOUSE).status_code, 404)

    def test_return_scope_reads_workshop_orders_and_action_recovery_without_view(self):
        order = self.dispatched('METAL')
        action = TubeOutsourcingAction.objects.get(order_id=order['id'], kind='DISPATCH')
        self.scoped_actor()
        self.grant(RETURN_PERMISSION, 'CRAFT', [self.spray])
        self.grant('outsourcing.view_outsourcingorder', 'STOCK')
        rows = self.warehouse_rows()
        self.assertEqual([(row['id'], row['warehouse_actions']) for row in rows], [(order['id'], ['return'])])
        self.assertEqual(self.rows()['meta']['total'], 0)
        self.warehouse_get(f"/api/v1/tube-outsourcing-orders/{order['id']}/")
        self.warehouse_get(f"/api/v1/tube-outsourcing-orders/{order['id']}/action-by-request/{action.client_request_id}/")
        preview = self.client.get(f"/api/v1/tube-outsourcing-orders/{order['id']}/receipt-preview/")
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data['data']['can_receive'])
        self.assertEqual(self.client.post(f"/api/v1/tube-outsourcing-orders/{order['id']}/dispatch/?warehouse_stage=all",
                                         self.action_payload(), format='json').status_code, 403)

    def test_view_scope_does_not_supply_missing_operation_scope_or_options(self):
        order = self.dispatched('METAL')
        other = Craft.objects.create(name='仓库无关刺绣', craft_type='EXTERNAL', outsourcing_code='EMBROIDERY')
        self.scoped_actor()
        self.grant('outsourcing.view_outsourcingorder', 'MODULE')
        self.grant(RETURN_PERMISSION, 'CRAFT', [other])
        self.assertEqual(self.warehouse_rows(), [])
        self.assertEqual(self.client.get(f"/api/v1/tube-outsourcing-orders/{order['id']}/", WAREHOUSE).status_code, 404)
        options = self.warehouse_get(URL + 'options/').data['data']
        self.assertEqual([row['id'] for row in options['crafts']], [str(other.pk)])
        self.assertEqual(self.client.get(URL, {'warehouse_stage': 'invented'}).status_code, 400)

    def test_completed_and_missing_dispatch_records_have_no_return_action(self):
        complete = self.dispatched('METAL')
        self.receive_final(complete, self.receipt_payload(complete, '0'))
        missing = self.saved_order('METAL')
        TubeOutsourcingOrder.objects.filter(pk=missing['id']).update(status='PROCESSING')
        self.scoped_actor()
        self.grant(RETURN_PERMISSION)
        self.assertEqual({row['id'] for row in self.warehouse_rows()}, {complete['id'], missing['id']})
        self.assertTrue(all(row['warehouse_actions'] == [] for row in self.warehouse_rows()))
        self.assertEqual([row['id'] for row in self.warehouse_rows(status='COMPLETED')], [complete['id']])
        self.warehouse_get(f"/api/v1/tube-outsourcing-orders/{complete['id']}/")

    def test_dispatch_only_tracks_completed_receipt_without_receiving_or_reading_direct_source(self):
        completed = self.dispatched('RAW_PIPE')
        self.receive_final(completed, self.receipt_payload(completed, '0'))
        processing = self.dispatched('RAW_PIPE')
        direct = self.dispatched('METAL')
        self.receive_final(direct, self.receipt_payload(direct, '0'))
        self.scoped_actor()
        self.grant(DISPATCH_PERMISSION, 'STOCK')
        before = self.receipt_snapshot()
        completed_url = f"/api/v1/tube-outsourcing-orders/{completed['id']}/"
        preview = self.warehouse_get(completed_url + 'receipt-preview/').data['data']
        self.assertFalse(preview['can_receive'])
        self.assertEqual(preview['receipt']['order_id'], completed['id'])
        self.warehouse_get(completed_url + 'receipt/')
        self.assertEqual(self.client.get(completed_url + 'receipt-preview/').status_code, 403)
        self.assertEqual(self.client.get(completed_url + 'receipt/').status_code, 403)
        processing_url = f"/api/v1/tube-outsourcing-orders/{processing['id']}/"
        preview = self.warehouse_get(processing_url + 'receipt-preview/').data['data']
        self.assertFalse(preview['can_receive'])
        self.assertIn('回货确认权限', ' '.join(preview['blockers']))
        response = self.client.post(processing_url + 'confirm-receipt/?warehouse_stage=all',
            self.receipt_payload(processing), format='json', HTTP_IF_MATCH=processing['etag'])
        self.assertEqual(response.status_code, 403, response.data)
        unrelated = Craft.objects.create(name='跟踪无关刺绣', craft_type='EXTERNAL', outsourcing_code='EMBROIDERY')
        self.grant(RETURN_PERMISSION, 'CRAFT', [unrelated])
        self.assertFalse(self.warehouse_get(processing_url + 'receipt-preview/').data['data']['can_receive'])
        for path in ('receipt/', 'receipt-preview/'):
            response = self.client.get(f"/api/v1/tube-outsourcing-orders/{direct['id']}/{path}", WAREHOUSE)
            self.assertEqual(response.status_code, 404, response.data)
        self.assertEqual(before, self.receipt_snapshot())


@override_settings(TUBE_OUTSOURCING_ENABLED=False, **SCOPES)
class WarehouseRegularOrdersTests(WarehouseResponseMixin, ScopedActorMixin, MaterialFlowFixture, APITestCase):
    def test_action_only_product_image_requires_authorized_order_and_its_own_file(self):
        order_id = self.create()
        other_order_id = self.create('FABRIC')
        self.scoped_actor()
        self.grant(DISPATCH_PERMISSION, 'CRAFT', [self.f.spray])
        # 临时图片限制在本轮隔离 MEDIA_ROOT 内，由上下文负责关闭后清理。
        with TemporaryDirectory(prefix='warehouse-product-images-', dir=settings.MEDIA_ROOT) as media_root, \
                override_settings(MEDIA_ROOT=media_root):
            image_bytes = b'\x89PNG\r\n\x1a\nwarehouse-product-test'
            image_path = Path(media_root) / 'warehouse-product.png'
            image_path.write_bytes(image_bytes)
            business_file = BusinessFile.objects.create(uploaded_by_employee=self.f.employee,
                original_name=image_path.name, storage_key=image_path.name, content_type='image/png',
                size_bytes=len(image_bytes), scan_status=FileScanStatus.CLEAN)
            unrelated_file = BusinessFile.objects.create(uploaded_by_employee=self.f.employee,
                original_name='unrelated.png', storage_key='unrelated.png', content_type='image/png',
                size_bytes=1, scan_status=FileScanStatus.CLEAN)
            self.f.schedule_product.image_file = business_file
            self.f.schedule_product.save(update_fields=['image_file', 'updated_at'])
            url = f'/api/v1/outsourcing-orders/{order_id}/product-files/{business_file.pk}/'
            response = self.client.get(url, WAREHOUSE)
            self.assertEqual(response.status_code, 200)
            # 测试客户端在流消费结束时关闭响应，不能再次触发 request_finished。
            received_bytes = b''.join(response.streaming_content)
            self.assertEqual(response['Content-Type'], 'image/png')
            self.assertEqual(received_bytes, image_bytes)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.get(
                f'/api/v1/outsourcing-orders/{other_order_id}/product-files/{business_file.pk}/', WAREHOUSE).status_code, 404)
            self.assertEqual(self.client.get(
                f'/api/v1/outsourcing-orders/{order_id}/product-files/{unrelated_file.pk}/', WAREHOUSE).status_code, 404)
            business_file.scan_status = FileScanStatus.INFECTED
            business_file.save(update_fields=['scan_status'])
            self.assertEqual(self.client.get(url, WAREHOUSE).status_code, 400)

    def test_raw_return_only_can_track_load_details_and_reconciliation_but_not_other_actions(self):
        order_id = self.create()
        self.dispatch(order_id)
        self.scoped_actor()
        self.grant(RAW_RETURN_PERMISSION, 'CRAFT', [self.f.spray])
        rows = self.warehouse_rows()
        self.assertEqual([(row['id'], row['warehouse_actions']) for row in rows], [(order_id, ['raw'])])
        url = f'/api/v1/outsourcing-orders/{order_id}/'
        detail = self.warehouse_get(url).data['data']
        self.assertTrue(detail['can_return_raw'])
        self.assertFalse(detail['can_confirm_return'])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.warehouse_get(url + 'reconciliation/')
        self.warehouse_get('/api/v1/outsourcing-orders/options/')
        self.warehouse_get(URL + 'options/')

    def test_dispatch_and_return_scopes_are_independent_and_no_view_user_cannot_enter(self):
        order_id = self.create()
        other = self.f.sewing
        self.scoped_actor()
        self.assertEqual(self.client.get(URL, WAREHOUSE).status_code, 403)
        self.grant(DISPATCH_PERMISSION, 'CRAFT', [other])
        self.grant(RETURN_PERMISSION, 'CRAFT', [self.f.spray])
        rows = self.warehouse_rows()
        self.assertEqual([(row['id'], row['warehouse_actions']) for row in rows], [(order_id, [])])
        detail = self.warehouse_get(f'/api/v1/outsourcing-orders/{order_id}/').data['data']
        self.assertFalse(detail['can_confirm_dispatch'])


@override_settings(TUBE_OUTSOURCING_ENABLED=False, **SCOPES)
class WarehouseMetalOrdersTests(WarehouseResponseMixin, ScopedActorMixin, MetalProcessingP4Fixture, APITestCase):
    def setUp(self):
        super().setUp()
        department, _ = OrganizationUnit.objects.get_or_create(
            unit_code='DEPT_WAREHOUSE', defaults={'unit_name': '仓库'})
        EmployeeOrganizationAssignment.objects.get_or_create(
            employee=self.f.employee, organization_unit=department, effective_to=None,
            defaults={'effective_from': timezone.now() - timedelta(days=1)})

    def good_return_payload(self):
        return {'request_id': str(uuid.uuid4()), 'good_pieces': 1, 'zone_id': str(self.f.semi_zone.pk),
                'received_by_employee_id': str(self.f.employee.pk), 'return_date': str(timezone.localdate()),
                'remark': '仓库动作范围验证'}

    def test_original_return_only_reads_scoped_p4_context_without_metal_view(self):
        handoff = self.create_original_handoff()
        self.scoped_actor()
        self.grant(RETURN_PERMISSION, 'CRAFT', [self.f.spray])
        rows = self.warehouse_rows()
        self.assertEqual([(row['id'], row['detail_access'], row['warehouse_actions']) for row in rows],
                         [(self.original_order, 'METAL', ['return'])])
        handoff_url = f'/api/v1/metal-processing-handoffs/{handoff.pk}/'
        self.assertEqual(self.client.get(handoff_url).status_code, 403)
        context = self.warehouse_get(handoff_url).data['data']['good_return_context']
        self.assertTrue(context['can_return'])
        self.warehouse_get(f'/api/v1/metal-processing-original-orders/{self.original_order}/')
        self.warehouse_get('/api/v1/metal-processing-sources/options/')
        self.warehouse_get(f'/api/v1/metal-processing-sources/{self.line.pk}/')
        sources = self.client.get('/api/v1/metal-processing-sources/', {**WAREHOUSE, 'original_order_id': self.original_order})
        self.assertEqual(sources.status_code, 200, sources.data)
        self.assertEqual([row['issue_line_id'] for row in sources.data['data']], [str(self.line.pk)])
        self.assertEqual(self.client.get(f'/api/v1/outsourcing-orders/{self.original_order}/', WAREHOUSE).status_code, 404)

    def test_rework_return_only_reads_its_source_details_and_stock(self):
        order = self.create_order()
        detail = self.client.get(f'/api/v1/metal-processing-external-orders/{order.pk}/')
        self.post(f'/api/v1/metal-processing-external-orders/{order.pk}/handoff/', {
            'request_id': str(uuid.uuid4()), 'handoff_pieces': 5, 'handoff_date': str(timezone.localdate()),
        }, etag=detail.data['data']['etag'])
        self.scoped_actor()
        self.grant(REWORK_RETURN_PERMISSION, 'CRAFT', [self.f.spray])
        rows = self.warehouse_rows()
        self.assertEqual([(row['id'], row['warehouse_actions']) for row in rows], [(str(order.pk), ['return'])])
        url = f'/api/v1/metal-processing-external-orders/{order.pk}/'
        self.assertEqual(self.client.get(url).status_code, 403)
        self.warehouse_get(url)
        self.warehouse_get(url + 'semi-stock/')
        self.warehouse_get(f'/api/v1/metal-processing-sources/{self.line.pk}/')
        self.assertEqual(self.client.get(f'/api/v1/metal-processing-original-orders/{self.original_order}/', WAREHOUSE).status_code, 403)

    def test_dispatch_permission_never_shows_direct_handoff_or_rework(self):
        self.create_order()
        self.scoped_actor()
        self.grant(DISPATCH_PERMISSION)
        self.assertEqual(self.warehouse_rows(), [])

    def test_module_return_without_any_view_permission_reads_and_receives_original_handoff(self):
        handoff = self.create_original_handoff()
        self.scoped_actor()
        self.grant(RETURN_PERMISSION)
        rows = self.warehouse_rows()
        self.assertEqual([(row['id'], row['warehouse_actions']) for row in rows], [(self.original_order, ['return'])])
        handoff_url = f'/api/v1/metal-processing-handoffs/{handoff.pk}/'
        context = self.warehouse_get(handoff_url).data['data']['good_return_context']
        self.assertTrue(context['can_return'])
        self.warehouse_get(f'/api/v1/metal-processing-sources/{self.line.pk}/')
        self.warehouse_get(f'/api/v1/metal-processing-original-orders/{self.original_order}/')
        response = self.client.post(handoff_url + 'good-returns/', self.good_return_payload(),
                                    format='json', HTTP_IF_MATCH=context['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['returned_good_pieces'], 1)

    def test_module_rework_return_without_any_view_permission_reads_and_receives(self):
        order = self.create_order()
        url = f'/api/v1/metal-processing-external-orders/{order.pk}/'
        detail = self.client.get(url)
        self.post(url + 'handoff/', {'request_id': str(uuid.uuid4()), 'handoff_pieces': 5,
                  'handoff_date': str(timezone.localdate())}, etag=detail.data['data']['etag'])
        self.scoped_actor()
        self.grant(REWORK_RETURN_PERMISSION)
        self.assertEqual([(row['id'], row['warehouse_actions']) for row in self.warehouse_rows()],
                         [(str(order.pk), ['return'])])
        detail = self.warehouse_get(url).data['data']
        self.warehouse_get(f'/api/v1/metal-processing-sources/{self.line.pk}/')
        response = self.client.post(url + 'returns/', self.good_return_payload(),
                                    format='json', HTTP_IF_MATCH=detail['etag'])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['returned_good_pieces'], 1)

    def test_stock_return_cannot_borrow_all_material_view_or_unrelated_craft_for_direct_handoff(self):
        handoff = self.create_original_handoff()
        self.scoped_actor()
        self.grant(RETURN_PERMISSION, 'STOCK')
        self.assertEqual(self.warehouse_rows(), [])
        self.grant('material_issues.view_all_materialissue')
        unrelated = Craft.objects.create(name='库存回货无关刺绣', craft_type='EXTERNAL', outsourcing_code='EMBROIDERY')
        self.grant(RETURN_PERMISSION, 'CRAFT', [unrelated])
        self.assertEqual(self.warehouse_rows(), [])
        for url in (f'/api/v1/metal-processing-sources/{self.line.pk}/',
                    f'/api/v1/metal-processing-original-orders/{self.original_order}/',
                    f'/api/v1/metal-processing-handoffs/{handoff.pk}/'):
            self.assertEqual(self.client.get(url, WAREHOUSE).status_code, 404)
        response = self.client.post(f'/api/v1/metal-processing-handoffs/{handoff.pk}/good-returns/',
                                    self.good_return_payload(), format='json', HTTP_IF_MATCH='"invalid"')
        self.assertEqual(response.status_code, 404, response.data)
