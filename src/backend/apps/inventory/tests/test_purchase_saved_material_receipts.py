"""采购收货与质检只使用已保存的采购材料，不回读 BOM 重新定料。"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.boms.models import BomLine
from apps.procurement.models import PurchaseOrderLine
from apps.products.models import RawMaterialInformation
from ..models import MaterialInbound, MaterialInboundLine, MaterialInboundStatus, MaterialStockMovement
from . import test_inventory_api as inventory_fixture


@override_settings(MODULE_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class PurchaseSavedMaterialReceiptsTests(APITestCase):
    payload = inventory_fixture.MaterialInventoryApiTests.payload
    confirm_quality = inventory_fixture.MaterialInventoryApiTests.confirm_quality

    def setUp(self):
        inventory_fixture.MaterialInventoryApiTests.setUp(self)
        inventory_fixture.MaterialInventoryApiTests.use_general_material(self)
        self.purchase_line.raw_material_snapshot = self.raw_material.material_number
        self.purchase_line.calculation_snapshot = {
            'schema_version': 1, 'source': 'PRODUCTION_PURCHASE',
            'raw_material_id': str(self.raw_material.pk), 'unit_id': str(self.raw_material.unit_id),
        }
        self.purchase_line.save(update_fields=['raw_material_snapshot', 'calculation_snapshot'])

    def change_bom_material(self):
        other = RawMaterialInformation.objects.create(
            material_number='SAVED-RECEIPT-OTHER', item_type='MATERIAL',
            category=self.raw_material.category, material_name='另一种材料',
            specification='另一种规格', unit=self.raw_material.unit,
            warehouse_number='CKM01', warehouse_name='测试材料仓',
        )
        BomLine.objects.filter(pk=self.bom_line.pk).update(raw_values={'source_raw_material_id': str(other.pk)})
        return other

    def receive(self, **kwargs):
        return self.client.post('/api/v1/material-inventory/receivings/', self.payload(**kwargs), format='json')

    def test_first_receipt_and_quality_use_saved_purchase_material(self):
        other = self.change_bom_material()
        response = self.receive()
        self.assertEqual(response.status_code, 201, response.data)
        line = MaterialInboundLine.objects.get(inbound_id=response.data['data']['id'])
        self.assertEqual(line.raw_material_information_id, self.raw_material.pk)
        self.assertEqual(line.raw_material_snapshot, self.raw_material.material_number)
        confirmed = self.confirm_quality(response)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        movement = MaterialStockMovement.objects.get(source_line_id=line.pk)
        self.assertEqual(movement.balance.raw_material_id, self.raw_material.pk)
        self.assertEqual(movement.quantity, Decimal('4.2500'))
        self.assertFalse(MaterialStockMovement.objects.filter(balance__raw_material=other).exists())

    def test_purchase_of_100_receives_and_credits_all_105_pieces(self):
        self.purchase_line.actual_purchase_quantity = Decimal('100')
        self.purchase_line.save(update_fields=['actual_purchase_quantity'])
        url = '/api/v1/material-inventory/receivings/'
        payload = self.payload(quantity='105', expected='100')
        item = payload['items'][0]
        item['remark'] = '   '
        missing = self.client.post(url, payload, format='json')
        self.assertEqual(missing.status_code, 400, missing.data)
        self.assertIn('请填写该行备注', str(missing.data))

        split = {**payload, 'items': [
            {**item, 'received_quantity': '60'},
            {**item, 'received_quantity': '45', 'location_id': self.second_location_id},
        ]}
        missing = self.client.post(url, split, format='json')
        self.assertEqual(missing.status_code, 400, missing.data)
        self.assertIn('请填写该行备注', str(missing.data))
        self.assertFalse(MaterialInbound.objects.exists())

        item['remark'] = '供应商实际送来105件'
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        line = MaterialInboundLine.objects.get(inbound_id=response.data['data']['id'])
        self.assertEqual(line.received_quantity, Decimal('105'))
        self.assertEqual(line.purchased_quantity_snapshot, Decimal('100'))
        self.assertEqual(line.remark, item['remark'])
        self.assertFalse(MaterialStockMovement.objects.filter(source_line_id=line.pk).exists())

        confirmed = self.confirm_quality(response)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        line.refresh_from_db()
        self.assertEqual(line.accepted_quantity, Decimal('105'))
        movement = MaterialStockMovement.objects.select_related('balance').get(source_line_id=line.pk)
        self.assertEqual(movement.quantity, Decimal('105'))
        self.assertEqual(movement.balance.quantity, Decimal('105'))
        eligible = self.client.get('/api/v1/material-inventory/eligible-lines/', {
            'purchase_order_id': self.purchase_line.purchase_order_id,
        })
        self.assertEqual(eligible.status_code, 200, eligible.data)
        self.assertEqual(eligible.data['data'], [])
        self.assertEqual(self.receive(quantity='105', expected='100').status_code, 409)
        self.assertEqual(MaterialInbound.objects.count(), 1)

    def test_receipt_list_keeps_each_record_and_reflects_partial_and_full_returns(self):
        root = '/api/v1/material-inventory/purchase-receipt-records/'
        first = self.receive(expected='10.5000')
        second = self.receive(expected='6.2500')
        pending_ids = []
        for received, returned, result in [(first, '1.0000', 'CONFIRMED'), (second, '4.2500', 'RETURNED')]:
            self.assertEqual(received.status_code, 201, received.data)
            record = received.data['data']
            pending_ids.append(str(record['id']))
            filters = {'section': record['material_section'] or 'UNASSIGNED', 'q': record['inbound_number']}
            listing = self.client.get(root, {**filters, 'status': 'PENDING_QUALITY'})
            self.assertEqual(listing.status_code, 200, listing.data)
            self.assertEqual([str(row['id']) for row in listing.data['data']], [str(record['id'])])
            self.assertTrue(listing.data['data'][0]['can_quality_confirm'])
            confirmed = self.confirm_quality(received, return_quantity=returned)
            self.assertEqual(confirmed.status_code, 200, confirmed.data)
            listing = self.client.get(root, {**filters, 'status': result})
            self.assertEqual(listing.status_code, 200, listing.data)
            self.assertEqual([str(row['id']) for row in listing.data['data']], [str(record['id'])])
            self.assertFalse(listing.data['data'][0]['can_quality_confirm'])
            detail = self.client.get(root + f"{record['id']}/")
            self.assertEqual(detail.status_code, 200, detail.data)
            self.assertEqual(detail.data['data']['status_display'], '已入库' if result == 'CONFIRMED' else '全部退货')
            self.assertEqual(len(detail.data['data']['lines']), 1)
        self.assertEqual(MaterialInbound.objects.filter(pk__in=pending_ids).count(), 2)

    def test_quality_confirmation_records_term_from_the_inbound_business_date(self):
        today = timezone.localdate()
        inbound_date = today.replace(day=1) - timedelta(days=1)
        url = f"/api/v1/suppliers/{self.supplier.pk}/"
        response = self.client.patch(url, {"payment_term": {
            "months": 1, "effective_month": inbound_date.strftime("%Y-%m"), "basis": "材料采购协议",
        }}, format="json", HTTP_IF_MATCH=self.client.get(url)["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        version_id = response.data["data"]["payment_term_versions"][0]["id"]
        receipt = self.receive(inbound_date=inbound_date.isoformat())
        self.assertEqual(receipt.status_code, 201, receipt.data)
        inbound = MaterialInbound.objects.get(pk=receipt.data["data"]["id"])
        self.assertFalse(inbound.purchase_payables.exists())
        confirmed = self.confirm_quality(receipt, return_quantity="1.2500")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        payable = inbound.purchase_payables.get()
        self.assertEqual((str(payable.payment_term_id), payable.payment_term_months, payable.due_month),
                         (version_id, 1, date(today.year, today.month, 1)))
        self.assertEqual(payable.lines.get().accepted_quantity, Decimal("3.0000"))

    def test_legacy_saved_material_number_works_without_bom(self):
        PurchaseOrderLine.objects.filter(pk=self.purchase_line.pk).update(
            calculation_snapshot={}, bom_line=None, bom=None, part_name_snapshot='部件名称与原料名称不同')
        response = self.receive()
        self.assertEqual(response.status_code, 201, response.data)
        line = MaterialInboundLine.objects.get(inbound_id=response.data['data']['id'])
        self.assertEqual(line.raw_material_information_id, self.raw_material.pk)
        self.assertEqual(self.confirm_quality(response).status_code, 200)

    def test_legacy_quality_uses_purchase_number_without_bom(self):
        response = self.receive()
        self.assertEqual(response.status_code, 201, response.data)
        MaterialInboundLine.objects.filter(inbound_id=response.data['data']['id']).update(raw_material_information=None)
        PurchaseOrderLine.objects.filter(pk=self.purchase_line.pk).update(calculation_snapshot={}, bom_line=None, bom=None)
        confirmed = self.confirm_quality(response)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(MaterialInboundLine.objects.get().raw_material_information_id, self.raw_material.pk)
        self.assertEqual(MaterialStockMovement.objects.get().balance.raw_material_id, self.raw_material.pk)

    def test_missing_saved_identity_does_not_fall_back_to_bom(self):
        PurchaseOrderLine.objects.filter(pk=self.purchase_line.pk).update(calculation_snapshot={}, raw_material_snapshot='')
        response = self.receive()
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['error']['code'], 'PURCHASE_MATERIAL_IDENTITY_MISSING')
        self.assertFalse(MaterialInbound.objects.exists())
        self.assertFalse(MaterialStockMovement.objects.exists())

    def test_partial_receipt_reuses_frozen_material_without_bom(self):
        response = self.receive()
        self.assertEqual(response.status_code, 201, response.data)
        PurchaseOrderLine.objects.filter(pk=self.purchase_line.pk).update(
            calculation_snapshot={}, raw_material_snapshot='', bom_line=None, bom=None)
        second = self.receive(quantity='1.0000', expected='6.2500')
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(set(MaterialInboundLine.objects.values_list('raw_material_information_id', flat=True)),
                         {self.raw_material.pk})

    def test_purchase_snapshot_conflict_with_existing_receipt_is_atomic(self):
        response = self.receive()
        self.assertEqual(response.status_code, 201, response.data)
        other = self.change_bom_material()
        PurchaseOrderLine.objects.filter(pk=self.purchase_line.pk).update(calculation_snapshot={
            'raw_material_id': str(other.pk), 'unit_id': str(other.unit_id)})
        second = self.receive(quantity='1.0000', expected='6.2500')
        self.assertEqual(second.status_code, 409, second.data)
        self.assertEqual(MaterialInbound.objects.count(), 1)
        self.assertEqual(MaterialInboundLine.objects.count(), 1)
        self.assertFalse(MaterialStockMovement.objects.exists())

    def test_quality_rejects_purchase_identity_conflict_even_when_all_returned(self):
        response = self.receive()
        self.assertEqual(response.status_code, 201, response.data)
        other = self.change_bom_material()
        PurchaseOrderLine.objects.filter(pk=self.purchase_line.pk).update(calculation_snapshot={
            'raw_material_id': str(other.pk), 'unit_id': str(other.unit_id)})
        confirmed = self.confirm_quality(response, return_quantity='4.2500')
        self.assertEqual(confirmed.status_code, 409, confirmed.data)
        self.assertEqual(MaterialInbound.objects.get().status, MaterialInboundStatus.PENDING_QUALITY)
        self.assertEqual(MaterialInboundLine.objects.get().return_quantity, Decimal('0'))
        self.assertFalse(MaterialStockMovement.objects.exists())

    def test_stock_lookup_uses_saved_purchase_number_and_returns_none_when_missing(self):
        from ..stock_services import inbound_line_material
        self.change_bom_material()
        self.purchase_line.calculation_snapshot = {}
        line = MaterialInboundLine(purchase_order_line=self.purchase_line)
        self.assertEqual(inbound_line_material(line).pk, self.raw_material.pk)
        self.purchase_line.raw_material_snapshot = ''
        self.assertIsNone(inbound_line_material(line))

    def test_stock_lookup_reuses_other_frozen_receipt_without_writing_legacy_row(self):
        from ..stock_services import inbound_line_material
        response = self.receive()
        self.assertEqual(response.status_code, 201, response.data)
        second = self.receive(quantity='1.0000', expected='6.2500')
        self.assertEqual(second.status_code, 201, second.data)
        MaterialInboundLine.objects.filter(inbound_id=response.data['data']['id']).update(raw_material_information=None)
        PurchaseOrderLine.objects.filter(pk=self.purchase_line.pk).update(calculation_snapshot={}, raw_material_snapshot='')
        line = MaterialInboundLine.objects.select_related('purchase_order_line').get(inbound_id=response.data['data']['id'])
        self.assertEqual(inbound_line_material(line).pk, self.raw_material.pk)
        line.refresh_from_db()
        self.assertIsNone(line.raw_material_information_id)

    def test_stock_lookup_rejects_conflict_with_other_frozen_receipt(self):
        from ..stock_services import inbound_line_material
        response = self.receive()
        self.assertEqual(response.status_code, 201, response.data)
        other = self.change_bom_material()
        self.purchase_line.calculation_snapshot = {'raw_material_id': str(other.pk)}
        line = MaterialInboundLine(purchase_order_line=self.purchase_line)
        self.assertIsNone(inbound_line_material(line))
