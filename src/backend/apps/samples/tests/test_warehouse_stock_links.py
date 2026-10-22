"""仓库来源关联至实际扣库；仅运行于本任务独占 PostgreSQL 测试库。"""
from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.inventory.models import MaterialStockMovement, PublicStockMovement, WarehouseZone
from apps.inventory.stock_services import credit_material_stock
from .test_sample_issue_all import AllIssueApiHelpers, SampleAllPipeIssueTests, SampleAllOtherMaterialIssueTests


class ReviewHelpers:
    def review_state(self):
        # 复用的采购夹具已进入采购阶段；仓库首次核对不能残留采购请求。
        record = self.procurement.material_request
        self.procurement.delete()
        record.reviewed_at = None
        record.save(update_fields=['reviewed_at'])
        self.sample.status = 'WAREHOUSE_PENDING'
        self.sample.save(update_fields=['status', 'updated_at'])
        self.review_url = f'/api/v1/sample-requests/{self.sample.pk}/warehouse-review/'
        return self.client.get(self.review_url)

    def save_link(self, state, balance, quantity, supply, *, submit=True):
        return self.client.put(self.review_url, {'submit': submit, 'draft': {'notes': '', 'lines': [{
            'key': self.key, 'supplyQuantity': supply, 'inventoryAllocations': [{
                'balanceId': str(balance.pk), 'stockMode': 'PUBLIC_V2' if hasattr(balance, 'stock_kind') else 'LEGACY',
                'quantity': quantity,
            }],
        }]}}, format='json', HTTP_IF_MATCH=state['ETag'])


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class WarehousePipeLinkTests(ReviewHelpers, AllIssueApiHelpers, APITestCase):
    stock = SampleAllPipeIssueTests.stock

    def setUp(self):
        SampleAllPipeIssueTests.setUp(self)
        self.set_demand('12', '0')

    def test_query_save_reload_and_issue_only_selected_zone(self):
        first = self.stock(3)
        zone = WarehouseZone.objects.create(warehouse=first.zone.warehouse, zone_name='选定供料区')
        chosen = self.stock(2, zone_id=zone.pk)
        state = self.review_state()
        candidates = self.client.get(f'/api/v1/sample-requests/{self.sample.pk}/warehouse-inventory/')
        self.assertEqual(candidates.status_code, 200, candidates.data)
        self.assertEqual({row['balanceId'] for row in candidates.data['data']['lines'][0]['candidates']}, {str(first.pk), str(chosen.pk)})
        saved = self.save_link(state, chosen, '2', '12')
        self.assertEqual(saved.status_code, 200, saved.data)
        chosen.refresh_from_db()
        self.assertEqual(chosen.quantity, 2)  # 核对只保存关联，不扣库。
        reloaded = self.client.get(self.review_url)
        linked = reloaded.data['data']['draft']['lines'][0]['inventoryAllocations'][0]
        self.assertEqual((linked['balanceId'], Decimal(linked['rawBarLengthM'])), (str(chosen.pk), Decimal('6')))
        started = self.initiate()
        self.assertEqual(started.data['data']['lines'][0]['pipeBatches'][0]['balanceId'], str(chosen.pk))
        request_id = str(uuid.uuid4())
        confirmed = self.confirm(started, request_id)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(self.confirm(started, request_id).status_code, 200)
        first.refresh_from_db(); chosen.refresh_from_db()
        self.assertEqual((first.quantity, chosen.quantity), (3, 0))
        self.assertEqual(PublicStockMovement.objects.filter(source_type='SAMPLE_MATERIAL_ISSUE').count(), 1)

    def test_invalid_identity_units_quantity_and_duplicate_are_rejected(self):
        balance = self.stock(2)
        state = self.review_state()
        for quantity, supply, expected in [('1.5', '9', 400), ('3', '12', 409), ('1', '12', 400)]:
            result = self.save_link(state, balance, quantity, supply, submit=False)
            self.assertEqual(result.status_code, expected, result.data)
        record = self.procurement.material_request
        record.draft['lines'][0]['rawMaterialId'] = str(uuid.uuid4())
        record.save(update_fields=['draft'])
        result = self.save_link(state, balance, '2', '12')
        self.assertEqual(result.status_code, 409, result.data)
        balance.refresh_from_db(); self.assertEqual(balance.quantity, 2)

    def test_repeated_demand_cannot_overallocate_same_balance(self):
        balance = self.stock(2)
        record = self.procurement.material_request
        other = {**self.demand, 'key': str(uuid.uuid4())}
        record.draft['lines'].append(other); record.save(update_fields=['draft'])
        state = self.review_state()
        lines = [{'key': row['key'], 'supplyQuantity': '12', 'inventoryAllocations': [
            {'balanceId': str(balance.pk), 'stockMode': 'PUBLIC_V2', 'quantity': '2'}
        ]} for row in record.draft['lines']]
        result = self.client.put(self.review_url, {'submit': False, 'draft': {'lines': lines, 'notes': ''}}, format='json', HTTP_IF_MATCH=state['ETag'])
        self.assertEqual(result.status_code, 409, result.data)

    def test_insufficient_selected_stock_never_falls_back_to_another_zone(self):
        selected = self.stock(2)
        zone = WarehouseZone.objects.create(warehouse=selected.zone.warehouse, zone_name='不可替代区')
        other = self.stock(5, zone_id=zone.pk)
        saved = self.save_link(self.review_state(), selected, '2', '12')
        self.assertEqual(saved.status_code, 200, saved.data)
        self.initiate()
        selected.quantity = 1; selected.meter_quantity = 6; selected.version += 1
        selected.save(update_fields=['quantity', 'meter_quantity', 'version'])
        fresh = self.client.get(self.issue_url)
        self.assertFalse(fresh.data['data']['canConfirm'])
        self.assertIn('关联库区', str(fresh.data['data']['blockers']))
        self.assertEqual(self.confirm(fresh).status_code, 409)
        other.refresh_from_db(); self.assertEqual(other.quantity, 5)
        self.assertFalse(PublicStockMovement.objects.filter(source_type='SAMPLE_MATERIAL_ISSUE').exists())

    def test_query_requires_warehouse_permission(self):
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        result = self.client.get(f'/api/v1/sample-requests/{self.sample.pk}/warehouse-inventory/')
        self.assertEqual(result.status_code, 403)

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=False)
    def test_legacy_pipe_link_stays_in_legacy_ledger(self):
        balance = self.stock(2, public=False)
        result = self.save_link(self.review_state(), balance, '2', '12')
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(self.confirm(self.initiate()).status_code, 200)
        balance.refresh_from_db(); self.assertEqual(balance.quantity, 0)
        self.assertFalse(PublicStockMovement.objects.filter(source_type='SAMPLE_MATERIAL_ISSUE').exists())


class WarehouseOtherLinkTests(ReviewHelpers, AllIssueApiHelpers, APITestCase):
    def setUp(self):
        SampleAllOtherMaterialIssueTests.setUp(self)
        self.demand['unitId'] = str(self.raw_material.unit_id)
        self.set_demand('4', '0')

    def test_non_pipe_actual_issue_uses_chosen_zone(self):
        zone = WarehouseZone.objects.get(pk=self.zone_id)
        chosen_zone = WarehouseZone.objects.create(warehouse=zone.warehouse, zone_name='五金指定区')
        balances = []
        for location in (zone, chosen_zone):
            movement = credit_material_stock(raw_material=self.raw_material, unit=self.raw_material.unit,
                zone=location, quantity=5, source_type='QA_OPENING', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(), actor_employee=self.employee)
            balances.append(movement.balance)
        saved = self.save_link(self.review_state(), balances[1], '4', '4')
        self.assertEqual(saved.status_code, 200, saved.data)
        started = self.initiate()
        self.assertTrue(started.data['data']['canConfirm'], started.data)
        confirmed = self.confirm(started)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        for balance in balances: balance.refresh_from_db()
        self.assertEqual([balance.quantity for balance in balances], [5, 1])
        self.assertEqual(MaterialStockMovement.objects.get(source_type='SAMPLE_MATERIAL_ISSUE').balance_id, balances[1].pk)
