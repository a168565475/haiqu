from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.boms.material_flow_calculations import pipe_plan
from apps.boms.models import BomSectionType, BomStatus
from apps.inventory.models import MaterialInbound, MaterialInboundLine
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.production_tasks.selectors import accessible_production_tasks
from apps.procurement.models import PurchaseGroup, PurchaseOrder, PurchaseReturn, PurchaseReturnLine
from apps.reference_data.models import ProductionUnit, ProductCategory
from apps.procurement.tracking_permissions import employee_can_view_task
from apps.procurement.tracking_selectors import _receipt_summaries, arrival_rows, coverage_rows
from apps.workshop_config.models import Workshop, Craft

from . import test_purchase_groups as group_tests
from . import test_purchase_order_api as order_tests


@override_settings(PURCHASE_TRACKING_ENABLED=False, PURCHASE_TRACKING_POLICY_ENABLED=False)
class TrackingQueryTests(APITestCase):
    make_task = order_tests.PurchaseOrderApiTests.make_task
    make_product_line = order_tests.PurchaseOrderApiTests.make_product_line
    make_bom = order_tests.PurchaseOrderApiTests.make_bom
    get_source = order_tests.PurchaseOrderApiTests.get_source
    batch = group_tests.PurchaseGroupApiTests.batch
    detail = group_tests.PurchaseGroupApiTests.detail

    def setUp(self):
        group_tests.PurchaseGroupApiTests.setUp(self)

    def batch_payload(self, *args, **kwargs):
        payload = group_tests.PurchaseGroupApiTests.batch_payload(self, *args, **kwargs)
        for line in payload['lines']:
            line['delivery_date'] = '2026-11-15'
        return payload

    def schedule(self, product=None):
        product = product or self.product_line
        task = product.production_task
        schedule = ProductionSchedule.objects.create(schedule_number=f'TRACK-{task.pk.hex[:12].upper()}',
            production_task=task, source_revision_hash='test', client_request_id=uuid4(), request_payload_hash='test',
            created_by_employee=self.employee, updated_by_employee=self.employee)
        scheduled_product = ProductionScheduleProduct.objects.create(schedule=schedule, product_line=product, line_number=1,
            planned_quantity=1, source_quantity_snapshot=product.quantity, unit=product.unit,
            unit_name_snapshot='PCS', material_inbound_date=date(2026, 11, 10), metal_return_date=date(2026, 11, 11),
            sewing_return_date=date(2026, 11, 12), finished_inbound_date=date(2026, 11, 13), source_revision_hash='test')
        workshop = Workshop.objects.first()
        craft, _ = Craft.objects.get_or_create(craft_type='INTERNAL', name='跟踪默认测试工艺', defaults={'workshop': workshop})
        ProductionScheduleProductCraft.objects.create(schedule_product=scheduled_product, craft=craft,
            craft_type_snapshot='INTERNAL', craft_name_snapshot=craft.name)
        return scheduled_product

    def rows(self, task=None, **kwargs):
        return coverage_rows(task_ids=[(task or self.task).pk], **kwargs)

    def timing_fixture(self):
        from apps.procurement.tracking_models import PurchaseTrackingPolicy
        from apps.procurement.tracking_rules import BEIJING
        now = datetime(2026, 11, 8, 10, 30, tzinfo=BEIJING)
        self.bom.confirmed_at = now - timedelta(days=2)
        self.bom.save(update_fields=['confirmed_at'])
        frozen = PurchaseGroup.objects.get(pk=self.group_id).lines.get()
        frozen.source_snapshot = {**frozen.source_snapshot, 'section_title_snapshot': '五金件'}
        frozen.save(update_fields=['source_snapshot'])
        policy = PurchaseTrackingPolicy.objects.get(key='default')
        policy.bom_timeout_days = 2
        policy.category_lead_days = {key: 2 for key in policy.category_lead_days}
        policy.save()
        return now, policy

    @override_settings(PURCHASE_TRACKING_POLICY_ENABLED=True)
    def test_unscheduled_timeout_uses_full_days_and_reaches_notification_candidates(self):
        from apps.procurement.tracking_rules import issue_candidates
        now, _ = self.timing_fixture()
        before = self.rows(now=now - timedelta(microseconds=1))[0]
        self.assertNotIn('BOM_PURCHASE_TIMEOUT', {risk['code'] for risk in before['risks']})
        row = self.rows(now=now)[0]
        self.assertFalse(row['scheduled'])
        self.assertEqual(row['risks'][0]['code'], 'BOM_PURCHASE_TIMEOUT')
        self.assertEqual(datetime.fromisoformat(row['bom_purchase_due_at']), now)
        self.assertEqual(issue_candidates([row], 'coverage')[0]['code'], 'BOM_PURCHASE_TIMEOUT')

    @override_settings(PURCHASE_TRACKING_POLICY_ENABLED=True)
    def test_category_lead_change_and_partial_purchase_recompute_deadline(self):
        now, policy = self.timing_fixture()
        self.schedule()
        self.batch('60')
        row = self.rows(now=now)[0]
        self.assertEqual(row['material_category_key'], 'HARDWARE')
        self.assertEqual(row['latest_purchase_date'], '2026-11-08')
        self.assertEqual(row['purchase_days_remaining'], 0)
        self.assertEqual(row['risks'][0]['code'], 'PURCHASE_DUE_TODAY')
        self.assertEqual(Decimal(row['remaining_quantity']), Decimal('40'))
        policy.category_lead_days['HARDWARE'] = 4
        policy.save(update_fields=['category_lead_days'])
        row = self.rows(now=now)[0]
        self.assertEqual(row['latest_purchase_date'], '2026-11-06')
        self.assertEqual(row['risks'][0]['code'], 'PURCHASE_OVERDUE')
        self.batch('40')
        row = self.rows(now=now)[0]
        self.assertEqual([risk['code'] for risk in row['risks']], ['COVERED'])
        self.assertEqual(self.client.get('/api/v1/purchase-tracking/coverage/').data['data'], [])

    @override_settings(PURCHASE_TRACKING_POLICY_ENABLED=True)
    def test_missing_confirmation_and_category_are_visible(self):
        now, _ = self.timing_fixture()
        self.schedule()
        self.bom.confirmed_at = None
        self.bom.save(update_fields=['confirmed_at'])
        frozen = PurchaseGroup.objects.get(pk=self.group_id).lines.get()
        frozen.source_snapshot['section_title_snapshot'] = '未知历史分类'
        frozen.save(update_fields=['source_snapshot'])
        row = self.rows(now=now)[0]
        codes = {risk['code'] for risk in row['risks']}
        self.assertTrue({'BOM_CONFIRMATION_UNKNOWN', 'PURCHASE_RULE_UNKNOWN'} <= codes)
        self.assertIsNone(row['bom_purchase_due_at'])
        self.assertIsNone(row['latest_purchase_date'])
        self.assertNotIn('BOM_PURCHASE_TIMEOUT', codes)

    @override_settings(PURCHASE_TRACKING_POLICY_ENABLED=True)
    def test_unreliable_quantity_does_not_claim_purchase_timeout(self):
        now, _ = self.timing_fixture()
        self.bom_line.budget_quantity = '150'
        self.bom_line.save(update_fields=['budget_quantity'])
        row = self.rows(now=now)[0]
        self.assertIsNone(row['remaining_quantity'])
        self.assertNotIn('BOM_PURCHASE_TIMEOUT', {risk['code'] for risk in row['risks']})
        self.assertIn('DEMAND_CHANGED', {risk['code'] for risk in row['risks']})

    @override_settings(PURCHASE_TRACKING_POLICY_ENABLED=True)
    def test_urgent_order_sort_keeps_all_material_rows_together(self):
        from apps.procurement.api.tracking_views import _sort_coverage_rows
        def row(task, material, rank, due):
            return {'production_task_id': task, 'task_number': task, 'row_key': task + material,
                'material_name': material, 'latest_purchase_date': due, 'risks': [{'rank': rank}]}
        rows = [row('A', '1', 40, '2026-11-10'), row('Z', '2', 40, '2026-11-12'),
                row('M', '1', 95, None), row('Z', '1', 110, '2026-11-06')]
        _sort_coverage_rows(rows)
        self.assertEqual([row['row_key'] for row in rows], ['Z1', 'Z2', 'M1', 'A1'])

    def inbound(self, batch, received, *, accepted=None, status='CONFIRMED'):
        order = PurchaseOrder.objects.get(pk=batch['id'])
        line = order.lines.get()
        received = Decimal(received)
        accepted = received if accepted is None else Decimal(accepted)
        record = MaterialInbound.objects.create(inbound_number=f'TR-{uuid4().hex[:16].upper()}', purchase_order=order,
            status=status, received_by_employee=self.employee)
        item = MaterialInboundLine.objects.create(inbound=record, purchase_order_line=line,
            raw_material_information=self.inventory_material, zone=self.zone, received_quantity=received,
            accepted_quantity=accepted, return_quantity=received-accepted, source_unit_text_snapshot=line.source_unit_text,
            purchased_quantity_snapshot=line.actual_purchase_quantity)
        return record, item

    def test_unbuilt_group_and_product_specific_partial_schedule_are_visible(self):
        other = self.make_product_line(self.task, line_number=2)
        self.make_bom(other, section_type=BomSectionType.ACCESSORY, budget_quantity='40')
        self.schedule(other)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        scheduled = next(row for row in rows if row['product_line_id'] == str(other.pk))
        self.assertEqual(Decimal(scheduled['required_quantity']), Decimal('40'))
        self.assertEqual(scheduled['risks'][0]['code'], 'SCHEDULED_UNPURCHASED')
        self.assertIsNone(scheduled['purchase_group_id'])
        self.assertFalse(next(row for row in rows if row['product_line_id'] == str(self.product_line.pk))['scheduled'])

    def test_coverage_returns_bom_time_order_delivery_and_frozen_material_attributes(self):
        snapshot = PurchaseGroup.objects.get(pk=self.group_id).lines.get().source_snapshot
        self.bom_line.specification = '当前规格已修改'
        self.bom_line.save(update_fields=['specification'])
        response = self.client.get('/api/v1/purchase-tracking/coverage/')
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data['data'][0]
        self.assertEqual(datetime.fromisoformat(row['bom_created_at']), self.bom.created_at)
        self.assertEqual(row['order_delivery_date'], self.task.delivery_date.isoformat())
        self.assertEqual(row['material_attributes_snapshot'], snapshot['material_attributes_snapshot'])
        self.assertEqual(row['part_name'], snapshot['part_name_snapshot'])
        self.assertEqual(row['material'], snapshot['material_snapshot'])
        self.assertEqual(row['specification'], snapshot['specification_snapshot'])

    def test_coverage_without_group_uses_bom_material_attributes(self):
        task = self.make_task('TRACK-ATTRIBUTES')
        product = self.make_product_line(task)
        bom, line = self.make_bom(product, section_type=BomSectionType.ACCESSORY, budget_quantity='25')
        line.section.title = '五金类'
        line.section.save(update_fields=['title'])
        line.raw_values['hardware_color'] = '黑色'
        line.save(update_fields=['raw_values'])
        row = self.rows(task)[0]
        self.assertEqual(row['bom_created_at'], bom.created_at.isoformat())
        self.assertEqual(row['order_delivery_date'], task.delivery_date.isoformat())
        fields = row['material_attributes_snapshot']['fields']
        self.assertIn({'key': 'hardware_color', 'label': '颜色', 'value': '黑色'}, fields)
        self.assertEqual(row['material_selection_snapshot'], {})

    def test_unknown_product_retains_dates_without_inventing_material_attributes(self):
        bom, _ = self.make_bom(self.product_line, version=2, section_type=BomSectionType.ACCESSORY, budget_quantity='100')
        row = self.rows()[0]
        self.assertEqual(row['bom_created_at'], bom.created_at.isoformat())
        self.assertEqual(row['order_delivery_date'], self.task.delivery_date.isoformat())
        self.assertEqual(row['material_attributes_snapshot'], {})
        self.assertEqual(row['material_selection_snapshot'], {})
        self.assertEqual(row['part_name'], '')
        type(bom).objects.filter(product_line=self.product_line).update(archived_at=timezone.now())
        self.assertIsNone(self.rows()[0]['bom_created_at'])

    def test_draft_does_not_cover_and_confirmation_clears_shortage(self):
        self.schedule()
        batch = self.batch('60')
        self.batch('40', confirm=False)
        row = self.rows()[0]
        self.assertEqual(Decimal(row['purchased_quantity']), Decimal('60'))
        self.assertEqual(Decimal(row['remaining_quantity']), Decimal('40'))
        self.assertEqual(row['risks'][0]['code'], 'SCHEDULED_SHORT')
        draft = PurchaseOrder.objects.get(purchase_group_id=self.group_id, status='DRAFT')
        response = self.client.post(f'/api/v1/purchase-orders/{draft.pk}/confirm/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.rows()[0]['risks'][0]['code'], 'COVERED')

    def test_bom_in_place_change_is_detected_but_remark_is_not(self):
        self.bom_line.raw_values = {**self.bom_line.raw_values, 'tracking_test_note': '说明变化'}
        self.bom_line.save(update_fields=['raw_values', 'updated_at'])
        self.assertTrue(self.rows()[0]['source_reliable'])
        self.bom_line.budget_quantity = '150'
        self.bom_line.save(update_fields=['budget_quantity', 'updated_at'])
        row = self.rows()[0]
        self.assertFalse(row['source_reliable'])
        self.assertIn('DEMAND_CHANGED', {risk['code'] for risk in row['risks']})
        self.assertIsNone(row['remaining_quantity'])

    def test_pending_latest_bom_never_falls_back_to_confirmed_snapshot(self):
        self.bom.status = BomStatus.PENDING_CONFIRMATION
        self.bom.save(update_fields=['status', 'updated_at'])
        row = self.rows()[0]
        self.assertFalse(row['source_reliable'])
        self.assertEqual(row['risks'][0]['code'], 'DEMAND_UNKNOWN')
        self.assertIsNone(row['remaining_quantity'])

    def test_closed_task_and_removed_schedule_do_not_generate_scheduled_shortage(self):
        scheduled = self.schedule()
        scheduled.crafts.update(removed_at=timezone.now(), removed_by_employee=self.employee)
        scheduled.removed_at = timezone.now()
        scheduled.removed_by_employee = self.employee
        scheduled.save(update_fields=['removed_at', 'removed_by_employee'])
        ProductionSchedule.objects.filter(pk=scheduled.schedule_id).update(record_status='VOID', void_reason='撤销测试排产',
            voided_at=timezone.now(), voided_by_employee=self.employee)
        self.assertFalse(self.rows()[0]['scheduled'])
        self.task.status = 'COMPLETED'
        self.task.save(update_fields=['status'])
        self.assertEqual(self.rows(), [])
        row = self.rows(include_history=True)[0]
        self.assertTrue(row['is_history'])
        self.assertFalse(row['scheduled'])

    def test_arrivals_count_physical_receipts_and_keep_returns_separate(self):
        batch = self.batch('100')
        self.inbound(batch, '70', accepted='50')
        self.inbound(batch, '30', status='PENDING_QUALITY')
        row = arrival_rows(task_ids=[self.task.pk], today=date(2026, 12, 1))[0]
        self.assertEqual([Decimal(row[key]) for key in ['received_quantity', 'accepted_quantity', 'pending_quality_quantity',
                         'unreceived_quantity', 'return_quantity']], list(map(Decimal, ['100', '50', '30', '0', '20'])))
        self.assertTrue(row['return_pending'])
        self.assertEqual({risk['code'] for risk in row['risks']}, {'ARRIVED', 'RETURN_PENDING'})

    def test_arrival_api_returns_frozen_purchase_attributes_without_current_bom_fallback(self):
        batch = self.batch('100')
        line = PurchaseOrder.objects.get(pk=batch['id']).lines.get()
        line.material_selection_snapshot = {'schema_version': 1, 'category_key': 'HARDWARE', 'template_key': 'HARDWARE',
            'name': '冻结品名', 'attributes': {'color': '黑色'}, 'unit_name': line.source_unit_text}
        line.material_attributes_snapshot = {'fields': [{'key': 'color', 'label': '颜色', 'value': '冻结黑色'}]}
        line.save(update_fields=['material_selection_snapshot', 'material_attributes_snapshot'])
        self.bom_line.part_name = '当前BOM已更名'
        self.bom_line.material = '当前BOM新材质'
        self.bom_line.specification = '当前BOM新规格'
        self.bom_line.raw_values = {**self.bom_line.raw_values, 'hardware_color': '白色'}
        self.bom_line.save(update_fields=['part_name', 'material', 'specification', 'raw_values'])

        response = self.client.get('/api/v1/purchase-tracking/arrivals/')
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data['data'][0]
        self.assertEqual(row['material_selection_snapshot'], line.material_selection_snapshot)
        self.assertEqual(row['material_attributes_snapshot'], line.material_attributes_snapshot)
        self.assertEqual(row['part_name'], line.part_name_snapshot)
        self.assertEqual(row['material'], line.material_snapshot)
        self.assertEqual(row['raw_material'], line.raw_material_snapshot)
        self.assertEqual(row['specification'], line.specification_snapshot)
        self.assertEqual(row['delivery_date'], line.delivery_date.isoformat())

        # 历史采购未保存的属性保持缺失，不借用后续修改过的 BOM 补写展示。
        type(line).objects.filter(pk=line.pk).update(material_selection_snapshot={}, material_attributes_snapshot={})
        row = self.client.get('/api/v1/purchase-tracking/arrivals/').data['data'][0]
        self.assertEqual(row['material_selection_snapshot'], {})
        self.assertEqual(row['material_attributes_snapshot'], {})
        self.assertEqual(row['part_name'], line.part_name_snapshot)

    def test_arrival_api_keeps_production_orders_together_across_purchase_batches(self):
        original_group_id, original_line_id = self.group_id, self.line_id
        first = self.batch('10')
        other_task = self.make_task('ZZ-ARRIVAL-SORT')
        other_product = self.make_product_line(other_task)
        other_bom, _ = self.make_bom(other_product, section_type=BomSectionType.ACCESSORY, budget_quantity='100')
        source = self.get_source(other_task).data['data']
        group = self.client.post('/api/v1/purchase-groups/', {'production_task_id': str(other_task.pk),
            'bom_id': str(other_bom.pk), 'source_revision': source['source_revision']}, format='json')
        self.assertEqual(group.status_code, 201, group.data)
        self.group_id = group.data['data']['id']
        self.line_id = group.data['data']['progress']['lines'][0]['id']
        middle = self.batch('10')
        self.group_id, self.line_id = original_group_id, original_line_id
        last = self.batch('10')
        for batch, order_number in zip((first, middle, last), ('SORT-001', 'SORT-002', 'SORT-003')):
            PurchaseOrder.objects.filter(pk=batch['id']).update(order_number=order_number)

        response = self.client.get('/api/v1/purchase-tracking/arrivals/')
        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data['data']
        self.assertEqual([row['purchase_order_id'] for row in rows], [first['id'], last['id'], middle['id']])
        self.assertEqual([row['production_task_id'] for row in rows], [str(self.task.pk), str(self.task.pk), str(other_task.pk)])

    def test_raw_completed_batch_history_does_not_stop_other_active_batch(self):
        first, second = self.batch('60'), self.batch('40')
        PurchaseOrder.objects.filter(pk=first['id']).update(status='COMPLETED', completed_at=timezone.now())
        PurchaseGroup.objects.filter(pk=self.group_id).update(manual_completed_at=timezone.now())
        current = arrival_rows(task_ids=[self.task.pk], today=date(2026, 12, 1))
        self.assertEqual([row['purchase_order_id'] for row in current], [second['id']])
        historical = arrival_rows(task_ids=[self.task.pk], today=date(2026, 12, 1), include_history=True)
        ended = next(row for row in historical if row['purchase_order_id'] == first['id'])
        self.assertEqual(Decimal(ended['unreceived_quantity']), Decimal('60'))
        self.assertEqual(ended['risks'][0]['code'], 'ENDED')

    def test_unknown_identity_is_visible_and_does_not_invent_arrival_or_coverage(self):
        batch = self.batch('40')
        PurchaseOrder.objects.get(pk=batch['id']).lines.update(calculation_snapshot={}, raw_material_snapshot='UNRESOLVED')
        row = arrival_rows(task_ids=[self.task.pk], today=date(2026, 12, 1))[0]
        self.assertFalse(row['source_reliable'])
        self.assertIn('ARRIVAL_UNKNOWN', {risk['code'] for risk in row['risks']})
        self.assertFalse(self.rows()[0]['source_reliable'])

    def test_api_rejects_unknown_filters_and_limits_and_filters_row_key(self):
        for query in [{'bogus': '1'}, {'page_size': 101}, {'page': 0}, {'risk': 'BAD'}, {'production_task_id': 'bad'}]:
            self.assertEqual(self.client.get('/api/v1/purchase-tracking/coverage/', query).status_code, 400)
        self.assertEqual(self.client.get('/api/v1/purchase-tracking/coverage/', {'row_key': 'missing'}).data['data'], [])
        response = self.client.get('/api/v1/purchase-tracking/coverage/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['meta']['total'], 1)
        with CaptureQueriesContext(connection) as queries:
            self.client.get('/api/v1/purchase-tracking/coverage/')
        self.assertFalse(any(query['sql'].lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ')) for query in queries))

    def test_api_hides_arrived_and_covered_rows_before_pagination(self):
        batch = self.batch('100')
        self.inbound(batch, '100')
        arrivals = self.client.get('/api/v1/purchase-tracking/arrivals/')
        self.assertEqual(arrivals.status_code, 200, arrivals.data)
        self.assertEqual(arrivals.data['meta']['total'], 0)

        coverage = self.client.get('/api/v1/purchase-tracking/coverage/')
        self.assertEqual(coverage.status_code, 200, coverage.data)
        self.assertEqual(coverage.data['meta']['total'], 0)

    def test_viewer_without_purchase_permission_gets_no_write_action(self):
        self.user.user_permissions.set(Permission.objects.filter(codename='view_purchaseorder'))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        response = self.client.get('/api/v1/purchase-tracking/coverage/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(any(action['kind'] in {'create_batch', 'create_group'} for action in response.data['data'][0]['actions']))

    def test_scope_and_employee_check_reject_other_tasks_and_inactive_employee(self):
        user = get_user_model().objects.create_user(username='tracking_other')
        employee = Employee.objects.create(user=user, employee_code='TRACK-OTHER', display_name='另一个员工')
        user.user_permissions.add(Permission.objects.get(content_type__app_label='procurement', codename='view_purchaseorder'))
        self.client.force_authenticate(user)
        response = self.client.get('/api/v1/purchase-tracking/coverage/', {'production_task_id': self.task.pk})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data'], [])
        self.assertFalse(employee_can_view_task(employee, self.task.pk))
        self.task.followers.add(employee)
        self.assertTrue(employee_can_view_task(employee, self.task.pk))
        Employee.objects.filter(pk=employee.pk).update(status='INACTIVE')
        self.assertFalse(employee_can_view_task(employee, self.task.pk))

    def test_query_count_does_not_grow_per_purchase_line(self):
        self.batch('10')
        with CaptureQueriesContext(connection) as first:
            arrival_rows(task_ids=[self.task.pk])
        for _ in range(5):
            self.batch('10')
        with CaptureQueriesContext(connection) as expanded:
            arrival_rows(task_ids=[self.task.pk])
        self.assertLessEqual(len(expanded), len(first) + 1)
        print(f'采购跟踪到货查询：1 批次={len(first)}，6 批次={len(expanded)}')

    def test_return_completion_clears_only_return_risk(self):
        batch = self.batch('100')
        record, line = self.inbound(batch, '60', accepted='40')
        returned = PurchaseReturn.objects.create(return_number='TRACK-RETURN', purchase_order_id=batch['id'],
            inbound=record, supplier=self.supplier, supplier_number_snapshot=self.supplier.supplier_number,
            supplier_name_snapshot=self.supplier.supplier_name, generated_by_employee=self.employee, status='COMPLETED')
        PurchaseReturnLine.objects.create(return_order=returned, inbound_line=line, quantity=Decimal('20'))
        row = arrival_rows(task_ids=[self.task.pk], today=date(2027, 1, 1))[0]
        self.assertFalse(row['return_pending'])
        self.assertEqual(Decimal(row['unreceived_quantity']), Decimal('40'))
        self.assertEqual(Decimal(row['return_quantity']), Decimal('20'))
        self.assertEqual(row['risks'][0]['code'], 'OVERDUE')

    def test_unknown_receipt_unit_never_becomes_zero_or_arrived(self):
        batch = self.batch('100')
        _, line = self.inbound(batch, '100')
        MaterialInboundLine.objects.filter(pk=line.pk).update(source_unit_text_snapshot='箱')
        row = arrival_rows(task_ids=[self.task.pk])[0]
        self.assertFalse(row['source_reliable'])
        self.assertIsNone(row['received_quantity'])
        self.assertIsNone(row['unreceived_quantity'])
        self.assertIn('ARRIVAL_UNKNOWN', {risk['code'] for risk in row['risks']})

    def test_latest_new_version_and_unmapped_purchase_are_unknown(self):
        self.make_bom(self.product_line, version=2, section_type=BomSectionType.ACCESSORY, budget_quantity='100')
        row = self.rows()[0]
        self.assertFalse(row['source_reliable'])
        self.assertIsNone(row['remaining_quantity'])
        self.assertEqual(row['risks'][0]['code'], 'DEMAND_CHANGED')

    def test_malformed_frozen_source_is_unknown_not_a_server_error(self):
        PurchaseGroup.objects.get(pk=self.group_id).lines.update(source_snapshot=[])
        row = self.rows()[0]
        self.assertFalse(row['source_reliable'])
        self.assertIsNone(row['remaining_quantity'])

    def test_unmapped_historical_product_does_not_create_false_unpurchased_result(self):
        batch = self.batch('40')
        PurchaseOrder.objects.get(pk=batch['id']).lines.update(product_line_id_snapshot=uuid4())
        row = self.rows()[0]
        self.assertFalse(row['source_reliable'])
        self.assertIsNone(row['remaining_quantity'])

    def test_filter_options_include_unbuilt_group_and_read_requires_identity(self):
        task = self.make_task('UNGROUPED')
        product = self.make_product_line(task)
        bom, _ = self.make_bom(product, section_type=BomSectionType.ACCESSORY, budget_quantity='25')
        response = self.client.get('/api/v1/purchase-tracking/filter-options/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(str(task.pk), {row['id'] for row in response.data['data']['production_tasks']})
        row = self.rows(task)[0]
        self.assertIn(f'production_task_id={task.pk}&bom_id={bom.pk}', next(
            action['path'] for action in row['actions'] if action['kind'] == 'create_group'))
        self.client.force_authenticate(None)
        self.assertIn(self.client.get('/api/v1/purchase-tracking/arrivals/').status_code, [401, 403])

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_followed_and_module_roles_match_notification_scope_without_unrelated_grants(self):
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        role = RoleProfile.objects.create(role_code='TRACK-SCOPE', display_name='跟踪范围',
            auth_group=Group.objects.create(name='tracking-scope'))
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=role, effective_from=timezone.now())
        view = Permission.objects.get(content_type__app_label='procurement', codename='view_purchaseorder')
        grant = RoleActionGrant.objects.create(role=role, permission=view, scope='FOLLOWED')
        other = Permission.objects.get(content_type__app_label='inventory', codename='receive_material')
        RoleActionGrant.objects.create(role=role, permission=other, scope='MODULE')
        self.assertEqual(self.client.get('/api/v1/purchase-tracking/coverage/').data['data'], [])
        self.assertFalse(employee_can_view_task(self.employee, self.task.pk))
        self.task.followers.add(self.employee)
        response = self.client.get('/api/v1/purchase-tracking/coverage/')
        self.assertEqual(len(response.data['data']), 1)
        self.assertEqual(set(accessible_production_tasks(response.renderer_context['request'],
            permission='procurement.view_purchaseorder').values_list('pk', flat=True)), {self.task.pk})
        self.assertTrue(employee_can_view_task(self.employee, self.task.pk))
        self.task.followers.clear()
        grant.scope = 'WORKSHOP'
        grant.save(update_fields=['scope'])
        self.assertFalse(employee_can_view_task(self.employee, self.task.pk))
        self.assertEqual(self.client.get('/api/v1/purchase-tracking/coverage/').data['data'], [])
        schedule = self.schedule()
        workshop = Workshop.objects.exclude(pk=schedule.crafts.first().craft.workshop_id).first()
        RoleGrantResource.objects.create(grant=grant, workshop=workshop)
        craft = Craft.objects.create(craft_type='INTERNAL', name='跟踪权限测试工艺', workshop=workshop)
        scheduled_craft = ProductionScheduleProductCraft.objects.create(schedule_product=schedule, craft=craft,
            craft_type_snapshot='INTERNAL', craft_name_snapshot=craft.name)
        response = self.client.get('/api/v1/purchase-tracking/coverage/')
        self.assertEqual(len(response.data['data']), 1)
        self.assertTrue(employee_can_view_task(self.employee, self.task.pk))
        self.assertEqual(set(accessible_production_tasks(response.renderer_context['request'],
            permission='procurement.view_purchaseorder').values_list('pk', flat=True)), {self.task.pk})
        scheduled_craft.removed_at = timezone.now()
        scheduled_craft.removed_by_employee = self.employee
        scheduled_craft.save(update_fields=['removed_at', 'removed_by_employee'])
        self.assertFalse(employee_can_view_task(self.employee, self.task.pk))
        grant.scope = 'MODULE'
        grant.save(update_fields=['scope'])
        self.assertTrue(employee_can_view_task(self.employee, self.task.pk))
        self.assertEqual(len(self.client.get('/api/v1/purchase-tracking/coverage/').data['data']), 1)

    @override_settings(MODULE_ACCESS_ENABLED=False, ACCESS_MANAGEMENT_ENABLED=True)
    def test_followed_scope_is_not_widened_by_disabling_module_switch(self):
        self.user.user_permissions.clear()
        group = Group.objects.create(name='tracking-followed-legacy-projection')
        role = RoleProfile.objects.create(role_code='TRACK-FOLLOWED', display_name='跟单', auth_group=group)
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=role, effective_from=timezone.now())
        view = Permission.objects.get(content_type__app_label='procurement', codename='view_purchaseorder')
        RoleActionGrant.objects.create(role=role, permission=view, scope='FOLLOWED')
        group.permissions.add(view)
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        response = self.client.get('/api/v1/purchase-tracking/coverage/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data'], [])
        self.assertFalse(employee_can_view_task(self.employee, self.task.pk))

    def test_tube_quantities_keep_roots_and_mark_missing_root_basis(self):
        root, _ = ProductionUnit.objects.get_or_create(unit_name='根', defaults={'unit_code': 'TRACK-ROOT'})
        self.inventory_material.unit = root
        self.inventory_material.category = ProductCategory.objects.get(category_name='管材', item_type='MATERIAL')
        self.inventory_material.save(update_fields=['unit', 'category'])
        task = self.make_task('TRACK-PIPE')
        product = self.make_product_line(task)
        plan = pipe_plan(cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=6, order_quantity=10)
        bom, pipe_line = self.make_bom(product, unit='根', **{key: plan[key] for key in (
            'cutting_length_mm', 'pieces_per_product', 'pieces_per_bar', 'raw_bar_length_m',
            'suggested_bar_count', 'suggested_purchase_meters')})
        source = self.get_source(task, bom).data['data']
        created = self.client.post('/api/v1/purchase-groups/', {'production_task_id': str(task.pk),
            'bom_id': str(bom.pk), 'source_revision': source['source_revision']}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.group_id = created.data['data']['id']
        self.line_id = created.data['data']['progress']['lines'][0]['id']
        payload = self.batch_payload(quantity=None)
        payload['lines'][0]['actual_bar_count'] = 3
        batch = self.client.post(f'/api/v1/purchase-groups/{self.group_id}/batches/', payload,
            format='json', HTTP_IF_MATCH=self.detail()['ETag'])
        self.assertEqual(batch.status_code, 201, batch.data)
        confirmed = self.client.post(f"/api/v1/purchase-orders/{batch.data['data']['id']}/confirm/", {}, format='json')
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        arrival = arrival_rows(task_ids=[task.pk])[0]
        self.assertEqual(arrival['ordered_root_count'], '3')
        self.assertEqual(Decimal(arrival['ordered_quantity']), Decimal('9.15'))
        coverage = self.rows(task)[0]
        self.assertTrue(coverage['source_reliable'], coverage['verification_notes'])
        self.assertEqual(coverage['remaining_root_count'], '1')
        # 换算依据变了，但向上取整后的总米数和根数恰好相同，仍须核对。
        pipe_line.cutting_length_mm, pipe_line.pieces_per_bar = 600, 5
        pipe_line.save(update_fields=['cutting_length_mm', 'pieces_per_bar'])
        self.assertEqual(self.rows(task)[0]['risks'][0]['code'], 'DEMAND_CHANGED')
        pipe_line.cutting_length_mm, pipe_line.pieces_per_bar = 500, 6
        pipe_line.save(update_fields=['cutting_length_mm', 'pieces_per_bar'])
        PurchaseOrder.objects.get(pk=confirmed.data['data']['id']).lines.update(actual_bar_count=None,
            raw_bar_length_m=None, suggested_bar_count=None, suggested_purchase_meters=None, actual_purchase_meters=None)
        arrival = arrival_rows(task_ids=[task.pk])[0]
        self.assertIsNone(arrival['ordered_root_count'])
        self.assertIsNone(self.rows(task)[0]['remaining_quantity'])
        self.assertFalse(arrival['source_reliable'])

    def test_history_receipts_are_database_aggregated_and_coverage_queries_are_batched(self):
        batch = self.batch('100')
        order = PurchaseOrder.objects.get(pk=batch['id'])
        line = order.lines.get()
        inbounds = MaterialInbound.objects.bulk_create([MaterialInbound(inbound_number=f'TRACK-BULK-{number}',
            purchase_order=order, status='CONFIRMED', received_by_employee=self.employee) for number in range(40)])
        MaterialInboundLine.objects.bulk_create([MaterialInboundLine(inbound=inbound, purchase_order_line=line,
            raw_material_information=self.inventory_material, zone=self.zone, received_quantity=1, accepted_quantity=1,
            return_quantity=0, source_unit_text_snapshot=line.source_unit_text, purchased_quantity_snapshot=100)
            for inbound in inbounds])
        with CaptureQueriesContext(connection) as receipts:
            summaries = _receipt_summaries([line.pk])
        self.assertEqual(len(receipts), 1)
        self.assertEqual(len(summaries[line.pk]), 1)
        self.assertEqual(summaries[line.pk][0]['received'], Decimal('40'))
        with CaptureQueriesContext(connection) as first:
            self.rows()
        for index in range(2, 8):
            product = self.make_product_line(self.task, line_number=index)
            self.make_bom(product, section_type=BomSectionType.ACCESSORY, budget_quantity='20')
        with CaptureQueriesContext(connection) as expanded:
            rows = self.rows()
        self.assertEqual(len(rows), 7)
        self.assertLessEqual(len(expanded), len(first) + 1)
        print(f'采购跟踪聚合查询：40 次收货={len(receipts)} 查询/1 聚合行；漏采 1 产品={len(first)}，7 产品={len(expanded)}')
