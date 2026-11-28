from datetime import date, timedelta
from uuid import uuid4

from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from apps.boms.models import BomLine
from apps.core.delivery_reminders import business_today
from apps.inventory.part_flow_receipts import component_stock_craft
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from ..models import (
    OutsourcingFactory, OutsourcingFactoryCraft, OutsourcingMaterialItem, TubeOutsourcingAction, TubeOutsourcingOrder,
    TubeOutsourcingReceipt, TubeOutsourcingReceiptLine,
)
from . import test_material_flow as historical, test_part_flow_plan_api as plans


URL = "/api/v1/sewing-tracking/"
BASE = plans.BASE
PLANNED = "2026-11-25"
DUE = "2026-11-30"
FIELDS = ("sent", "received", "factory_remaining", "not_sent")


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, PUBLIC_STOCK_ISSUES_ENABLED=True,
                   MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class SewingTrackingTests(plans.PartFlowPlanFixture, APITestCase):
    part_context = plans.PartFlowPlanApiTests.part_context

    def setup_sample(self, quantity):
        self.task.task_number = "TEST-SEWING-20261127"
        self.task.save(update_fields=["task_number"])
        self.factory.name = "甲厂"
        self.factory.save(update_fields=["name"])
        self.part.part_name = "左扶手"
        self.part.save(update_fields=["part_name"])
        self.product_line.quantity = quantity
        self.product_line.color_name_snapshot = "蓝色"
        self.product_line.save(update_fields=["quantity", "color_name_snapshot"])
        self.schedule_product.planned_quantity = self.schedule_product.source_quantity_snapshot = quantity
        self.schedule_product.save(update_fields=["planned_quantity", "source_quantity_snapshot"])
        self.bom.order_quantity = quantity
        self.bom.save(update_fields=["order_quantity"])

    def move_piece_to_part(self, piece, name, unit):
        part = BomLine.objects.create(section=self.part.section, line_number=10 + piece.line_number,
                                      component_kind="SEWN_PART", part_name=name, unit=unit, parts_per_product=1)
        piece.parent_part = part
        piece.save(update_fields=["parent_part"])
        return part

    def make_plan(self, lines, *, planned=PLANNED, due=DUE):
        context = self.part_context()
        response = self.client.post(BASE, {
            "is_plan": True, "client_request_id": str(uuid4()), "source_revision": context["source_revision"],
            "schedule_product_id": str(self.schedule_product.pk), "source_kind": "CUTTING",
            "craft_id": str(self.external_sewing.pk), "planned_dispatch_date": planned, "expected_return_date": due,
            "lines": [{"component_identity": str(part.component_identity), "quantity": quantity,
                       "unit_price": "1.00", "factory_id": str(factory.pk)} for part, factory, quantity in lines],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["data"]

    def stock(self, *pieces):
        for piece, quantity in pieces:
            identity = build_semi_finished_identity(
                bom_line=piece, completed_craft=component_stock_craft("CUTTING"), unit=self.piece_unit,
            )
            credit_public_stock(identity=identity, zone=self.semi_zone, quantity=quantity,
                                source_type="SEWING_TRACKING_TEST", source_id=uuid4(), source_line_id=uuid4(),
                                actor_employee=self.employee)

    def action(self, order, endpoint, **data):
        response = self.client.post(f"{BASE}{order['id']}/{endpoint}/", {
            "client_request_id": str(uuid4()), **data,
        }, format="json", HTTP_IF_MATCH=order["etag"])
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def send(self, order, *pieces, day=PLANNED):
        return self.action(order, "plan-dispatch", actual_dispatch_date=day, source_kind="PUBLIC_PIECE",
                           zone_id=str(self.semi_zone.pk), inputs=[
                               {"component_identity": str(piece.component_identity), "quantity": quantity}
                               for piece, quantity in pieces
                           ])

    def receive(self, order, part, quantity, day):
        line, = [line for line in order["lines"] if line["component_identity"] == str(part.component_identity)]
        return self.action(order, "plan-receipt", receipt_date=day, warehouse_id=str(self.semi_zone.warehouse_id),
                           lines=[{"order_line_id": line["id"], "received_quantity": quantity,
                                   "zone_id": str(self.semi_zone.pk)}])

    def results(self, *, key="factory_name", **filters):
        response = self.client.get(URL, {"task_number": self.task.task_number.lower(), **filters})
        self.assertEqual(response.status_code, 200, response.data)
        return {row[key]: row for row in response.data["data"]}

    def check_factory(self, factory, quantities, day):
        row = self.results()[factory]
        self.assertEqual(row["task_number"], self.task.task_number)
        self.assertEqual(row["color"], "蓝色")
        self.assertEqual(row["planned_dispatch_dates"], [PLANNED])
        self.assertEqual(row["expected_return_dates"], [DUE])
        self.assertEqual(row["last_receipt_date"], day)
        self.assertEqual([row[field] for field in FIELDS], [
            [{"unit": "个", "quantity": str(amount)}] for amount in quantities
        ])

    def test_task_number_example_and_void_last_receipt(self):
        self.setup_sample(1000)
        face, side = self.parts
        face.pieces_per_part = 1
        face.save(update_fields=["pieces_per_part"])
        other_part = self.move_piece_to_part(self.cotton, "右扶手", "个")
        other = OutsourcingFactory.objects.create(
            factory_number="SEWING-TRACKING-B", name="乙厂", processing_type="车缝",
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        OutsourcingFactoryCraft.objects.create(factory=other, craft=self.external_sewing,
                                               craft_name_snapshot=self.external_sewing.name)
        order = self.make_plan([(self.part, self.factory, 1000), (other_part, other, 100)])
        self.check_factory("甲厂", (0, 0, 0, 1000), None)
        self.check_factory("乙厂", (0, 0, 0, 100), None)
        assigned = self.results()["甲厂"]
        self.assertEqual(assigned["part_name"], "左扶手")
        self.assertEqual(assigned["unit_prices"], [{"amount": "1", "unit": "个"}])
        self.assertEqual(assigned["dispatch_dates"], [])
        self.stock((face, 700), (side, 1200), (self.cotton, 50))

        order = self.send(order, (face, 349), (side, 599))
        order = self.send(order, (face, 351), (side, 601), (self.cotton, 50), day="2026-11-26")
        self.check_factory("甲厂", (600, 0, 600, 400), None)
        sent = self.results()
        self.assertEqual(sent["甲厂"]["dispatch_dates"], [PLANNED, "2026-11-26"])
        self.assertEqual(sent["乙厂"]["part_name"], "右扶手")
        self.assertEqual(sent["乙厂"]["dispatch_dates"], ["2026-11-26"])
        order = self.receive(order, self.part, 400, "2026-11-28")
        self.check_factory("甲厂", (600, 400, 200, 400), "2026-11-28")
        reminder = self.results(owner="甲厂")["甲厂"]["reminder"]
        self.assertEqual((reminder["action"], reminder["quantity"], reminder["unit"], reminder["due"]),
                         ("催回厂", "200", "个", DUE))
        internal = self.results(owner="我方")["甲厂"]["reminder"]
        self.assertEqual((internal["action"], internal["quantity"], internal["due"]), ("我方待发", "400", PLANNED))

        order = self.receive(order, other_part, 20, "2026-11-29")
        order = self.receive(order, self.part, 200, DUE)
        self.check_factory("甲厂", (600, 600, 0, 400), DUE)
        self.assertEqual(self.results(owner="甲厂"), {})
        self.check_factory("乙厂", (50, 20, 30, 50), "2026-11-29")
        latest, = [record for record in order["receipt_records"] if str(record["receipt_date"]) == DUE]
        self.action(order, "plan-record-correction", record_kind="RECEIPT", record_id=latest["id"], operation="DELETE")
        self.check_factory("甲厂", (600, 400, 200, 400), "2026-11-28")
        self.check_factory("乙厂", (50, 20, 30, 50), "2026-11-29")

    def test_fulfilled_earlier_deadline_does_not_make_later_batch_overdue(self):
        self.setup_sample(100)
        today = business_today()
        planned = (today - timedelta(days=10)).isoformat()
        early_due = (today - timedelta(days=2)).isoformat()
        later_due = (today + timedelta(days=4)).isoformat()
        pieces = tuple((piece, piece.pieces_per_part * 50) for piece in (*self.parts, self.cotton))
        self.stock(*pieces)
        data = self.make_plan([(self.part, self.factory, 50)], planned=planned, due=early_due)
        early = TubeOutsourcingOrder.objects.get(pk=data["id"])
        early.is_plan, early.status, early.source_snapshot = False, "COMPLETED", {}
        early.save(update_fields=["is_plan", "status", "source_snapshot"])
        TubeOutsourcingAction.objects.create(order=early, kind="DISPATCH", actual_dispatch_date=planned,
            actor_employee=self.employee, client_request_id=uuid4(), request_payload_hash="earlier-dispatch")
        receipt = TubeOutsourcingReceipt.objects.create(order=early, receipt_number="SEWING-EARLY-QA",
            receipt_date=early_due, client_request_id=uuid4(), request_payload_hash="earlier-receipt",
            warehouse=self.semi_zone.warehouse, actor_employee=self.employee)
        identity = build_semi_finished_identity(bom_line=self.part, completed_craft=component_stock_craft("SEWING"), unit=self.part_unit)
        movement = credit_public_stock(identity=identity, zone=self.semi_zone, quantity=50,
            source_type="SEWING_TRACKING_TEST", source_id=receipt.pk, source_line_id=uuid4(), actor_employee=self.employee)
        TubeOutsourcingReceiptLine.objects.create(receipt=receipt, order_line=early.lines.get(), dispatched_quantity=50,
            received_quantity=50, shortage_quantity=0, zone=self.semi_zone, stock_movement=movement)
        late = self.make_plan([(self.part, self.factory, 50)], planned=planned, due=later_due)
        self.send(late, *pieces, day=planned)

        self.assertEqual(self.results(follow_up="FOLLOW_UP"), {})
        row = self.results()["甲厂"]
        self.assertEqual(row["expected_return_dates"], [early_due, later_due])
        reminder = row["reminder"]
        self.assertEqual((reminder["status"], reminder["due"], reminder["quantity"], reminder["reference"]),
                         ("UPCOMING", later_due, "50", late["order_number"]))

    def test_same_factory_parts_keep_independent_rows_receipts_and_units(self):
        self.setup_sample(100)
        first, paired = self.parts
        second = self.move_piece_to_part(paired, "右扶手", "个")
        third = self.move_piece_to_part(self.cotton, "配套布面", "套")
        order = self.make_plan([(part, self.factory, 100) for part in (self.part, second, third)])
        self.stock((first, 20), (paired, 40), (self.cotton, 9))
        order = self.send(order, (first, 20), (paired, 40), (self.cotton, 9))
        order = self.receive(order, self.part, 30, "2026-11-28")
        self.receive(order, third, 4, "2026-11-29")
        rows = self.results(key="part_name")
        self.assertEqual(set(rows), {"左扶手", "右扶手", "配套布面"})
        self.assertEqual(len({row["id"] for row in rows.values()}), 3)
        for name, unit, quantities, day in (
            ("左扶手", "个", (10, 30, 0, 90), "2026-11-28"),
            ("右扶手", "个", (20, 0, 20, 80), None),
            ("配套布面", "套", (9, 4, 5, 91), "2026-11-29"),
        ):
            row = rows[name]
            self.assertEqual(row["factory_name"], "甲厂")
            self.assertEqual(row["last_receipt_date"], day)
            self.assertEqual([row[field] for field in FIELDS], [
                [{"unit": unit, "quantity": str(amount)}] for amount in quantities
            ])

    def test_completed_historical_order_retains_whole_sets(self):
        self.setup_sample(100)
        data = self.make_plan([(self.part, self.factory, 100)])
        order = TubeOutsourcingOrder.objects.get(pk=data["id"])
        order.is_plan, order.status, order.source_snapshot = False, "COMPLETED", {}
        order.save(update_fields=["is_plan", "status", "source_snapshot"])
        line = order.lines.get()
        line.snapshot = {"unit": "套", "factory_name": "甲厂"}
        line.save(update_fields=["snapshot"])
        TubeOutsourcingAction.objects.create(order=order, kind="DISPATCH", actual_dispatch_date=date.fromisoformat(PLANNED),
            actor_employee=self.employee, client_request_id=uuid4(), request_payload_hash="historical-tracking")
        row = self.results()["甲厂"]
        self.assertEqual(row["sent"], [{"unit": "套", "quantity": "100"}])
        self.assertEqual(row["received"], [{"unit": "套", "quantity": "0"}])
        self.assertIsNone(row["last_receipt_date"])

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True)
    def test_only_existing_view_scope_can_query_the_list(self):
        self.setup_sample(100)
        self.factory.contact_phone = "000-00000000"
        self.factory.save(update_fields=["contact_phone"])
        self.make_plan([(self.part, self.factory, 100)])
        self.scoped_actor()
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(APIClient().get(URL).status_code, 401)
        code = "outsourcing.view_outsourcingorder"
        self.grant(code, "FOLLOWED")
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.grant(code, "CRAFT", [self.print_craft])
        self.assertEqual(self.results(), {})
        self.grant(code, "CRAFT", [self.external_sewing])
        self.check_factory("甲厂", (0, 0, 0, 100), None)
        factory_url = f"/api/v1/outsourcing-factories/{self.factory.pk}/"
        self.assertEqual(self.client.get(factory_url).status_code, 403)
        self.assertEqual(self.results()["甲厂"]["factory_phone"], "")
        self.grant("outsourcing.view_outsourcingfactory", "MODULE")
        self.assertEqual(self.client.get(factory_url).status_code, 200)
        self.assertEqual(self.results()["甲厂"]["factory_phone"], "000-00000000")
        self.assertEqual(self.client.get(URL, {"page_size": 0}).status_code, 400)
        self.assertEqual(self.client.get(URL, {"factory": "unavailable"}).status_code, 400)
        self.assertEqual(self.client.post(URL, {}).status_code, 405)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False)
class HistoricalSewingTrackingTests(historical.MaterialFlowFixture, APITestCase):
    def test_raw_fabric_returns_are_subtracted_before_folding_to_sets(self):
        order = self.create("FABRIC", "20", output_sets="10")
        self.freeze_legacy_fabric(order, meters_per_set="2")
        _, source = self.dispatch(order, "FABRIC", "20")
        self.raw_return(order, source, 4)
        self.return_goods(order, source, 8, raw_inputs=[self.entry(source, "RAW_INPUT", 16)])
        task = self.f.product_line.production_task.task_number

        with self.settings(PUBLIC_STOCK_FLOW_ENABLED=True):
            row, = self.client.get(URL, {"task_number": task}).data["data"]
            self.assertEqual([row[field][0]["quantity"] for field in FIELDS], ["10", "8", "0", "0"])
            self.assertIsNone(row["reminder"])
            OutsourcingMaterialItem.objects.filter(pk=source.material_item_id).update(conversion_snapshot={"kind": "FABRIC"})
            source.snapshot = {"kind": "FABRIC"}
            source.save(update_fields=["snapshot"])
            row, = self.client.get(URL, {"task_number": task, "follow_up": "REVIEW"}).data["data"]
            self.assertEqual((row["reminder"]["label"], row["reminder"]["quantity"]), ("数量待核", None))

    def test_meter_dispatch_with_or_without_frozen_conversion(self):
        order = self.create("FABRIC", "90", output_sets="100")
        self.freeze_legacy_fabric(order, meters_per_set="1.5")
        _, source = self.dispatch(order, "FABRIC", "90")
        self.return_goods(order, source, 40, raw_inputs=[self.entry(source, "RAW_INPUT", 90)])

        task = self.f.product_line.production_task.task_number

        def quantities():
            with self.settings(PUBLIC_STOCK_FLOW_ENABLED=True):
                response = self.client.get(URL, {"task_number": task})
            self.assertEqual(response.status_code, 200, response.data)
            row, = response.data["data"]
            self.assertEqual(row["task_number"], task)
            self.assertEqual(row["planned_dispatch_dates"], [])
            self.assertEqual(row["expected_return_dates"], [source.dispatch.order.delivery_date.isoformat()])
            return [row[field] for field in FIELDS]

        self.assertEqual(quantities(), [
            [{"unit": "套", "quantity": value}] for value in ("60", "40", "20", "40")
        ])
        OutsourcingMaterialItem.objects.filter(pk=source.material_item_id).update(conversion_snapshot={"kind": "FABRIC"})
        self.assertEqual(quantities(), [
            [{"unit": "套", "quantity": value}] for value in ("60", "40", "20", "40")
        ])
        source.snapshot = {"kind": "FABRIC"}
        source.save(update_fields=["snapshot"])
        self.assertEqual(quantities(), [
            [{"unit": "套", "quantity": value}] for value in (None, "40", None, None)
        ])
