from uuid import uuid4

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.boms.models import BomLine, BomSection
from apps.outsourcing.models import TubeOutsourcingOrder
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft, Operation, Workshop
from apps.workshop_config.tests.factories import production_employee
from . import test_workshop_reporting_api as reporting_fixture


class InternalSewingAssignmentTests(APITestCase):
    api = "/api/v1/workshop-reporting/"

    def setUp(self):
        reporting_fixture.WorkshopReportingApiTests.setUp(self)
        self.sewing_shop, _ = Workshop.objects.get_or_create(name="车缝车间")
        self.internal = Craft.objects.create(name="本厂车缝", craft_type="INTERNAL", plan_category="SEWING", workshop=self.sewing_shop)
        self.external = Craft.objects.create(name="委外车缝", craft_type="EXTERNAL", outsourcing_code="SEWING")
        ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product, craft=self.internal,
            craft_type_snapshot="INTERNAL", craft_name_snapshot=self.internal.name, plan_category="SEWING")
        unit, _ = ProductionUnit.objects.get_or_create(unit_name="套", catalog_owner=None, defaults={"unit_code": "WG-SET"})
        self.sew = Operation.objects.create(operation_number="WGA-SEW", product_name="布套", name="缝边",
            craft=self.internal, reporting_unit=unit)
        section = BomSection.objects.create(bom=self.bom, line_number=2, section_type="FABRIC", title="裁剪明细")
        self.parts = [BomLine.objects.create(section=section, line_number=i, part_name=name,
            component_kind="SEWN_PART", parts_per_product=1, unit="套") for i, name in enumerate(("坐垫", "靠背"), start=1)]

    def add_external_craft(self):
        ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product, craft=self.external,
            craft_type_snapshot="EXTERNAL", craft_name_snapshot=self.external.name)

    def save_assignment(self, internal):
        return TubeOutsourcingOrder.objects.create(order_number="WGA-OUT", schedule_product=self.schedule_product,
            product_line=self.product_line, bom=self.bom, craft=self.external, source_kind="CUTTING", is_plan=True,
            planned_dispatch_date=timezone.localdate(), expected_return_date=timezone.localdate(),
            client_request_id=uuid4(), created_by_employee=self.employee, updated_by_employee=self.employee,
            source_snapshot={"part_flow": True, "sewing_inputs": True, "internal_sewing_part_count": len(internal),
                "sewing_part_assignments": {"internal": [
                    {"component_identity": str(part.component_identity), "bom_line_id": str(part.pk),
                     "part_name": part.part_name, "quantity": 100, "unit": "套", "unit_price": "9.0000"}
                    for part in internal], "has_external": True}})

    def scheme_payload(self):
        return {"product_line_id": str(self.product_line.pk), "schedule_product_id": str(self.schedule_product.pk),
            "workshop_id": str(self.sewing_shop.pk), "craft_ids": [str(self.internal.pk)], "operation_product_name": "布套",
            "lines": [{"craft_id": str(self.internal.pk), "operation_id": str(self.sew.pk),
                "bom_line_id": str(part.pk), "display_name": part.part_name, "counting_mode": "SET",
                "declared_price": "2", "status": "ACTIVE"} for part in self.parts]}

    def test_pending_and_external_only_hide_sewing_and_reject_new_wages(self):
        self.add_external_craft()
        for stage in ("pending", "all_external"):
            if stage == "all_external":
                self.save_assignment([])
            with self.subTest(stage=stage):
                context = self.client.get(self.api + "context/", {"schedule_product_id": self.schedule_product.pk})
                self.assertEqual(context.status_code, 200, context.data)
                crafts = {row["id"] for row in context.data["data"]["crafts"]}
                self.assertNotIn(str(self.internal.pk), crafts)
                self.assertIn(str(self.craft.pk), crafts)
                plans = self.client.get(reverse("production-schedule-item-list"),
                                        {"category": "SEWING", "schedule_product_id": self.schedule_product.pk})
                self.assertEqual(plans.status_code, 200, plans.data)
                self.assertEqual(plans.data["data"], [])
                mobile = self.client.get(reverse("workshop-mobile-plan", args=[self.schedule_product.pk]),
                                         {"workshop_id": self.sewing_shop.pk, "plan_category": "SEWING"})
                self.assertEqual(mobile.status_code, 404, mobile.data)
                form = self.client.get(self.api + "wage-schemes/mobile-form/",
                                       {"schedule_product_id": self.schedule_product.pk, "craft_id": self.internal.pk})
                self.assertEqual(form.status_code, 404, form.data)
                response = self.client.post(self.api + "wage-schemes/", self.scheme_payload(), format="json")
                self.assertEqual(response.status_code, 400, response.data)

    def test_mixed_assignment_filters_previously_approved_scheme_and_preserves_wage(self):
        scheme = reporting_fixture.WorkshopReportingApiTests.create_approved_scheme(self).data["data"]
        self.add_external_craft()
        self.save_assignment([self.parts[0]])
        query = {"product_line_id": self.product_line.pk, "schedule_product_id": self.schedule_product.pk,
                 "workshop_id": self.sewing_shop.pk, "craft_id": self.internal.pk, "production_date": timezone.localdate()}
        context = self.client.get(self.api + "work-reports/price-context/", query)
        self.assertEqual(context.status_code, 200, context.data)
        self.assertEqual([line["bom_component_identity"] for line in context.data["data"]["lines"]],
                         [str(self.parts[0].component_identity)])
        worker = production_employee(workshop=self.sewing_shop, position="车缝", name="车缝员工")
        ids = {line["bom_component_identity"]: line["id"] for line in scheme["lines"]}
        for part, expected in [(self.parts[1], 400), (self.parts[0], 201)]:
            body = {"schedule_product_id": str(self.schedule_product.pk), "production_date": str(timezone.localdate()),
                    "client_request_id": str(uuid4()), "scheme_id": scheme["id"], "scheme_revision": scheme["revision"],
                    "lines": [{"scheme_line_id": ids[str(part.component_identity)], "workshop_employee_id": str(worker.pk), "quantity": "3"}]}
            report = self.client.post(self.api + "work-reports/", body, format="json")
            self.assertEqual(report.status_code, expected, report.data)
        self.assertEqual(report.data["data"]["total_amount"], "6.00")
