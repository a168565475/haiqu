from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.test import APITestCase

from apps.access_control.models import MaterialSectionGrant
from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.material_issues.models import MaterialIssue, OrderMaterialRequirement
from apps.workshop_config.models import Workshop

from .. import warehouse_workbench_internal as board
from ..api.warehouse_workbench import WarehouseWorkbenchViewSet
from ..models import MaterialInbound, MaterialInboundLine
from . import test_assembly_receipts as assembly
from . import test_inbound_loading as purchasing


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class WarehouseInternalTests(ScopedActorMixin, APITestCase):
    make_order = purchasing.InboundLoadingTests.make_order

    def setUp(self):
        purchasing.InboundLoadingTests.setUp(self)
        self.scoped_actor()
        self.today = timezone.localdate()
        self.line.category_snapshot = '型材'
        self.line.source_unit_text = '根'
        self.line.delivery_date = self.today
        self.line.save()
        grant = self.grant(board.RECEIVE, 'MATERIAL')
        MaterialSectionGrant.objects.create(grant=grant, sections=['TUBE'])
        self.unreadable = self.order.lines.create(line_number=2, quantity_parse_status='READY',
            section_type_snapshot='ACCESSORY', section_title_snapshot='五金件', part_name_snapshot='不可见铆钉',
            supplier_name_snapshot='不可见供应商', actual_purchase_quantity=8)
        self.req = OrderMaterialRequirement.objects.create(production_task=self.order.production_task, line_type='RAW', section_code='TUBE',
            raw_material=self.raw_material, unit=self.raw_material.unit, required_quantity=100, source_revision_hash='warehouse')
        self.shop = Workshop.objects.get_or_create(name='金工车间')[0]
        self.grant(board.ISSUE)
        self.grant(board.REVIEW)

    def request(self):
        req = self.scoped_request()
        view = WarehouseWorkbenchViewSet()
        view.action = 'items'
        req.parser_context = {'view': view}
        return req

    def issue(self, number, status):
        issue = MaterialIssue.objects.create(issue_number=number, production_task=self.order.production_task,
            workshop=self.shop, client_request_id=uuid4(), request_payload_hash=number,
            status=status, created_by_employee=self.employee, updated_by_employee=self.employee,
            submitted_at=timezone.now(), issued_at=timezone.now() if status == 'ISSUED' else None)
        issue.lines.create(line_number=1, requirement=self.req, raw_material=self.raw_material, line_type='RAW',
            unit=self.raw_material.unit, unit_snapshot='根', material_name_snapshot='椅架钢管', requested_quantity=10,
            issued_quantity=10 if status == 'ISSUED' else None)
        return issue

    def receive(self, number, line, quantity):
        doc = MaterialInbound.objects.create(inbound_number=number, purchase_order=self.order, received_by_employee=self.employee)
        MaterialInboundLine.objects.create(inbound=doc, purchase_order_line=line, raw_material_information=self.raw_material,
            zone=self.zone, received_quantity=quantity, accepted_quantity=quantity, purchased_quantity_snapshot=line.actual_purchase_quantity,
            section_title_snapshot=line.section_title_snapshot, category_snapshot=line.category_snapshot,
            part_name_snapshot=line.part_name_snapshot, source_unit_text_snapshot=line.source_unit_text)
        return doc

    def test_receiving_matches_own_material_sections_and_actual_remaining(self):
        req = self.request()
        self.hidden.lines.create(line_number=1, quantity_parse_status='READY', section_type_snapshot='ACCESSORY',
            section_title_snapshot='五金件', part_name_snapshot='其他任务不可见物料', actual_purchase_quantity=3)
        visible = self.receive('RK-WH-1', self.line, 4)
        hidden = self.receive('RK-WH-2', self.unreadable, 2)
        card = board.overview(req, 'purchase', self.today)
        self.assertEqual((card['count'], card['breakdown']['partial']), (1, 1))
        self.assertEqual(card['priority'][0]['id'], str(self.order.pk))
        with self.assertRaises(NotFound):
            board.detail(req, 'purchase', 'purchase', self.hidden.pk)
        doc = board.detail(req, 'purchase', 'purchase', self.order.pk)
        self.assertNotIn('不可见', str(doc))
        self.assertEqual(len(doc['lines']), 1)
        self.assertEqual(Decimal(doc['lines'][0]['remaining']), 6)
        count, acts = board.activity(req, 'purchase', self.today, self.today, 20, 0)
        self.assertEqual((count, [e['id'] for e in acts]), (1, [str(visible.pk)]))
        with self.assertRaises(NotFound):
            board.detail(req, 'purchase', 'purchase_receipt', hidden.pk)
        self.receive('RK-WH-3', self.line, 6)
        self.assertEqual(board.overview(req, 'purchase', self.today)['count'], 0)
        with self.assertRaises(NotFound):
            board.detail(req, 'purchase', 'purchase', self.order.pk)

    def test_issue_groups_detail_and_history(self):
        req, task_id = self.request(), self.order.production_task_id
        first = self.issue('LL-WH-1', 'PENDING_REVIEW')
        self.issue('LL-WH-2', 'PENDING_REVIEW')
        self.issue('LL-WH-3', 'DRAFT')
        issued = self.issue('LL-WH-4', 'ISSUED')
        old = self.issue('LL-WH-5', 'ISSUED')
        MaterialIssue.objects.filter(pk=old.pk).update(issued_at=timezone.now()-timedelta(days=1))
        self.assertEqual(board.overview(req, 'issue', self.today)['breakdown']['documents'], 2)
        total, groups = board.items(req, 'issue', dict(page=1,page_size=5))
        self.assertEqual((total, groups[0]['id'], groups[0]['document_count']), (1, str(task_id), 2))
        total, docs = board.items(req, 'issue', dict(page=1,page_size=1,task_id=task_id))
        self.assertEqual((total,len(docs)), (2,1))
        detail = board.detail(req,'issue','issue',first.pk)
        self.assertEqual(Decimal(detail['lines'][0]['remaining']), 10)
        count, history = board.activity(req, 'issue', self.today, self.today, 10, 0)
        self.assertEqual((count, [row['id'] for row in history]), (1, [str(issued.pk)]))
        doc = board.detail(req,'issue','issue',issued.pk)
        self.assertEqual(Decimal(doc['lines'][0]['remaining']), 0)
        self.grant(board.FINISHED)
        req = self.request()
        self.assertFalse(board.overview(req, 'inbound', self.today)['available'])
        with self.assertRaises(PermissionDenied):
            board.items(req, 'inbound', dict(page=1,page_size=5))


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class WarehouseAssemblyTests(ScopedActorMixin, assembly.AssemblyFixture, APITestCase):
    def test_only_submitted_assembly_in_queue_and_only_confirmed_in_history(self):
        self.prepare()
        submitted = self.post(self.payload(received_quantity=4))
        self.assertEqual(submitted.status_code, 201, submitted.data)
        self.scoped_actor()
        self.grant(board.FINISHED)
        self.grant(board.CONFIRM['finished'])
        req, today = self.scoped_request(), timezone.localdate()
        card = board.overview(req, 'inbound', today)
        self.assertEqual(card['breakdown'], {'finished': 1})
        receipt_id = submitted.data['data']['id']
        detail = board.detail(req, 'inbound', 'finished', receipt_id)
        self.assertEqual(Decimal(detail['lines'][0]['remaining']), 4)
        self.assertEqual(board.activity(req, 'inbound', today, today, 10,0)[0], 0)
        self.client.force_authenticate(self.user)
        self.confirm(submitted)
        self.assertEqual(board.overview(req, 'inbound', today)['count'], 0)
        self.assertEqual(board.activity(req, 'inbound', today, today, 10,0)[1][0]['id'], str(receipt_id))
