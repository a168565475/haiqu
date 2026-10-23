from apps.workshop_config.tests.factories import production_employee
import copy
import uuid
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.inventory.models import MaterialStockMovement, SemiFinishedStockBalance, SemiFinishedStockMovement, WarehouseZone
from apps.outsourcing.tests.test_material_flow import MaterialFlowFixture
from apps.products.models import RawMaterialInformation
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Workshop, Craft
from ..models import MaterialIssue, OrderMaterialRequirement
from ..scopes import material_section_codes_for_workshop


class MaterialIssueFlowTests(MaterialFlowFixture, APITestCase):
    def setUp(self):
        super().setUp()
        f = self.f
        f.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="material_issues"))
        self.workshop, _ = Workshop.objects.get_or_create(name="金工车间", defaults={"status": "ACTIVE"})
        self.recipient = production_employee(workshop=self.workshop, name="S7 领料员", position="领料员", is_supervisor=False, status="ACTIVE")
        craft = Craft.objects.create(craft_type="INTERNAL", name="S7 金工", workshop=self.workshop, plan_category="METAL",
            status="ACTIVE", created_by_employee=f.employee, updated_by_employee=f.employee)
        self.plan = ProductionScheduleProductCraft.objects.create(schedule_product=f.schedule_product, craft=craft,
            craft_type_snapshot="INTERNAL", craft_name_snapshot=craft.name, plan_category="METAL")
        hardware_unit, _ = ProductionUnit.objects.get_or_create(unit_name="个", defaults={"unit_code": "S7-EACH"})
        hardware_category, _ = ProductCategory.objects.get_or_create(
            category_name="五金", defaults={"item_type": "MATERIAL"})
        self.raw_hardware = RawMaterialInformation.objects.create(
            material_number="S7-HARDWARE", item_type="MATERIAL", category=hardware_category,
            material_name="S7 测试铆钉", specification="M6", unit=hardware_unit)
        f.hardware.raw_values = {"source_inventory_material_id": str(self.raw_hardware.pk)}
        f.hardware.save(update_fields=["raw_values", "updated_at"])
        self.task = f.bom.production_task

    def requirements(self):
        response = self.client.get('/api/v1/material-issues/requirements/', {"production_task_id": str(self.task.pk),
            "product_line_id": str(self.f.product_line.pk), "workshop_id": str(self.workshop.pk)}, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['blockers'], [])
        return response.data['data']['items']

    def test_plan_material_scopes_follow_confirmed_workshop_rules(self):
        self.assertEqual(
            material_section_codes_for_workshop("金工车间", "METAL"),
            frozenset({"PROFILE", "HARDWARE"}),
        )
        self.assertEqual(
            material_section_codes_for_workshop("车缝车间", "CUTTING"),
            frozenset({"FABRIC"}),
        )
        self.assertEqual(
            material_section_codes_for_workshop("车缝车间", "SEWING"),
            frozenset({"AUXILIARY"}),
        )
        self.assertEqual(
            material_section_codes_for_workshop("装配车间", "ASSEMBLY"),
            frozenset({"PROFILE", "HARDWARE", "PLASTIC", "AUXILIARY", "PACKAGING", "SEMI"}),
        )
        self.assertIsNone(material_section_codes_for_workshop("装配车间", "CUTTING"))

    def test_assembly_scope_excludes_fabric_and_allows_other_materials(self):
        assembly, _ = Workshop.objects.get_or_create(name="装配车间", defaults={"status": "ACTIVE"})
        response = self.client.get('/api/v1/material-issues/requirements/', {
            "production_task_id": str(self.task.pk),
            "product_line_id": str(self.f.product_line.pk),
            "workshop_id": str(assembly.pk),
            "plan_category": "ASSEMBLY",
        }, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200, response.data)
        items = response.data['data']['items']
        self.assertTrue(any(row.get('conversion_snapshot', {}).get('kind') == 'PIPE' for row in items))
        self.assertTrue(all(row['section_code'] in {"PROFILE", "HARDWARE", "PLASTIC", "AUXILIARY", "PACKAGING", "SEMI"} for row in items))
        self.assertFalse(any(row['section_code'] == "FABRIC" for row in items))

    def issue_payload(self, quantity="12"):
        pipe = next(r for r in self.requirements() if r.get('conversion_snapshot', {}).get('kind') == 'PIPE')
        return {"client_request_id": str(uuid.uuid4()), "schedule_product_id": str(self.f.schedule_product.pk),
            "plan_category": "METAL", "production_task_id": str(self.task.pk), "product_line_id": str(self.f.product_line.pk),
            "workshop_id": str(self.workshop.pk), "recipient_workshop_employee_id": str(self.recipient.pk),
            "issue_at": timezone.now().isoformat(), "lines": [{"requirement_id": pipe['requirement_id'],
                "requested_quantity": quantity, "batch_allocations": [{"inbound_line_id": str(self.pipe_batch.pk), "requested_pieces": quantity}]}]}

    def create_issue(self, payload=None, expected=201):
        response = self.client.post('/api/v1/material-issues/', payload or self.issue_payload(), format='json', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def action(self, issue_id, action, payload=None, expected=200, etag=None):
        detail = self.client.get(f'/api/v1/material-issues/{issue_id}/', HTTP_HOST='localhost')
        response = self.client.post(f'/api/v1/material-issues/{issue_id}/{action}/', payload or {}, format='json',
            HTTP_HOST='localhost', HTTP_IF_MATCH=etag or detail['ETag'])
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def pending(self, payload=None):
        result = self.create_issue(payload); key = result.data['data']['id']
        self.action(key, 'submit')
        return key

    def test_read_and_preview_do_not_create_or_change_stock(self):
        self.requirements(); self.assertFalse(OrderMaterialRequirement.objects.exists())
        key = self.pending()
        before = list(OrderMaterialRequirement.objects.values())
        movements = MaterialStockMovement.objects.count()
        result = self.action(key, 'preview-issue')
        self.assertTrue(result.data['data']['can_confirm'])
        self.assertEqual(before, list(OrderMaterialRequirement.objects.values()))
        self.assertEqual(MaterialStockMovement.objects.count(), movements)
        self.pipe_balance.refresh_from_db(); self.assertEqual(self.pipe_balance.quantity, 100)

    def test_pipe_actual_three_quantities_and_idempotent_confirmation(self):
        key = self.pending(); request = {"request_id": str(uuid.uuid4())}
        result = self.action(key, 'confirm-issue', request)
        line = result.data['data']['lines'][0]
        self.assertEqual((line['requested_quantity'], line['bar_count'], line['meters']), ('12.0000', '2', '6.10'))
        self.action(key, 'confirm-issue', request)
        self.pipe_balance.refresh_from_db()
        self.assertEqual((self.pipe_balance.quantity, self.pipe_balance.meter_quantity), (98, Decimal('298.90')))
        self.assertEqual(OrderMaterialRequirement.objects.get(measurement_kind='PIPE').internal_issued_quantity, 12)
        self.assertEqual(MaterialStockMovement.objects.filter(source_type='MATERIAL_ISSUE').count(), 1)

    def test_new_pipe_rule_flows_into_requirement_and_actual_issue(self):
        from apps.boms.material_flow_calculations import pipe_plan
        line = self.f.profile
        plan = pipe_plan(cutting_length_mm=500, pieces_per_product=4, pieces_per_bar=6, order_quantity=100)
        line.raw_values['pipe_plan_version'] = 3
        line.suggested_bar_count = plan['suggested_bar_count']
        line.suggested_purchase_meters = plan['suggested_purchase_meters']
        line.save()
        row = next(item for item in self.requirements() if item.get('conversion_snapshot', {}).get('kind') == 'PIPE')
        self.assertEqual(Decimal(row['required_quantity']), 402)
        key = self.pending(self.issue_payload('402'))
        self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())})
        requirement = OrderMaterialRequirement.objects.get(measurement_kind='PIPE')
        self.assertEqual((requirement.required_quantity, requirement.internal_issued_quantity), (402, 402))
        self.pipe_balance.refresh_from_db()
        self.assertEqual(self.pipe_balance.quantity, 33)

    def test_pipe_issue_does_not_require_user_selected_batch(self):
        payload = self.issue_payload()
        payload['lines'][0].pop('batch_allocations')
        key = self.pending(payload)
        result = self.action(key, 'confirm-issue', {"request_id": str(uuid.uuid4())})
        line = result.data['data']['lines'][0]
        self.assertEqual((line['requested_quantity'], line['bar_count'], line['meters']), ('12.0000', '2', '6.10'))
        self.assertEqual(len(line['batch_allocations']), 1)
        self.assertEqual(line['batch_allocations'][0]['inbound_line_id'], str(self.pipe_batch.pk))

    def test_pipe_issue_automatically_uses_multiple_matching_stock_rows(self):
        from apps.inventory.models import MaterialInboundLine
        from apps.inventory.stock_services import credit_confirmed_inbound_line

        self.pipe_balance.quantity = Decimal('1')
        self.pipe_balance.meter_quantity = Decimal('3.05')
        self.pipe_balance.save(update_fields=['quantity', 'meter_quantity'])
        second_batch = MaterialInboundLine.objects.create(
            inbound=self.f.material_inbound,
            raw_material_information=self.raw_pipe,
            zone=self.pipe_batch.zone,
            measurement_kind='PIPE',
            raw_bar_length_m='3.05',
            received_bar_count=100,
            accepted_bar_count=100,
            return_bar_count=0,
            received_quantity=305,
            accepted_quantity=305,
            return_quantity=0,
            source_unit_text_snapshot='米',
            purchased_quantity_snapshot=305,
        )
        second_balance = credit_confirmed_inbound_line(
            line=second_batch,
            actor_employee=self.f.employee,
        ).balance
        payload = self.issue_payload()
        payload['lines'][0].pop('batch_allocations')
        key = self.pending(payload)
        result = self.action(key, 'confirm-issue', {"request_id": str(uuid.uuid4())})
        line = result.data['data']['lines'][0]
        self.assertEqual(len(line['batch_allocations']), 2)
        self.pipe_balance.refresh_from_db()
        second_balance.refresh_from_db()
        self.assertEqual((self.pipe_balance.quantity, second_balance.quantity), (0, 99))

    def test_fraction_or_nonwhole_pipe_draft_rejected(self):
        for amount in ['5', '7', '6.5', '0']:
            self.create_issue(self.issue_payload(amount), expected=400)
        self.assertFalse(MaterialIssue.objects.exists())

    def test_client_batch_selection_is_ignored_and_system_allocates(self):
        payload = self.issue_payload()
        payload['lines'][0]['batch_allocations'] = [{
            'inbound_line_id': str(self.f.material_inbound_line.pk),
            'requested_pieces': '12',
        }]
        key = self.pending(payload)
        result = self.action(key, 'confirm-issue', {"request_id": str(uuid.uuid4())})
        allocations = result.data['data']['lines'][0]['batch_allocations']
        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations[0]['inbound_line_id'], str(self.pipe_batch.pk))

    def test_stock_change_blocks_entire_confirmation(self):
        key = self.pending()
        self.pipe_balance.quantity = 1; self.pipe_balance.meter_quantity = Decimal('3.05'); self.pipe_balance.save()
        result = self.action(key, 'preview-issue'); self.assertFalse(result.data['data']['can_confirm'])
        self.action(key, 'confirm-issue', {"request_id": str(uuid.uuid4())}, expected=400)
        self.assertFalse(MaterialStockMovement.objects.filter(source_type='MATERIAL_ISSUE').exists())
        self.assertEqual(MaterialIssue.objects.get(pk=key).status, 'PENDING_REVIEW')

    def test_pending_internal_issue_reserves_allowance_from_outsourcing(self):
        key = self.pending()
        order = self.create(amount='402')
        from apps.outsourcing.models import OutsourcingMaterialItem
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order)
        self.post(order, 'confirm-dispatch', {'request_id': str(uuid.uuid4()), 'lines': [{
            'material_item_id': str(material.pk), 'inbound_line_id': str(self.pipe_batch.pk),
            'requested_quantity': '402',
        }]}, 409)
        self.action(key, 'confirm-issue', {"request_id": str(uuid.uuid4())})
        requirement = OrderMaterialRequirement.objects.get(measurement_kind='PIPE')
        self.assertEqual((requirement.internal_issued_quantity, requirement.outsourcing_issued_quantity), (12, 0))

    def test_internal_confirmation_restricts_later_outsourcing(self):
        key = self.pending(); self.action(key, 'confirm-issue', {"request_id": str(uuid.uuid4())})
        order = self.create(amount='402')
        from apps.outsourcing.models import OutsourcingMaterialItem
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order)
        self.post(order, 'confirm-dispatch', {'request_id': str(uuid.uuid4()), 'lines': [{'material_item_id': str(material.pk),
            'inbound_line_id': str(self.pipe_batch.pk), 'requested_quantity': '402'}]}, 409)

    def semi_payload(self, kind='PIPE', quantity='6', returned_quantity=None):
        order = self.create(kind, '12' if kind == 'PIPE' else '9')
        _, source = self.dispatch(order, kind, '12' if kind == 'PIPE' else '9')
        self.return_goods(order, source, returned_quantity if returned_quantity is not None else (10 if kind == 'PIPE' else 6),
            raw_inputs=[self.entry(source, 'RAW_INPUT', 2 if kind == 'PIPE' else 9)])
        balance = SemiFinishedStockBalance.objects.get(quality='AVAILABLE')
        # 半成品在装配计划领用；金工计划只允许管材和五金原料。
        assembly, _ = Workshop.objects.get_or_create(name='装配车间', defaults={'status': 'ACTIVE'})
        recipient = production_employee(workshop=assembly, name='S7 装配领料员',
            position='领料员', is_supervisor=False, status='ACTIVE')
        craft = Craft.objects.create(craft_type='INTERNAL', name='S7 装配', workshop=assembly,
            plan_category='ASSEMBLY', status='ACTIVE', created_by_employee=self.f.employee,
            updated_by_employee=self.f.employee)
        ProductionScheduleProductCraft.objects.create(schedule_product=self.f.schedule_product, craft=craft,
            craft_type_snapshot='INTERNAL', craft_name_snapshot=craft.name, plan_category='ASSEMBLY')
        payload = self.issue_payload()
        payload.update(plan_category='ASSEMBLY', workshop_id=str(assembly.pk),
            recipient_workshop_employee_id=str(recipient.pk),
            lines=[{'requirement_id': str(balance.pk), 'requested_quantity': quantity}])
        return payload, balance

    def test_semi_pipe_five_pieces_no_whole_bar_or_second_raw_debit(self):
        payload, balance = self.semi_payload(quantity='5', returned_quantity=12)
        before = list(MaterialStockMovement.objects.order_by('pk').values())
        self.pipe_balance.refresh_from_db()
        raw_before = (self.pipe_balance.quantity, self.pipe_balance.meter_quantity)
        quota = OrderMaterialRequirement.objects.get(measurement_kind='PIPE')
        key = self.pending(payload)
        request = {'request_id': str(uuid.uuid4())}
        self.action(key, 'confirm-issue', request)
        self.action(key, 'confirm-issue', request)
        balance.refresh_from_db(); quota.refresh_from_db()
        self.assertEqual(balance.quantity, 7)
        self.assertEqual(list(MaterialStockMovement.objects.order_by('pk').values()), before)
        self.pipe_balance.refresh_from_db()
        self.assertEqual((self.pipe_balance.quantity, self.pipe_balance.meter_quantity), raw_before)
        self.assertEqual((quota.internal_issued_quantity, quota.outsourcing_issued_quantity), (0, 12))
        self.assertEqual(SemiFinishedStockMovement.objects.filter(direction='OUT').count(), 1)

    def test_fabric_semi_uses_integer_sets(self):
        payload, balance = self.semi_payload('FABRIC', '2')
        key = self.pending(payload); self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())})
        balance.refresh_from_db(); self.assertEqual((balance.quantity, balance.unit.unit_name), (4, '套'))

    def test_semi_pipe_issue_snapshot_records_actual_pieces_and_zero_raw_debit(self):
        payload, balance = self.semi_payload(quantity='5', returned_quantity=12)
        key = self.pending(payload)
        result = self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())})
        line = next(item for item in result.data['data']['lines'] if item['line_type'] == 'SEMI')
        self.assertEqual(line['requested_quantity'], '5.0000')
        snapshot = line['conversion_snapshot']
        self.assertEqual(snapshot['kind'], 'SEMI_PIPE_PIECES')
        self.assertEqual(snapshot['issued_pieces'], '5.0000')
        self.assertEqual(snapshot['raw_deducted_bar_count'], '0')
        self.assertEqual(snapshot['raw_deducted_meters'], '0.00')
        self.assertNotIn('issued_bar_count', snapshot)
        self.assertNotIn('issued_meters', snapshot)
        balance.refresh_from_db(); self.assertEqual(balance.quantity, 7)

    def test_semi_pipe_invalid_quantities_and_over_stock_do_not_write_stock(self):
        payload, balance = self.semi_payload(quantity='5', returned_quantity=12)
        for quantity in ('0', '-1', '1.5'):
            invalid = copy.deepcopy(payload)
            invalid['client_request_id'] = str(uuid.uuid4())
            invalid['lines'][0]['requested_quantity'] = quantity
            self.create_issue(invalid, expected=400)
        payload['lines'][0]['requested_quantity'] = '13'
        key = self.create_issue(payload).data['data']['id']
        self.action(key, 'submit', expected=400)
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 12)
        self.assertFalse(SemiFinishedStockMovement.objects.filter(direction='OUT').exists())

    def test_semi_pipe_cleared_bom_conversion_still_issues_integer_pieces(self):
        payload, balance = self.semi_payload(quantity='5', returned_quantity=12)
        cleared_fields = ['cutting_length_mm', 'pieces_per_product', 'pieces_per_bar', 'raw_bar_length_m',
                          'suggested_bar_count', 'suggested_purchase_meters']
        for field in cleared_fields:
            setattr(self.f.profile, field, None)
        self.f.profile.save(update_fields=cleared_fields)
        response = self.client.get('/api/v1/material-issues/requirements/', {
            'production_task_id': str(self.task.pk), 'product_line_id': str(self.f.product_line.pk),
            'workshop_id': str(self.workshop.pk)}, HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200, response.data)
        semi = next(row for row in response.data['data']['items'] if row['line_type'] == 'SEMI')
        self.assertEqual(semi['conversion_snapshot']['kind'], 'SEMI_PIPE_PIECES')
        self.assertTrue(semi['conversion_snapshot']['integer_required'])
        self.assertFalse(semi['conversion_snapshot']['whole_bar_required'])
        self.assertNotIn('pieces_per_bar', semi['conversion_snapshot'])
        invalid = copy.deepcopy(payload)
        invalid['client_request_id'] = str(uuid.uuid4())
        invalid['lines'][0]['requested_quantity'] = '1.5'
        self.create_issue(invalid, expected=400)
        key = self.pending(payload)
        self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())})
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 7)

    def test_semi_pipe_changed_bom_conversion_does_not_change_issue_quantity(self):
        payload, balance = self.semi_payload(quantity='5', returned_quantity=12)
        self.f.profile.pieces_per_bar = 3
        self.f.profile.raw_bar_length_m = Decimal('1.55')
        self.f.profile.save(update_fields=['pieces_per_bar', 'raw_bar_length_m'])
        key = self.pending(payload)
        self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())})
        balance.refresh_from_db()
        self.assertEqual(balance.quantity, 7)

    def test_semi_pipe_other_part_cannot_cover_requested_part_shortage(self):
        payload, balance = self.semi_payload(quantity='5', returned_quantity=12)
        other_part = copy.copy(self.f.profile)
        other_part.pk = None
        other_part.component_identity = uuid.uuid4()
        other_part.line_number += 1
        other_part.part_name = '后脚管'
        other_part.save()
        other = SemiFinishedStockBalance.objects.create(
            production_task=balance.production_task, product_line=balance.product_line,
            bom_line=other_part, completed_craft=balance.completed_craft, unit=balance.unit,
            color_snapshot=balance.color_snapshot, zone=balance.zone, quality='AVAILABLE', quantity=20,
        )
        excessive = copy.deepcopy(payload)
        excessive['client_request_id'] = str(uuid.uuid4())
        excessive['lines'][0]['requested_quantity'] = '13'
        key = self.create_issue(excessive).data['data']['id']
        self.action(key, 'submit', expected=400)
        key = self.pending(payload)
        self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())})
        balance.refresh_from_db(); other.refresh_from_db()
        self.assertEqual((balance.quantity, other.quantity), (7, 20))

    def test_semi_requirements_split_by_zone_without_batch_selection(self):
        _payload, balance = self.semi_payload(quantity='6')
        second_zone = WarehouseZone.objects.create(
            warehouse=balance.zone.warehouse, zone_name='P4 聚合区', status='ACTIVE',
            created_by_employee=self.f.employee, updated_by_employee=self.f.employee,
        )
        SemiFinishedStockBalance.objects.create(
            production_task=balance.production_task, product_line=balance.product_line,
            bom_line=balance.bom_line, completed_craft=balance.completed_craft,
            color_snapshot=balance.color_snapshot, unit=balance.unit, zone=second_zone,
            quality=balance.quality, quantity=2,
        )
        rows = self.requirements()
        semi_rows = [row for row in rows if row['line_type'] == 'SEMI']
        self.assertEqual(len(semi_rows), 2, semi_rows)
        self.assertEqual(sorted(row['available_stock'] for row in semi_rows), ['10.0000', '2.0000'])
        self.assertTrue(all(len(row['semi_balance_allocations']) == 1 for row in semi_rows))
        self.assertTrue(all(row['batch_selection'] is False for row in semi_rows))

    def test_semi_fraction_and_inactive_zone_rejected(self):
        payload, balance = self.semi_payload(quantity='1.5')
        self.create_issue(payload, expected=400)
        payload['lines'][0]['requested_quantity'] = '6'
        key = self.pending(payload)
        balance.zone.status = 'DISABLED'; balance.zone.save()
        self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())}, expected=400)
        self.assertFalse(SemiFinishedStockMovement.objects.filter(direction='OUT').exists())

    def test_semi_can_issue_after_bom_changed(self):
        payload, balance = self.semi_payload()
        count = OrderMaterialRequirement.objects.count()
        self.f.bom.status = 'PENDING_CONFIRMATION'; self.f.bom.save()
        key = self.pending(payload)
        self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())})
        balance.refresh_from_db(); self.assertEqual(balance.quantity, 4)
        self.assertEqual(OrderMaterialRequirement.objects.count(), count)

    def test_invalidated_plan_blocks_confirmation(self):
        key = self.pending(); self.plan.removed_at = timezone.now(); self.plan.removed_by_employee = self.f.employee; self.plan.save()
        self.assertFalse(self.action(key, 'preview-issue').data['data']['can_confirm'])
        self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())}, expected=400)

    def test_return_edit_resubmit_no_stock_until_confirm(self):
        key = self.pending(); result = self.action(key, 'return', {'reason': '批次支数需要修改'})
        payload = self.issue_payload('18')
        response = self.client.patch(f'/api/v1/material-issues/{key}/', {'lines': payload['lines']}, format='json',
            HTTP_HOST='localhost', HTTP_IF_MATCH=result['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        self.action(key, 'submit'); self.pipe_balance.refresh_from_db(); self.assertEqual(self.pipe_balance.quantity, 100)
        self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())})
        self.pipe_balance.refresh_from_db(); self.assertEqual(self.pipe_balance.quantity, 97)

    def test_stale_etag_and_no_permission(self):
        created = self.create_issue(); key = created.data['data']['id']; self.action(key, 'submit')
        self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())}, expected=412, etag=created['ETag'])
        self.f.user.user_permissions.remove(*Permission.objects.filter(codename='review_materialissue'))
        self.f.user.is_superuser = False
        self.f.user.save()
        for name in ['_perm_cache', '_user_perm_cache']:
            if hasattr(self.f.user, name): delattr(self.f.user, name)
        self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())}, expected=403)

    def test_issued_snapshot_survives_bom_change(self):
        key = self.pending(); before = self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())}).data['data']['lines']
        self.f.profile.part_name = '改名后'; self.f.profile.save()
        result = self.client.get(f'/api/v1/material-issues/{key}/', HTTP_HOST='localhost')
        self.assertEqual(before, result.data['data']['lines'])

    def test_two_parts_share_batch_check_combined_stock_and_debit(self):
        second = copy.copy(self.f.profile); second.pk = None; second.component_identity = uuid.uuid4()
        second.line_number += 1; second.part_name = '后脚管'; second.save()
        payload = self.issue_payload()
        other = next(
            r for r in self.requirements()
            if r.get('conversion_snapshot', {}).get('kind') == 'PIPE'
            and r['requirement_id'] != payload['lines'][0]['requirement_id']
        )
        payload['lines'].append({**copy.deepcopy(payload['lines'][0]), 'requirement_id': other['requirement_id']})
        created = self.create_issue(payload); key = created.data['data']['id']
        self.pipe_balance.quantity = 3; self.pipe_balance.meter_quantity = Decimal('9.15'); self.pipe_balance.save()
        self.action(key, 'submit', expected=400)
        self.pipe_balance.quantity = 4; self.pipe_balance.meter_quantity = Decimal('12.20'); self.pipe_balance.save()
        self.action(key, 'submit'); self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())})
        self.pipe_balance.refresh_from_db(); self.assertEqual(self.pipe_balance.quantity, 0)
        self.assertEqual(MaterialStockMovement.objects.filter(source_type='MATERIAL_ISSUE').count(), 2)

    def test_mixed_issue_semi_shortage_rolls_back_pipe_and_quota(self):
        # 装配范围会校验全部辅料来源；建立包边带档案，不绕过来源完整性检查。
        category, _ = ProductCategory.objects.get_or_create(category_name='辅料', defaults={'item_type': 'MATERIAL'})
        auxiliary = RawMaterialInformation.objects.create(material_number='S7-AUXILIARY', item_type='MATERIAL',
            category=category, material_name='包边带', specification='25mm', unit=self.f.material_unit)
        self.f.auxiliary.raw_values = {**self.f.auxiliary.raw_values, 'source_inventory_material_id': str(auxiliary.pk)}
        self.f.auxiliary.save(update_fields=['raw_values', 'updated_at'])
        payload, balance = self.semi_payload()
        payload['lines'] = self.issue_payload()['lines'] + payload['lines']
        key = self.pending(payload)
        balance.quantity = 0; balance.save()
        self.action(key, 'confirm-issue', {'request_id': str(uuid.uuid4())}, expected=400)
        self.assertFalse(MaterialStockMovement.objects.filter(source_type='MATERIAL_ISSUE').exists())
        self.assertFalse(SemiFinishedStockMovement.objects.filter(direction='OUT').exists())
        self.assertEqual(OrderMaterialRequirement.objects.get(measurement_kind='PIPE').internal_issued_quantity, 0)


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections, connection, transaction
from rest_framework.test import APITransactionTestCase, APIClient


class MaterialIssueFlowConcurrencyTests(APITransactionTestCase):
    def setUp(self):
        with transaction.atomic():
            # 共用夹具显式建立单位、车间、材料及排产，不恢复迁移种子的全库快照。
            self.h = MaterialIssueFlowTests(methodName='test_pipe_actual_three_quantities_and_idempotent_confirmation')
            self.h.setUp()

    def race(self, rows):
        barrier = Barrier(len(rows))
        def execute(row):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '15s'")
                    cursor.execute("SET statement_timeout = '30s'")
                client = APIClient(); client.force_authenticate(self.h.f.user)
                url, payload, etag = row
                barrier.wait(timeout=10)
                response = client.post(url, payload, format='json', HTTP_HOST='localhost', HTTP_IF_MATCH=etag)
                return response.status_code
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=len(rows)) as pool:
            return sorted(pool.map(execute, rows))

    def issue_request(self, key, request_id=None):
        response = self.h.client.get(f'/api/v1/material-issues/{key}/', HTTP_HOST='localhost')
        return (f'/api/v1/material-issues/{key}/confirm-issue/', {'request_id': request_id or str(uuid.uuid4())}, response['ETag'])

    def test_same_issue_same_request_debits_once(self):
        key = self.h.pending(); row = self.issue_request(key)
        self.assertEqual(self.race([row, row]), [200, 200])
        self.assertEqual(MaterialStockMovement.objects.filter(source_type='MATERIAL_ISSUE').count(), 1)

    def test_same_issue_different_request_debits_once(self):
        key = self.h.pending()
        self.assertEqual(self.race([self.issue_request(key), self.issue_request(key)]), [200, 412])
        self.assertEqual(MaterialStockMovement.objects.filter(source_type='MATERIAL_ISSUE').count(), 1)

    def test_different_issues_shared_request_conflict_without_server_error(self):
        first, second = self.h.pending(), self.h.pending()
        request_id = str(uuid.uuid4())
        self.assertEqual(self.race([self.issue_request(first, request_id), self.issue_request(second, request_id)]), [200, 409])
        self.assertEqual(MaterialStockMovement.objects.filter(source_type='MATERIAL_ISSUE').count(), 1)

    def test_internal_and_external_race_cannot_exceed_shared_allowance(self):
        key = self.h.pending(); order = self.h.create(amount='402')
        from apps.outsourcing.models import OutsourcingMaterialItem
        material = OutsourcingMaterialItem.objects.get(allocation__processing_item__order_product__order_id=order)
        response = self.h.client.get(f'/api/v1/outsourcing-orders/{order}/', HTTP_HOST='localhost')
        external = (f'/api/v1/outsourcing-orders/{order}/confirm-dispatch/', {'request_id': str(uuid.uuid4()), 'lines': [
            {'material_item_id': str(material.pk), 'inbound_line_id': str(self.h.pipe_batch.pk), 'requested_quantity': '402'}]}, response['ETag'])
        result = self.race([self.issue_request(key), external])
        self.assertIn(result, [[200, 400], [200, 409]])
        quota = OrderMaterialRequirement.objects.get(measurement_kind='PIPE')
        self.assertIn(quota.internal_issued_quantity + quota.outsourcing_issued_quantity, [12, 402])
        self.assertEqual(MaterialStockMovement.objects.filter(direction='OUT').count(), 1)
