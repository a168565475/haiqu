"""采购收货与质检只使用已保存的采购材料，不回读 BOM 重新定料。"""
from decimal import Decimal

from django.test import override_settings
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
