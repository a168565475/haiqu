"""车缝多张待入库原单按当前额度确认，同时保护冻结的实物属性。"""
import uuid

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductCategory
from apps.workshop_config.models import Craft, Workshop
from apps.wecom.models import NotificationEvent
from ..models import InternalSemiFinishedReceipt, PublicStockMovement
from .test_internal_receipt_sewing import SewingFixture
from . import test_internal_receipt_sewing as sewing_fixture
from .test_tube_d1_receipts import D1Fixture


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True)
class SewingPendingConfirmationTests(D1Fixture, APITestCase):
    url = '/api/v1/semi-finished-receipts/'
    preview = sewing_fixture.InternalSewingReceiptTests.preview
    receive = sewing_fixture.InternalSewingReceiptTests.receive

    def setUp(self):
        super().setUp()
        # 复用已独立准备产品/计划的夹具，再增加本测试真实使用的车缝来源。
        ProductCategory.objects.get_or_create(category_name='面料', item_type='MATERIAL')
        SewingFixture.prepare_sewing(self)
        workshop, _ = Workshop.objects.get_or_create(name='车缝车间')
        craft = Craft.objects.create(name='待入库确认测试车缝', craft_type='INTERNAL',
            plan_category='SEWING', workshop=workshop, status='ACTIVE')
        ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product,
            craft=craft, craft_type_snapshot='INTERNAL', craft_name_snapshot=craft.name, plan_category='SEWING')

    def submit_pending(self, quantity):
        response = self.receive(seat=quantity)
        self.assertEqual(response.status_code, 201, response.data)
        receipt = InternalSemiFinishedReceipt.objects.get(pk=response.data['data']['receipt_id'])
        return receipt, f'"{receipt.source_revision_hash}"'

    def confirm_pending(self, value):
        receipt, etag = value
        return self.client.post(f'{self.url}{receipt.pk}/confirm/', HTTP_IF_MATCH=etag)

    def confirm_both(self, *, newest_first):
        first = self.submit_pending(60)
        second = self.submit_pending(20)
        for value in ([second, first] if newest_first else [first, second]):
            response = self.confirm_pending(value)
            self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(InternalSemiFinishedReceipt.objects.filter(status='CONFIRMED').count(), 2)
        quantities = PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').values_list('quantity', flat=True)
        self.assertEqual(sum(quantities), 80)

    def test_older_pending_can_confirm_before_newer(self):
        self.confirm_both(newest_first=False)

    def test_older_pending_can_confirm_after_newer(self):
        self.confirm_both(newest_first=True)

    def test_changed_part_identity_cannot_confirm_frozen_receipt(self):
        receipt = self.submit_pending(60)
        self.parts[0].part_name = '已经变更的裁片'
        self.parts[0].save(update_fields=['part_name'])
        response = self.confirm_pending(receipt)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').exists())

    def test_deleted_request_cannot_recreate_sewing_pending_receipt(self):
        preview = self.preview()
        payload = {'request_id': str(uuid.uuid4()), 'schedule_product_id': str(self.schedule_product.pk),
            'plan_category': 'SEWING', 'zone_id': str(self.semi_zone.pk),
            'receipt_date': str(timezone.localdate()),
            'lines': [{'bom_line_id': str(self.parts[0].pk), 'quantity': '7'}]}
        created = self.client.post(self.url, payload, format='json', HTTP_IF_MATCH=preview['etag'])
        self.assertEqual(created.status_code, 201, created.data)
        receipt = InternalSemiFinishedReceipt.objects.get(pk=created.data['data']['receipt_id'])
        replay = self.client.post(self.url, payload, format='json', HTTP_IF_MATCH=preview['etag'])
        self.assertEqual(replay.status_code, 200, replay.data)
        deleted = self.client.delete(f'{self.url}{receipt.pk}/', HTTP_IF_MATCH=f'"{receipt.source_revision_hash}"')
        self.assertEqual(deleted.status_code, 204, deleted.data)
        event_count = NotificationEvent.objects.count()
        replay = self.client.post(self.url, payload, format='json', HTTP_IF_MATCH=preview['etag'])
        self.assertEqual(replay.status_code, 409, replay.data)
        self.assertEqual(replay.data['error']['code'], 'RECEIPT_REQUEST_DELETED')
        self.assertFalse(InternalSemiFinishedReceipt.objects.filter(request_id=payload['request_id']).exists())
        self.assertFalse(PublicStockMovement.objects.filter(source_type='INTERNAL_SEMI_RECEIPT').exists())
        self.assertEqual(NotificationEvent.objects.count(), event_count)
        self.assertEqual(self.preview()['lines'][0]['can_receive'], preview['lines'][0]['can_receive'])
        replacement = self.client.post(self.url, {**payload, 'request_id': str(uuid.uuid4())},
            format='json', HTTP_IF_MATCH=self.preview()['etag'])
        self.assertEqual(replacement.status_code, 201, replacement.data)
