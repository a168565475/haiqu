"""隔离数据库 API 回归：厂内裁片直交与首次入库/外发共用产出额度。"""
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from apps.inventory.models import InternalSemiFinishedReceipt, PublicStockBalance, PublicStockMovement
from apps.inventory.tests import test_part_flow_receipts as receipt_fixture
from apps.organizations.models import Employee
from apps.outsourcing.models import OutsourcingFactoryCraft
from apps.outsourcing.tests import test_part_flow_plan_api as outsourcing_fixture
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.workshop_config.models import Craft
from apps.workshop_config.tests.factories import production_employee

from ..models import MaterialIssue, MaterialIssueAuditEvent, MaterialIssuePublicStockAllocation
from ..scopes import raw_line_allowed_for_plan


class RawCuttingSourceScopeTests(SimpleTestCase):
    def test_cuttable_cotton_only_goes_to_cutting_and_ordinary_auxiliary_stays_available(self):
        cotton, thread = uuid.uuid4(), uuid.uuid4()
        self.assertTrue(raw_line_allowed_for_plan(cotton, 'AUXILIARY', 'CUTTING', {cotton}))
        self.assertFalse(raw_line_allowed_for_plan(thread, 'AUXILIARY', 'CUTTING', {cotton}))
        for category in ('SEWING', 'ASSEMBLY'):
            self.assertFalse(raw_line_allowed_for_plan(cotton, 'AUXILIARY', category, {cotton}))
            self.assertTrue(raw_line_allowed_for_plan(thread, 'AUXILIARY', category, {cotton}))

    def test_legacy_bom_without_typed_sources_keeps_existing_scope(self):
        self.assertTrue(raw_line_allowed_for_plan(uuid.uuid4(), 'AUXILIARY', 'CUTTING', set()))


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class PartFlowDirectIssueTests(receipt_fixture.PartFlowReceiptTests):
    # 保留共同夹具的 4 个入库回归，新增测试不替换其行为。
    issue_url = '/api/v1/material-issues/'
    part_context = outsourcing_fixture.PartFlowPlanApiTests.part_context
    create_part_plan = outsourcing_fixture.PartFlowPlanApiTests.create_part_plan
    dispatch_part = outsourcing_fixture.PartFlowPlanApiTests.dispatch_part

    def setUp(self):
        super().setUp()
        self.sewing_craft = Craft.objects.get(plan_category='SEWING')
        self.sewing_workshop = self.sewing_craft.workshop
        self.sewing_recipient = production_employee(workshop=self.sewing_workshop, position='领料员', name='直交领料员')
        self.reviewer_user = get_user_model().objects.create_superuser(username='part-direct-reviewer', password='test')
        self.reviewer = Employee.objects.create(user=self.reviewer_user, employee_code='PART-DIRECT-REVIEWER', display_name='直交审核员')
        ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product, craft=self.external_sewing,
            defaults={'craft_type_snapshot': 'EXTERNAL', 'craft_name_snapshot': self.external_sewing.name})
        OutsourcingFactoryCraft.objects.get_or_create(factory=self.factory, craft=self.external_sewing,
            defaults={'craft_name_snapshot': self.external_sewing.name})

    def issue_rows(self):
        response = self.client.get(self.issue_url + 'requirements/', {
            'production_task_id': str(self.task.pk), 'product_line_id': str(self.product_line.pk),
            'workshop_id': str(self.sewing_workshop.pk), 'plan_category': 'SEWING'})
        self.assertEqual(response.status_code, 200, response.data)
        return [row for row in response.data['data']['items'] if row.get('component_kind') == 'CUT_PIECE']

    def issue_row(self, piece=None):
        component = str((piece or self.parts[0]).component_identity)
        return next(row for row in self.issue_rows() if row['conversion_snapshot']['component_identity'] == component)

    def direct_payload(self, quantity='20', piece=None):
        row = self.issue_row(piece)
        return {'client_request_id': str(uuid.uuid4()), 'schedule_product_id': str(self.schedule_product.pk),
            'plan_category': 'SEWING', 'production_task_id': str(self.task.pk),
            'product_line_id': str(self.product_line.pk), 'workshop_id': str(self.sewing_workshop.pk),
            'recipient_workshop_employee_id': str(self.sewing_recipient.pk), 'issue_at': timezone.now().isoformat(),
            'lines': [{'requirement_id': row['requirement_id'], 'requested_quantity': str(quantity), 'source_kind': 'CUTTING_DIRECT'}]}

    def create_direct(self, quantity='20', piece=None):
        response = self.client.post(self.issue_url, self.direct_payload(quantity, piece), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def submit_direct(self, created):
        response = self.client.post(f"{self.issue_url}{created.data['data']['id']}/submit/", {},
            format='json', HTTP_IF_MATCH=created['ETag'])
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def confirm_direct(self, pending, request_id=None, etag=None):
        self.client.force_authenticate(self.reviewer_user)
        return self.client.post(f"{self.issue_url}{pending.data['data']['id']}/confirm-issue/",
            {'request_id': request_id or str(uuid.uuid4())}, format='json', HTTP_IF_MATCH=etag or pending['ETag'])

    def test_zero_stock_direct_submission_confirmation_and_replay_do_not_debit_inventory(self):
        row = self.issue_row()
        self.assertEqual(Decimal(row['available_stock']), 0)
        initial = Decimal(row['direct_available_quantity'])
        balances = list(PublicStockBalance.objects.order_by('pk').values('id', 'quantity'))
        movements = PublicStockMovement.objects.count()
        created = self.create_direct()
        self.assertEqual(created.data['data']['lines'][0]['source_kind'], 'CUTTING_DIRECT')
        self.assertEqual(Decimal(self.issue_row()['direct_available_quantity']), initial)
        pending = self.submit_direct(created)
        self.assertEqual(Decimal(self.issue_row()['direct_available_quantity']), initial - 20)
        self.assertEqual(Decimal(self.issue_row()['public_pending_quantity']), 0)
        request_id = str(uuid.uuid4())
        confirmed = self.confirm_direct(pending, request_id)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        replayed = self.confirm_direct(pending, request_id)
        self.assertEqual(replayed.status_code, 200, replayed.data)
        issue = MaterialIssue.objects.get(pk=created.data['data']['id'])
        self.assertEqual(issue.status, 'ISSUED')
        line = issue.lines.get()
        self.assertEqual(line.issued_quantity, 20)
        self.assertEqual(line.semi_requirement.internal_issued_quantity, 20)
        self.assertEqual(MaterialIssueAuditEvent.objects.filter(issue=issue, action='ISSUED').count(), 1)
        self.assertFalse(MaterialIssuePublicStockAllocation.objects.filter(line__issue=issue).exists())
        self.assertEqual(PublicStockMovement.objects.count(), movements)
        self.assertEqual(list(PublicStockBalance.objects.order_by('pk').values('id', 'quantity')), balances)
        self.assertEqual(Decimal(self.issue_row()['direct_available_quantity']), initial - 20)

    def test_pending_direct_receipt_and_outsourcing_share_capacity_and_return_releases_only_own_reservation(self):
        initial = Decimal(self.issue_row()['direct_available_quantity'])
        pending = self.submit_direct(self.create_direct())
        received, _ = self.submit('CUTTING', self.parts[0], 10)
        self.assertEqual(received.status_code, 201, received.data)
        plan = self.create_part_plan()
        self.dispatch_part(plan, 15)
        remaining = initial - 20 - 10 - 15
        self.assertEqual(Decimal(self.issue_row()['direct_available_quantity']), remaining)
        receipt_line = next(row for row in self.preview('CUTTING')['lines'] if row['bom_line_id'] == str(self.parts[0].pk))
        self.assertEqual(Decimal(receipt_line['can_receive']), remaining)
        too_many = self.client.post(self.issue_url, self.direct_payload(remaining + 1), format='json')
        self.assertEqual(too_many.status_code, 400, too_many.data)
        self.client.force_authenticate(self.reviewer_user)
        returned = self.client.post(f"{self.issue_url}{pending.data['data']['id']}/return/", {'reason': '调整直交数量'},
            format='json', HTTP_IF_MATCH=pending['ETag'])
        self.assertEqual(returned.status_code, 200, returned.data)
        self.assertEqual(Decimal(self.issue_row()['direct_available_quantity']), initial - 10 - 15)

    def test_mixed_issue_still_rejects_stock_shortage_without_partially_reserving_direct_quantity(self):
        initial = Decimal(self.issue_row()['direct_available_quantity'])
        payload = self.direct_payload()
        stock_row = self.issue_row(self.parts[1])
        payload['lines'].append({'requirement_id': stock_row['requirement_id'], 'requested_quantity': '1', 'source_kind': 'STOCK'})
        before = MaterialIssue.objects.count()
        response = self.client.post(self.issue_url, payload, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(MaterialIssue.objects.count(), before)
        self.assertEqual(Decimal(self.issue_row()['direct_available_quantity']), initial)

    def test_direct_requires_integer_quantity_permissions_and_current_version(self):
        invalid = self.client.post(self.issue_url, self.direct_payload('1.5'), format='json')
        self.assertEqual(invalid.status_code, 400, invalid.data)
        created = self.create_direct()
        identifier = created.data['data']['id']
        missing = self.client.post(f'{self.issue_url}{identifier}/submit/', {}, format='json')
        self.assertEqual(missing.status_code, 428, missing.data)
        pending = self.submit_direct(created)
        stale = self.confirm_direct(pending, etag=created['ETag'])
        self.assertEqual(stale.status_code, 412, stale.data)
        outsider = get_user_model().objects.create_user(username='direct-no-permission')
        Employee.objects.create(user=outsider, employee_code='DIRECT-NO-PERMISSION', display_name='无领料权限')
        self.client.force_authenticate(outsider)
        denied = self.client.post(f'{self.issue_url}{identifier}/confirm-issue/', {'request_id': str(uuid.uuid4())},
            format='json', HTTP_IF_MATCH=pending['ETag'])
        self.assertEqual(denied.status_code, 403, denied.data)
        self.assertEqual(MaterialIssue.objects.get(pk=identifier).status, 'PENDING_REVIEW')

    def test_selected_unit_survives_cutting_receipt_and_stock_sewing_issue(self):
        piece = self.parts[0]
        piece.unit = '套'
        piece.save(update_fields=['unit'])
        preview = next(row for row in self.preview('CUTTING')['lines'] if row['bom_line_id'] == str(piece.pk))
        self.assertEqual(preview['unit'], '套')
        created, _ = self.submit('CUTTING', piece, 20)
        self.assertEqual(created.status_code, 201, created.data)
        confirmed = self.confirm(created)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        receipt = InternalSemiFinishedReceipt.objects.get(pk=created.data['data']['receipt_id'])
        receipt_line = receipt.lines.get()
        self.assertEqual((receipt_line.unit.unit_name, receipt_line.input_unit_name), ('套', '片'))
        movement = PublicStockMovement.objects.get(source_type='INTERNAL_SEMI_RECEIPT', source_id=receipt.pk)
        self.assertEqual(movement.balance.unit.unit_name, '套')
        self.assertEqual(movement.balance.identity_snapshot['composition'][0]['piece']['unit_name'], '套')
        row = self.issue_row(piece)
        self.assertEqual(row['unit'], '套')
        self.assertEqual(Decimal(row['available_stock']), 20)
        payload = self.direct_payload('7', piece)
        payload['lines'][0]['source_kind'] = 'STOCK'
        issue = self.client.post(self.issue_url, payload, format='json')
        self.assertEqual(issue.status_code, 201, issue.data)
        pending = self.submit_direct(issue)
        issued = self.confirm_direct(pending)
        self.assertEqual(issued.status_code, 200, issued.data)
        line = MaterialIssue.objects.get(pk=issue.data['data']['id']).lines.get()
        self.assertEqual((line.unit_snapshot, line.unit.unit_name, line.issued_quantity), ('套', '套', 7))
        self.assertEqual(line.public_stock_allocations.get().stock_quantity, 7)
        movement.balance.refresh_from_db()
        self.assertEqual(movement.balance.quantity, 13)

    def test_mixed_selected_units_support_zero_stock_direct_handoff_with_integer_quantities(self):
        self.parts[0].unit = '米'
        self.parts[0].save(update_fields=['unit'])
        self.parts[1].unit = '个'
        self.parts[1].save(update_fields=['unit'])
        rows = {row['conversion_snapshot']['component_identity']: row for row in self.issue_rows()}
        for piece, unit in ((self.parts[0], '米'), (self.parts[1], '个'), (self.parts[2], '片')):
            self.assertEqual(rows[str(piece.component_identity)]['unit'], unit)
        initial = Decimal(rows[str(self.parts[0].component_identity)]['direct_available_quantity'])
        invalid, _ = self.submit('CUTTING', self.parts[0], '1.5')
        self.assertEqual(invalid.status_code, 400, invalid.data)
        invalid = self.client.post(self.issue_url, self.direct_payload('1.5'), format='json')
        self.assertEqual(invalid.status_code, 400, invalid.data)
        before = PublicStockMovement.objects.count()
        created = self.create_direct('3')
        pending = self.submit_direct(created)
        confirmed = self.confirm_direct(pending)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        line = MaterialIssue.objects.get(pk=created.data['data']['id']).lines.get()
        self.assertEqual((line.unit_snapshot, line.issued_quantity), ('米', 3))
        self.assertEqual(PublicStockMovement.objects.count(), before)
        self.assertEqual(Decimal(self.issue_row()['direct_available_quantity']), initial - 3)
