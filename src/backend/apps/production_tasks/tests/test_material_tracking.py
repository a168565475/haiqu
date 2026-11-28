from datetime import date

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.inventory.models import MaterialInbound
from apps.inventory.tests.finished_receipt_fixture import historical_finished_receipt
from apps.inventory.tests.test_assembly_receipts import AssemblyFixture
from apps.procurement.models import PurchaseOrder
from apps.procurement.tests.test_multi_product_purchase import MultiProductPurchaseFixture
from apps.production_tasks.models import ProductionTaskProduct
from apps.workshop_reporting.models import WorkshopPlanExecution

from .test_director_workbench import SCHEDULE, assign_role, director

URL = "/api/v1/material-tracking/"


@override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class FabricTrackingTests(MultiProductPurchaseFixture, APITestCase):
    def setUp(self):
        super().setUp()
        assign_role(self.employee, "TRACKING_FABRIC", [SCHEDULE])
        self.add_fabrics([("红", "R1"), ("蓝", "B1")])
        self.red_fabric = self.red_bom.sections.get(title="面料类").lines.get()
        self.blue_fabric = self.blue_bom.sections.get(title="面料类").lines.get()
        self.red_fabric.total_purchase_quantity = "1000"
        self.red_fabric.save(update_fields=["total_purchase_quantity"])
        self.order = PurchaseOrder.objects.create(
            production_task=self.task, order_number="CGDD261102001", status="PURCHASING",
            production_task_number_snapshot=self.task.task_number,
        )

    def purchase_line(self, bom_line, *, contributions=None):
        bom = bom_line.section.bom
        return self.order.lines.create(
            line_number=self.order.lines.count() + 1,
            bom=bom, bom_line=bom_line, product_line_id_snapshot=bom.product_line_id,
            calculation_snapshot={"group_source_contributions": contributions} if contributions else {},
            material_catalog=bom_line.material_catalog, material_selection_snapshot=bom_line.material_selection_snapshot,
            section_type_snapshot="FABRIC", section_title_snapshot="面料类",
            source_unit_text="米", actual_purchase_quantity=2000, quantity_parse_status="READY",
        )

    def receive_fabric(self, line, day, quantity, *, status="CONFIRMED"):
        inbound = MaterialInbound.objects.create(
            inbound_number=f"TRACKING-{MaterialInbound.objects.count() + 1}",
            purchase_order=self.order, inbound_date=date(2026, 11, day),
            status=status, received_by_employee=self.employee,
        )
        inbound.lines.create(
            purchase_order_line=line, material_catalog=line.material_catalog,
            material_selection_snapshot=line.material_selection_snapshot, zone=self.zone,
            received_quantity=quantity, accepted_quantity=quantity,
            purchased_quantity_snapshot=line.actual_purchase_quantity, source_unit_text_snapshot="米",
        )
        return inbound.inbound_number

    def rows(self):
        response = self.client.get(URL, {"task_number": self.task.task_number.lower()})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["id"] for row in response.data["data"]], [str(self.red.pk), str(self.blue.pk)])
        return response.data["data"]

    def test_partial_and_supplemental_receipts_keep_the_first_complete_day_and_product(self):
        line = self.purchase_line(self.red_fabric)
        first = self.receive_fabric(line, 2, 600)
        second = self.receive_fabric(line, 5, 400)
        pending = self.receive_fabric(line, 1, 1000, status="PENDING_QUALITY")
        self.assertEqual(self.rows()[0]["stages"]["fabric_arrival"]["date"], "2026-11-05")
        extra = self.receive_fabric(line, 8, 20)
        red, blue = self.rows()
        self.assertEqual(red["stages"]["fabric_arrival"]["date"], "2026-11-05")
        self.assertEqual(blue["stages"]["fabric_arrival"]["note"], "未到齐")
        red_detail = self.client.get(f"{URL}{self.red.pk}/").data["data"]
        blue_detail = self.client.get(f"{URL}{self.blue.pk}/").data["data"]
        self.assertEqual(red_detail["fabrics"][0]["total_received"], "1020")
        self.assertEqual([row["number"] for row in red_detail["batches"] if row["kind"] == "fabric_arrival"],
                         [first, second, extra])
        self.assertNotIn(pending, {row["number"] for row in red_detail["batches"]})
        self.assertFalse(blue_detail["batches"])

    def test_different_specifications_and_unallocated_common_receipts(self):
        additional_spec = self.red_fabric.section.lines.create(
            line_number=2, part_name="配色面料", unit="米", total_purchase_quantity="100",
            material_catalog=self.blue_fabric.material_catalog,
            material_selection_snapshot=self.blue_fabric.material_selection_snapshot,
        )
        self.receive_fabric(self.purchase_line(self.red_fabric), 2, 1200)
        sources = [{"product_line_id": str(bom.product_line_id), "bom_id": str(bom.pk),
                    "product_name": bom.product_name_snapshot, "product_specification": bom.specification_snapshot}
                   for bom in (self.red_bom, self.blue_bom)]
        common = self.receive_fabric(self.purchase_line(additional_spec, contributions=sources), 4, 200)
        red, blue = self.rows()
        self.assertIsNone(red["stages"]["fabric_arrival"]["date"])
        self.assertEqual(red["stages"]["fabric_arrival"]["note"], "1/2 规格到齐")
        self.assertEqual(blue["stages"]["fabric_arrival"]["note"], "共采待分配")
        detail = self.client.get(f"{URL}{self.red.pk}/").data["data"]
        self.assertCountEqual([row["arrived_on"] for row in detail["fabrics"]], ["2026-11-02", None])
        shared = next(row for row in detail["batches"] if row["number"] == common)
        self.assertEqual((shared["date"], shared["quantity"], shared["note"]), (None, None, "共采待分配"))
        self.receive_fabric(self.purchase_line(additional_spec), 7, 100)
        red = self.rows()[0]
        self.assertEqual(red["stages"]["fabric_arrival"]["note"], "2/2 规格到齐")
        self.assertIsNone(red["stages"]["fabric_arrival"]["date"])


@override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class WorkshopTrackingTests(AssemblyFixture, APITestCase):
    def setUp(self):
        self.prepare()

    def test_workshop_scope_is_applied_to_list_and_detail(self):
        other = ProductionTaskProduct.objects.create(
            production_task=self.task, line_number=2, product_name_snapshot="同单其他产品", quantity=20,
            currency=self.line.currency, unit_price=self.line.unit_price, total_amount=20 * self.line.unit_price,
            exchange_rate=self.line.exchange_rate,
        )
        viewer, _, _ = director("TRACKING_ASSEMBLY", self.craft.workshop, [SCHEDULE])
        response = viewer.get(URL, {"task_number": self.task.task_number})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["id"] for row in response.data["data"]], [str(self.line.pk)])
        self.assertEqual(viewer.get(f"{URL}{self.line.pk}/").status_code, 200)
        self.assertEqual(viewer.get(f"{URL}{other.pk}/").status_code, 404)
        self.assertEqual(viewer.get(URL, {"page_size": 0}).status_code, 400)
        self.assertEqual(viewer.post(URL, {}).status_code, 405)
        restricted, _, _ = director("TRACKING_NO_PLAN", self.craft.workshop, [])
        self.assertEqual(restricted.get(URL).status_code, 403)
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_actual_assembly_records_and_only_confirmed_finished_quantities(self):
        historical_finished_receipt(product_line=self.line, actor=self.employee, location_id=self.location_id,
                                    quantity=4, quantity_per_box=None)
        pending = self.post(self.payload(received_quantity=3))
        self.assertEqual(pending.status_code, 201, pending.data)
        expected = [{"quantity": "4", "unit": self.line.unit.unit_name}]
        row = self.client.get(URL).data["data"][0]
        self.assertEqual(row["finished_quantities"], expected)
        self.assertEqual(row["assembly_lines"], [1])
        self.assertEqual(row["stages"]["assembly_first"]["date"], str(timezone.localdate()))
        self.assertIsNone(row["stages"]["assembly_completion"]["date"])
        WorkshopPlanExecution.objects.create(
            schedule_product=self.plan, craft=self.craft, status="COMPLETED", completed_at=timezone.now(),
        )
        self.confirm(pending)
        row = self.client.get(URL).data["data"][0]
        self.assertEqual(row["finished_quantities"], [{"quantity": "7", "unit": self.line.unit.unit_name}])
        self.assertEqual(row["stages"]["assembly_completion"]["date"], str(timezone.localdate()))
