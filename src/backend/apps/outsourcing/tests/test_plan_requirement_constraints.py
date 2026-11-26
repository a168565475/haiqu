"""合并约束：允许实际领用超BOM，保留整数/非负及计划凭证保护。"""
import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from apps.boms.models import BomLine, BomSection
from apps.inventory.stock_services import credit_material_stock
from apps.material_issues.models import OrderMaterialRequirement
from apps.material_issues.requirements import sync_order_requirements
from apps.products.models import RawMaterialInformation
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductionUnit, ProductCategory
from ..models import OutsourcingFactoryCraft
from . import test_plan_cutting_api as cutting_fixtures
from .test_tube_orders_api import TubeApiFixture


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class PlanRequirementConstraintTests(TubeApiFixture, APITestCase):
    def test_database_retains_actual_outsourcing_above_bom(self):
        OrderMaterialRequirement.objects.filter(pk=self.requirement.pk).update(outsourcing_issued_quantity=250)
        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.required_quantity, 210)
        self.assertEqual(self.requirement.internal_issued_quantity, 100)
        self.assertEqual(self.requirement.outsourcing_issued_quantity, 250)

    def test_database_still_rejects_nonwhole_negative_but_allows_internal_overage(self):
        for fields in ({'required_quantity': Decimal('210.5')}, {'internal_issued_quantity': Decimal('100.5')},
                {'outsourcing_issued_quantity': Decimal('250.5')}, {'internal_issued_quantity': -1},
                {'outsourcing_issued_quantity': -1}, {'required_quantity': 0}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    OrderMaterialRequirement.objects.filter(pk=self.requirement.pk).update(**fields)
        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.outsourcing_issued_quantity, 0)
        OrderMaterialRequirement.objects.filter(pk=self.requirement.pk).update(internal_issued_quantity=211)
        self.requirement.refresh_from_db()
        self.assertEqual(self.requirement.required_quantity, 210)
        self.assertEqual(self.requirement.internal_issued_quantity, 211)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    PUBLIC_STOCK_ISSUES_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False,
    ACCESS_RESOURCE_SCOPES_ENABLED=False)
class PlanMaterialRequirementMergeTests(cutting_fixtures.SewingProcessingFixture, TestCase):
    context = cutting_fixtures.PlanCuttingApiTests.context
    plan = cutting_fixtures.PlanCuttingApiTests.plan
    dispatch = cutting_fixtures.PlanCuttingApiTests.dispatch

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        ProductionScheduleProductCraft.objects.get_or_create(schedule_product=self.schedule_product, craft=self.print_craft,
            defaults={'craft_type_snapshot': 'EXTERNAL', 'craft_name_snapshot': self.print_craft.name})
        OutsourcingFactoryCraft.objects.get_or_create(factory=self.factory, craft=self.print_craft,
            defaults={'craft_name_snapshot': self.print_craft.name})

    def test_real_plan_dispatch_exempts_reduced_requirement_but_unbacked_issue_does_not(self):
        unit, _ = ProductionUnit.objects.get_or_create(unit_name='个', defaults={'unit_code': 'PLAN-MERGE-COUNT'})
        category, _ = ProductCategory.objects.get_or_create(category_name='辅料', item_type='MATERIAL')
        raw = RawMaterialInformation.objects.create(material_number='PLAN-MERGE-AUX', item_type='MATERIAL',
            category=category, unit=unit, material_name='合并回归扣件', material='塑料', specification='M6', color_snapshot='黑色')
        section = BomSection.objects.create(bom=self.bom, line_number=4, section_type='FABRIC', title='辅料类')
        line = BomLine.objects.create(section=section, line_number=1, part_name='合并回归扣件', category='辅料',
            material='塑料', specification='M6', unit='个', unit_consumption='2', total_consumption='1000',
            raw_values={'source_inventory_material_id': str(raw.pk), 'accessory_color': '黑色'})
        material = {'bom_line_id': str(line.pk), 'factory_id': str(self.factory.pk),
            'quantity': '1200', 'zone_id': str(self.zone.pk)}
        order = self.plan(materials=[material])
        stock = credit_material_stock(raw_material=raw, unit=unit, zone=self.zone, quantity=1300,
            source_type='TEST_PLAN_MERGE', source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
            actor_employee=self.employee).balance
        order = self.dispatch(order, 100, materials=[material])
        material['quantity'] = '50'
        order = self.dispatch(order, 10, materials=[material])
        requirement = OrderMaterialRequirement.objects.get(production_task=self.task, raw_material=raw)
        stock.refresh_from_db()
        self.assertEqual((requirement.required_quantity, requirement.internal_issued_quantity,
                          requirement.outsourcing_issued_quantity, stock.quantity), (1000, 0, 1250, 50))
        self.assertEqual(len(order['dispatch_records']), 2)

        # 真正降低建议量，避免仅凭“建议未变”分支掩盖计划凭证豁免丢失。
        line.total_consumption = '999'
        line.save(update_fields=['total_consumption', 'updated_at'])
        sync_order_requirements(self.task.pk)
        requirement.refresh_from_db()
        self.assertEqual((requirement.required_quantity, requirement.outsourcing_issued_quantity), (999, 1250))

        # 直接增加无凭证计数仅用于边界注入，不代表真实发出业务流程。
        requirement.outsourcing_issued_quantity += 1500
        requirement.save(update_fields=['outsourcing_issued_quantity'])
        line.total_consumption = '998'
        line.save(update_fields=['total_consumption', 'updated_at'])
        with self.assertRaisesMessage(ValidationError, 'REQUIREMENT_BELOW_ISSUED'):
            sync_order_requirements(self.task.pk)
        requirement.refresh_from_db()
        stock.refresh_from_db()
        self.assertEqual((requirement.required_quantity, requirement.internal_issued_quantity,
                          requirement.outsourcing_issued_quantity, stock.quantity), (999, 0, 2750, 50))
