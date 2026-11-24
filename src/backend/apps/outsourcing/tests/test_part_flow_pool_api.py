"""不同裁片行共享实物库存时，合计发出仍须尊重其他待审领料。"""
import uuid
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.boms.models import BomLine
from apps.inventory.models import PublicStockBalance, PublicStockMovement
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.tests.test_internal_receipt_sewing import SewingFixture
from apps.inventory.tests.test_tube_d1_receipts import D1Fixture
from apps.material_issues.models import MaterialIssue
from apps.material_issues.public_issue_services import replace_public_issue_lines
from apps.material_issues.public_semi_requirements import public_semi_requirement_rows
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft, Workshop
from apps.outsourcing.models import OutsourcingFactoryCraft, TubeOutsourcingInput
from . import test_part_flow_plan_api as plan_fixture

BASE = plan_fixture.BASE


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class PartFlowPoolApiTests(D1Fixture, APITestCase):
    part_context = plan_fixture.PartFlowPlanApiTests.part_context
    create_part_plan = plan_fixture.PartFlowPlanApiTests.create_part_plan

    def setUp(self):
        super().setUp()
        ProductCategory.objects.get_or_create(category_name='面料', item_type='MATERIAL')
        SewingFixture.prepare_sewing(self)
        self.piece_unit, _ = ProductionUnit.objects.get_or_create(unit_name='片', defaults={'unit_code': 'POOLPIECE'})
        ProductionUnit.objects.get_or_create(unit_name='个', defaults={'unit_code': 'POOLPART'})
        self.part = BomLine.objects.create(section=self.parts[0].section, line_number=3,
            component_kind='SEWN_PART', part_name='床面', unit='个', parts_per_product=1)
        first = self.parts[0]
        for piece in self.parts:
            piece.component_kind = 'CUT_PIECE'
            piece.parent_part = self.part
            piece.pieces_per_part = 2
            piece.unit = '片'
            piece.part_name, piece.specification = first.part_name, first.specification
            piece.fabric_source_line = first.fabric_source_line
            piece.cutting_pieces_per_set = piece.cutting_sets_per_product = None
            piece.fabric_meters_per_piece = piece.fabric_meters_per_set = None
            piece.save()
        self.sewing_workshop, _ = Workshop.objects.get_or_create(name='车缝车间')
        self.cut_craft = Craft.objects.create(name='同实物裁片测试裁剪', craft_type='INTERNAL',
            plan_category='CUTTING', workshop=self.sewing_workshop, status='ACTIVE')
        ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product, craft=self.external_sewing,
            defaults={'craft_type_snapshot': 'EXTERNAL', 'craft_name_snapshot': self.external_sewing.name})
        OutsourcingFactoryCraft.objects.get_or_create(factory=self.factory, craft=self.external_sewing,
            defaults={'craft_name_snapshot': self.external_sewing.name})

    def test_combined_inputs_cannot_consume_stock_reserved_for_another_issue(self):
        identities = [build_semi_finished_identity(bom_line=piece, completed_craft=self.cut_craft,
            unit=self.piece_unit) for piece in self.parts]
        self.assertEqual(identities[0]['identity_key'], identities[1]['identity_key'])
        credit_public_stock(identity=identities[0], zone=self.semi_zone, quantity=100, actor_employee=self.employee,
            source_type='TUBE_OUTSOURCING_RETURN', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            production_task=self.task, product_line=self.product_line, bom_line=self.parts[0])
        issue = MaterialIssue.objects.create(stock_mode='PUBLIC_V2', issue_number='POOL-RESERVATION',
            client_request_id=uuid.uuid4(), request_payload_hash='pool-reservation', production_task=self.task,
            product_line=self.product_line, workshop=self.sewing_workshop,
            created_by_employee=self.employee, updated_by_employee=self.employee)
        issue._material_issue_plan_category = 'SEWING'
        rows, blockers = public_semi_requirement_rows(self.task.pk, self.product_line.pk, plan_category='SEWING')
        self.assertFalse(blockers, blockers)
        row = next(row for row in rows if row['conversion_snapshot']['component_identity'] == str(self.parts[0].component_identity))
        replace_public_issue_lines(issue, [{'requirement_id': uuid.UUID(row['requirement_id']),
            'requested_quantity': Decimal(50), 'source_kind': 'STOCK'}])
        issue.status = 'PENDING_REVIEW'
        issue.save(update_fields=['status'])
        order = self.create_part_plan(source='PUBLIC_PIECE')
        for quantity, expected in [(40, 409), (25, 200)]:
            payload = {'client_request_id': str(uuid.uuid4()), 'actual_dispatch_date': str(timezone.localdate()),
                'source_kind': 'PUBLIC_PIECE', 'zone_id': str(self.semi_zone.pk),
                'inputs': [{'component_identity': str(piece.component_identity), 'quantity': str(quantity)}
                           for piece in self.parts]}
            response = self.client.post(BASE + order['id'] + '/plan-dispatch/', payload,
                format='json', HTTP_IF_MATCH=order['etag'])
            self.assertEqual(response.status_code, expected, response.data)
            if expected == 409:
                self.assertFalse(TubeOutsourcingInput.objects.exists())
                self.assertFalse(PublicStockMovement.objects.filter(source_type='TUBE_OUTSOURCING_DISPATCH').exists())
                self.assertEqual(PublicStockBalance.objects.get(identity_key=identities[0]['identity_key']).quantity, 100)
        self.assertEqual(TubeOutsourcingInput.objects.count(), 2)
        self.assertEqual(PublicStockBalance.objects.get(identity_key=identities[0]['identity_key']).quantity, 50)
