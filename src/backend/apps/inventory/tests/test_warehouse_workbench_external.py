from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.test import APITestCase

from apps.inventory import warehouse_workbench_external as board
from apps.inventory.part_flow_receipts import component_stock_craft
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.inventory.models import SemiFinishedStockBalance
from apps.material_issues.models import MetalProcessingOriginalHandoff
from apps.outsourcing.models import (
    OutsourcingFactoryAllocation, OutsourcingOrder, OutsourcingOrderProduct, OutsourcingProcessingItem,
    OutsourcingReturn, OutsourcingReturnLine, TubeOutsourcingOrder,
)
from apps.outsourcing.tests import test_part_flow_plan_api as plans
from apps.outsourcing.warehouse_access import DISPATCH_PERMISSION, RETURN_PERMISSION


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True,
                   MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class WarehouseExternalTests(plans.PartFlowPlanFixture, APITestCase):
    part_context = plans.PartFlowPlanApiTests.part_context
    create_part_plan = plans.PartFlowPlanApiTests.create_part_plan
    dispatch_part = plans.PartFlowPlanApiTests.dispatch_part
    receive_part = plans.PartFlowPlanApiTests.receive_part

    def request(self, scoped=False):
        return SimpleNamespace(user=self.scope_user if scoped else self.user,
                               employee=self.scope_employee if scoped else self.employee, query_params={})

    def test_one_document_two_partial_queues_and_actual_receipts(self):
        req = self.request()
        today = timezone.localdate()
        order = self.create_part_plan('PUBLIC_PIECE')
        self.assertEqual(board.overview(req, 'dispatch', today)['count'], 1)
        self.assertEqual(board.overview(req, 'returns', today)['count'], 0)
        identity = build_semi_finished_identity(bom_line=self.parts[0], completed_craft=component_stock_craft('CUTTING'),unit=self.piece_unit)
        credit_public_stock(identity=identity, zone=self.semi_zone, quantity=30, source_type='TEST_WAREHOUSE_BENCH',
                            source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee)
        order, _ = self.dispatch_part(order,20,'PUBLIC_PIECE')
        order, _ = self.dispatch_part(order, 4, 'CUTTING')
        self.receive_part(order,3)
        TubeOutsourcingOrder.objects.filter(pk=order['id']).update(expected_return_date=today-timedelta(days=1))
        self.assertEqual(board.overview(req,'returns',today)['breakdown']['overdue'],1)
        for key,want_done,unit in [('dispatch','20','片'),('returns','3','个')]:
            total,rows=board.items(req,key,{'page':1,'page_size':1})
            self.assertEqual((total,rows[0]['id']),(1,order['id']))
            detail=board.detail(req,key,'tube',order['id'])
            self.assertIn((want_done,unit),[(v['done'],v['unit']) for v in detail['lines']])
            if key == 'dispatch':
                material = next(line for line in detail['lines'] if line['done'] == '20')
                self.assertEqual((material['required'], material['remaining']), ('196', '176'))
                self.assertIn('另有直发 4 片', material['name'])
            self.assertEqual(len(detail['movements']),2)
            self.assertEqual(detail['related']['id'],order['id'])
            self.assertEqual(board.activity(req,key,today,today,0,0),(1,[]))
            self.assertEqual(len(board.activity(req,key,today,today,1,0)[1]),1)
        TubeOutsourcingOrder.objects.get(pk=order['id']).plan_receipts.update(voided_at=timezone.now())
        self.assertEqual(board.activity(req,'returns',today,today,2,0),(0,[]))

    def test_workshop_direct_shipment_is_not_warehouse_dispatch(self):
        today=timezone.localdate()
        request=self.request()
        order=self.create_part_plan('CUTTING')
        self.assertEqual(board.overview(request,'dispatch',today)['count'],0)
        self.dispatch_part(order,4)
        self.assertEqual(board.activity(request,'dispatch',today,today,10,0),(0,[]))
        self.assertEqual(board.overview(request,'returns',today)['count'],1)

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True)
    def test_action_permission_and_actual_order_scope(self):
        order=self.create_part_plan('PUBLIC_PIECE')
        self.scoped_actor()
        self.grant(DISPATCH_PERMISSION,'CRAFT',[self.print_craft])
        req=self.request(scoped=True)
        self.assertEqual(board.overview(req,'dispatch',timezone.localdate())['count'],0)
        self.assertIsNone(board.overview(req,'returns',timezone.localdate())['count'])
        with self.assertRaises(NotFound):
            board.detail(req,'dispatch','tube',order['id'])
        with self.assertRaises(PermissionDenied):
            board.items(req,'returns',{'page':1,'page_size':20})
        self.grant(RETURN_PERMISSION,'CRAFT',[self.external_sewing])
        self.assertEqual(board.overview(self.request(scoped=True),'dispatch',timezone.localdate())['count'],0)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True,
                   MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class WarehouseMetalReturnTests(plans.D1Fixture, APITestCase):
    def test_direct_factory_handoff_and_partial_warehouse_receipt(self):
        today = timezone.localdate()
        source = self.source
        source.source_snapshot = {'product_line_id': str(self.product_line.pk), 'part_name': self.metal_bom_line.part_name,
                                  'conversion_snapshot': {'bom_line_id': str(self.metal_bom_line.pk)}}
        source.completed_pieces = source.dispatched_pieces = 8
        source.save(update_fields=['source_snapshot', 'completed_pieces', 'dispatched_pieces'])

        order = OutsourcingOrder.objects.create(
            order_number='WORKBENCH-METAL', schedule=self.schedule_product.schedule, craft=self.spray,
            craft_name_snapshot=self.spray.name, delivery_date=today, status='PARTIAL_RETURN',
            client_request_id=uuid4(), created_by_employee=self.employee, updated_by_employee=self.employee)
        product = OutsourcingOrderProduct.objects.create(order=order, schedule_product=self.schedule_product,
            bom=self.bom, line_number=1, order_quantity_snapshot=8, planned_quantity_snapshot=8, bom_version_snapshot=1)
        part = OutsourcingProcessingItem.objects.create(order_product=product, bom_line=self.metal_bom_line,
            line_number=1, quantity=8, unit=self.piece_unit, unit_snapshot='支', component_snapshot={'part_name': self.metal_bom_line.part_name})
        allocation = OutsourcingFactoryAllocation.objects.create(processing_item=part, factory=self.factory,
                                                                   allocated_quantity=8, unit_price=1)
        MetalProcessingOriginalHandoff.objects.create(original_order=order, source=source, factory=self.factory,
            handoff_pieces=8, handoff_date=today, actor_employee=self.employee, request_id=uuid4())
        balance = SemiFinishedStockBalance.objects.create(production_task=self.task, product_line=self.product_line,
            bom_line=self.metal_bom_line, completed_craft=self.spray, unit=self.piece_unit, zone=self.semi_zone, quantity=3)
        receipt = OutsourcingReturn.objects.create(return_number='WORKBENCH-METAL-R1', order=order, factory=self.factory,
            client_request_id=uuid4(), zone=self.semi_zone, received_by_employee=self.employee,
            confirmed_by_employee=self.employee, confirmed_at=timezone.now(), return_date=today)
        OutsourcingReturnLine.objects.create(return_record=receipt, allocation=allocation, returned_quantity=3,
            quality='AVAILABLE', semi_finished_balance=balance, snapshot={'source_id': str(source.pk)})

        request = SimpleNamespace(user=self.user, employee=self.employee, query_params={})
        self.assertEqual(board.activity(request, 'dispatch', today, today, 10, 0), (0, []))
        result = board.detail(request, 'returns', 'metal_original', order.pk)
        self.assertEqual([(r['required'], r['done'], r['remaining']) for r in result['lines']], [('8', '3', '5')])
        self.assertEqual(result['row']['task_number'], self.task.task_number)
        self.assertEqual(len(result['movements']), 1)
        count, receipts = board.activity(request, 'returns', today, today, 10, 0)
        self.assertEqual(count, 1)
        self.assertEqual(receipts[0]['number'], result['movements'][0]['number'])
