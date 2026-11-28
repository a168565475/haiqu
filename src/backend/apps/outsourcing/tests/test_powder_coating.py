import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.core.delivery_reminders import business_today
from apps.inventory.models import PublicStockMovement
from apps.inventory.public_stock_identity import build_semi_finished_identity
from apps.inventory.public_stock_services import credit_public_stock
from apps.material_issues.tests.test_metal_processing_p4 import MetalProcessingP4Fixture
from apps.workshop_config.models import Craft

from ..models import OutsourcingRawReturnLine, OutsourcingReturn, OutsourcingReturnLine, TubeOutsourcingOrder
from .test_material_flow import MaterialFlowFixture
from .test_plan_orders_api import PlanApiFixture
from .test_plan_record_corrections import CorrectionApiMixin
from .test_tube_orders_api import BASE
from .test_tube_receipts_api import TubeReceiptFixture


URL = "/api/v1/powder-coating-movements/"
REMINDERS = "/api/v1/powder-coating-reminders/"


class PowderCoatingFixture(PlanApiFixture):
    def split_movements(self, *, keep_open=False):
        self.metal_bom_line.part_name = "前脚管"
        self.metal_bom_line.specification = "20×1.0"
        self.metal_bom_line.save(update_fields=["part_name", "specification"])
        identity = build_semi_finished_identity(bom_line=self.metal_bom_line, completed_craft=self.craft, unit=self.piece_unit)
        credit_public_stock(identity=identity, zone=self.semi_zone, quantity=320,
                            source_type="TEST_POWDER_OPENING", source_id=uuid.uuid4(), source_line_id=uuid.uuid4(),
                            actor_employee=self.employee)
        order = self.plan(quantity="200" if keep_open else "750")
        dispatches = (("METAL", "100"), ("PUBLIC_SEMI", "100")) if keep_open else (("METAL", "400"), ("PUBLIC_SEMI", "300"))
        for source, quantity in dispatches:
            order = self.write_plan(order, "dispatch", {
                **self.dispatch_payload(source, quantity), "actual_dispatch_date": str(self.today - timedelta(days=1)),
            })
        for quantity in (("60", "40") if keep_open else ("200", "150")):
            order = self.write_plan(order, "receipt", self.receipt_payload(order, quantity))
        return order


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True,
                   TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class PowderCoatingApiTests(CorrectionApiMixin, ScopedActorMixin, PowderCoatingFixture, APITestCase):
    def rows(self, direction="dispatch", **query):
        response = self.client.get(URL, {"task_number": self.task.task_number.lower(), "direction": direction, **query})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def reminders(self, **query):
        response = self.client.get(REMINDERS, query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def test_two_same_day_batches_and_two_receipts_match_their_vouchers(self):
        order = self.split_movements()
        original = self.client.get(BASE + order["id"] + "/").data["data"]
        before = PublicStockMovement.objects.count()
        for direction, records, number, date, quantity, expected in (
            ("dispatch", original["dispatch_records"], "order_number", "actual_dispatch_date", "quantity", ["300", "400"]),
            ("receipt", original["receipt_records"], "receipt_number", "receipt_date", "received_quantity", ["150", "200"]),
        ):
            with self.subTest(direction=direction):
                rows = self.rows(direction, task_number="")
                self.assertEqual([row["quantity"] for row in rows], expected)
                by_voucher = {record[number]: record for record in records}
                for row in rows:
                    record = by_voucher[row["voucher_number"]]
                    self.assertEqual((row["business_date"], row["quantity"]), (record[date], record["lines"][0][quantity]))
                    self.assertEqual((row["task_number"], row["order_id"], row["part_name"], row["factory_name"],
                                      row["specification"], row["spray_color"], row["unit"]),
                                     (self.task.task_number, order["id"], "前脚管", self.factory.name, "20×1.0", "黑色", "支"))
                self.assertEqual(self.rows(direction, page=2, page_size=1), [rows[1]])
        self.assertEqual(PublicStockMovement.objects.count(), before)

    def test_current_reminder_is_attached_to_both_voucher_lists(self):
        order = self.split_movements(keep_open=True)
        original = TubeOutsourcingOrder.objects.get(pk=order["id"])
        today = business_today()
        for days, status in ((-2, "OVERDUE"), (0, "DUE_TODAY"), (3, "NEAR_DUE"), (4, "UPCOMING")):
            with self.subTest(days=days):
                original.expected_return_date = today + timedelta(days=days)
                original.save(update_fields=["expected_return_date"])
                row, = self.reminders(owner=self.factory.name, page_size=1)
                reminder = row["reminder"]
                self.assertEqual((row["task_number"], row["part_name"], row["order_id"], reminder["status"],
                                  reminder["quantity"], reminder["unit"], reminder["due"]),
                                 (self.task.task_number, "前脚管", order["id"], status, "100", "支",
                                  original.expected_return_date.isoformat()))
                self.assertEqual(len(self.reminders(follow_up="FOLLOW_UP")), int(status != "UPCOMING"))
                for direction, quantities in (("dispatch", ["100", "100"]), ("receipt", ["40", "60"])):
                    rows = self.rows(direction, task_number="", owner=self.factory.name)
                    self.assertEqual([row["quantity"] for row in rows], quantities)
                    self.assertEqual(len({row["id"] for row in rows}), 2)
                    for movement in rows:
                        self.assertEqual(movement["expected_return_date"], original.expected_return_date.isoformat())
                        self.assertEqual(movement["reminder"], {"status": status, "label": reminder["label"]})
                    filtered = self.rows(direction, task_number="", follow_up="FOLLOW_UP")
                    self.assertEqual(len(filtered), 2 if status != "UPCOMING" else 0)
        self.assertEqual(self.reminders(owner="不存在的加工点"), [])
        self.assertEqual(self.reminders(task_number="其他任务"), [])
        self.assertEqual([row["quantity"] for row in self.rows(order_id=order["id"])], ["100", "100"])
        self.assertEqual([row["quantity"] for row in self.rows("receipt", order_id=order["id"])], ["40", "60"])
        self.assertEqual(self.rows(order_id=uuid.uuid4()), [])
        order = self.client.get(BASE + order["id"] + "/").data["data"]
        self.write_plan(order, "receipt", self.receipt_payload(order, "100"))
        self.assertEqual(self.reminders(), [])
        self.assertEqual(len(self.rows(task_number="", owner=self.factory.name)), 2)
        self.assertEqual(self.rows(task_number="", follow_up="FOLLOW_UP"), [])

    def test_corrections_and_voids_follow_the_current_original(self):
        order = self.split_movements()
        changed = self.correct(order, self.correction_payload(order, kind="RECEIPT", quantity=180))
        updated = next(row for row in changed["receipt_records"] if row["lines"][0]["received_quantity"] == "180")
        self.assertEqual([(row["business_date"], row["quantity"]) for row in self.rows("receipt")
                          if row["voucher_number"] == updated["receipt_number"]], [(updated["receipt_date"], "180")])
        self.assertEqual([row["quantity"] for row in self.rows("receipt")], ["150", "180"])
        changed = self.correct(changed, self.correction_payload(changed, kind="RECEIPT", operation="DELETE", record=updated))
        changed = self.correct(changed, self.correction_payload(changed, operation="DELETE", record=changed["dispatch_records"][0]))
        self.assertEqual([row["quantity"] for row in self.rows("receipt")], ["150"])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["voucher_number"], changed["dispatch_records"][0]["order_number"])

    def test_non_powder_and_out_of_scope_records_are_excluded(self):
        order = self.split_movements(keep_open=True)
        other = Craft.objects.create(name="其他工艺", craft_type="EXTERNAL", outsourcing_code="CUTTING")
        self.scoped_actor()
        self.assertEqual(self.client.get(URL, {"task_number": self.task.task_number}).status_code, 403)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.client.get(REMINDERS).status_code, 403)
        legacy = Permission.objects.get(content_type__app_label="outsourcing", codename="view_outsourcingorder")
        self.scope_user.user_permissions.add(legacy)
        self.client.force_authenticate(get_user_model().objects.get(pk=self.scope_user.pk))
        self.assertEqual(self.client.get(BASE + order["id"] + "/").status_code, 404)
        for direction in ("dispatch", "receipt"):
            self.assertEqual(self.rows(direction), [])
            self.assertEqual(self.rows(direction, task_number=""), [])
        self.assertEqual(self.reminders(), [])
        self.scope_user.user_permissions.remove(legacy)
        self.grant("outsourcing.view_outsourcingorder", "CRAFT", [other])
        self.assertEqual(self.rows(task_number=""), [])
        self.assertEqual(self.reminders(), [])
        self.grant("outsourcing.view_outsourcingorder", "CRAFT", [self.spray])
        self.assertEqual(len(self.rows(task_number="")), 2)
        self.assertEqual([row["order_id"] for row in self.reminders()], [order["id"]])
        self.assertEqual(self.rows(task_number=f"{self.task.task_number}-OTHER"), [])
        TubeOutsourcingOrder.objects.filter(product_line=self.product_line).update(craft=other)
        for direction in ("dispatch", "receipt"):
            self.assertEqual(self.rows(direction), [])

    def test_authentication_input_and_read_only_method(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.assertEqual(self.client.post(URL, {}).status_code, 405)
        self.assertEqual(APIClient().get(REMINDERS).status_code, 401)
        self.assertEqual(self.client.post(REMINDERS, {}).status_code, 405)
        self.assertEqual(self.client.get(REMINDERS, {"follow_up": "INVALID"}).status_code, 400)
        for query in ({"task_number": "x" * 51}, {"direction": "invalid"}, {"page_size": 101},
                      {"owner": "x" * 151}, {"follow_up": "INVALID"}):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(URL, query).status_code, 400)


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class PowderCoatingStandaloneTests(TubeReceiptFixture, APITestCase):
    def test_follow_up_prioritizes_status_due_date_and_business_date_before_pagination(self):
        today = business_today()
        by_dates = {}
        for due_offset, dispatch_offset in ((-5, -3), (-2, 0), (0, -1), (3, 0), (-5, -2)):
            action = {**self.action_payload(), "actual_dispatch_date": (today + timedelta(days=dispatch_offset)).isoformat()}
            order = self.act(self.saved_order(), payload=action).data["data"]
            TubeOutsourcingOrder.objects.filter(pk=order["id"]).update(expected_return_date=today + timedelta(days=due_offset))
            by_dates[due_offset, dispatch_offset] = order["id"]

        all_rows = self.client.get(URL).data["data"]
        self.assertEqual(len(all_rows), 5)
        self.assertEqual([row["business_date"] for row in all_rows],
                         sorted((row["business_date"] for row in all_rows), reverse=True))
        query = {"follow_up": "FOLLOW_UP", "page_size": 2}
        first = self.client.get(URL, query)
        second = self.client.get(URL, {**query, "page": 2})
        third = self.client.get(URL, {**query, "page": 3})
        self.assertEqual([first.status_code, second.status_code, third.status_code], [200, 200, 200])
        self.assertEqual(first.data["meta"]["total"], 5)
        rows = first.data["data"] + second.data["data"] + third.data["data"]
        self.assertEqual([row["order_id"] for row in rows],
                         [by_dates[key] for key in ((-5, -2), (-5, -3), (-2, 0), (0, -1), (3, 0))])

    def test_blank_task_factory_filters_history_and_status_before_pagination(self):
        today = business_today()
        action = {**self.action_payload(), "actual_dispatch_date": (today - timedelta(days=5)).isoformat()}
        overdue = self.act(self.saved_order(), payload=action).data["data"]
        closed = self.dispatched()
        self.receive_final(closed, self.receipt_payload(closed, quantity="20"))
        self.saved_order("RAW_PIPE", "20")
        due = today - timedelta(days=2)
        TubeOutsourcingOrder.objects.filter(pk__in=[overdue["id"], closed["id"]]).update(expected_return_date=due)

        query = {"owner": self.factory.name, "page_size": 1}
        all_dispatch = self.client.get(URL, query)
        active_dispatch = self.client.get(URL, {**query, "follow_up": "OVERDUE"})
        self.assertEqual((all_dispatch.status_code, active_dispatch.status_code), (200, 200))
        self.assertEqual(all_dispatch.data["meta"]["total"], 2)
        historical, = all_dispatch.data["data"]
        self.assertEqual((historical["order_id"], historical["expected_return_date"], historical["reminder"]),
                         (closed["id"], due.isoformat(), None))
        self.assertEqual(active_dispatch.data["meta"]["total"], 1)
        current, = active_dispatch.data["data"]
        self.assertEqual((current["order_id"], current["quantity"], current["reminder"]["status"]),
                         (overdue["id"], "20", "OVERDUE"))
        received = self.client.get(URL, {**query, "direction": "receipt"})
        movement, = received.data["data"]
        self.assertEqual((movement["order_id"], movement["quantity"], movement["reminder"]), (closed["id"], "20", None))
        self.assertEqual(self.client.get(URL, {**query, "direction": "receipt", "follow_up": "OVERDUE"}).data["data"], [])

    def test_standalone_positive_final_receipt_and_pending_order(self):
        self.receive_final(self.dispatched(), expected=201)
        second = self.dispatched()
        self.receive_final(second, self.receipt_payload(second, quantity="0"), expected=201)
        self.saved_order("RAW_PIPE", "20")
        query = {"task_number": self.task.task_number}
        dispatched = self.client.get(URL, query)
        received = self.client.get(URL, {**query, "direction": "receipt"})
        self.assertEqual((dispatched.status_code, received.status_code), (200, 200))
        self.assertEqual([row["quantity"] for row in dispatched.data["data"]], ["20", "20"])
        self.assertEqual([row["quantity"] for row in received.data["data"]], ["18"])

    def test_one_voucher_has_one_row_per_part_with_its_own_factory(self):
        order = self.multi_part_order()
        self.receive_final(order, self.receipt_payload(order, quantity="8"))
        rows = self.client.get(URL, {"task_number": self.task.task_number, "direction": "receipt"}).data["data"]
        self.assertEqual(len({row["voucher_number"] for row in rows}), 1)
        self.assertCountEqual([(row["part_name"], row["factory_name"], row["quantity"]) for row in rows],
                              [(row["part_name"], row["factory_name"], "8") for row in order["lines"]])
        filtered = self.client.get(URL, {"direction": "receipt", "owner": "第二喷塑", "page_size": 1})
        self.assertEqual((filtered.status_code, filtered.data["meta"]["total"]), (200, 1))
        self.assertEqual(filtered.data["data"][0]["part_name"], "后脚管")


@override_settings(TUBE_OUTSOURCING_ENABLED=False, PUBLIC_STOCK_FLOW_ENABLED=False, PUBLIC_STOCK_ISSUES_ENABLED=False)
class PowderCoatingMetalHistoryTests(MetalProcessingP4Fixture, APITestCase):
    def issue_line(self, quantity=210, confirm=True):
        self.f.hardware.raw_values["hardware_weight_mode"] = "MANUAL"
        self.f.hardware.save(update_fields=["raw_values"])
        return super().issue_line(quantity, confirm)

    def test_original_good_return_appears_once_and_unsprayed_return_is_excluded(self):
        unsprayed, _ = self.create_rework()
        handoff = unsprayed.original_handoff
        handoff_url = f"/api/v1/metal-processing-handoffs/{handoff.pk}/"
        context = self.client.get(handoff_url).data["data"]["good_return_context"]
        result = self.post(handoff_url + "good-returns/", {
            "request_id": str(uuid.uuid4()), "good_pieces": 3, "zone_id": str(self.f.semi_zone.pk),
            "received_by_employee_id": str(self.f.employee.pk), "return_date": str(handoff.handoff_date),
        }, etag=context["etag"]).data["data"]["good_returns"][0]
        query = {"task_number": self.line.issue.production_task.task_number}
        dispatched = self.client.get(URL, query).data["data"]
        received = self.client.get(URL, {**query, "direction": "receipt"}).data["data"]
        self.assertEqual([(row["quantity"], row["order_id"], row["source"]) for row in dispatched],
                         [("8", self.original_order, "METAL")])
        self.assertEqual([(row["voucher_number"], row["business_date"], row["order_id"], row["source"],
                           Decimal(row["quantity"])) for row in received],
                         [(result["return_number"], result["return_date"], self.original_order, "METAL", Decimal("3"))])
        self.assertEqual(self.client.get(REMINDERS, query).data["data"], [])

    def test_rework_only_counts_after_actual_handoff_and_receipt(self):
        order = self.create_order()
        url = f"/api/v1/metal-processing-external-orders/{order.pk}/"
        query = {"task_number": self.line.issue.production_task.task_number}
        self.assertEqual([row["source"] for row in self.client.get(URL, query).data["data"]], ["METAL"])
        detail = self.client.get(url).data["data"]
        date = str(timezone.localdate())
        handoff = self.post(url + "handoff/", {
            "request_id": str(uuid.uuid4()), "handoff_pieces": 5, "handoff_date": date,
        }, etag=detail["etag"]).data["data"]
        result = self.post(url + "returns/", {
            "request_id": str(uuid.uuid4()), "good_pieces": 3, "zone_id": str(self.f.semi_zone.pk),
            "received_by_employee_id": str(self.f.employee.pk), "return_date": date,
        }, etag=handoff["etag"]).data["data"]["good_returns"][0]
        dispatched = self.client.get(URL, query).data["data"]
        received = self.client.get(URL, {**query, "direction": "receipt"}).data["data"]
        self.assertCountEqual([(row["source"], row["quantity"]) for row in dispatched], [("METAL", "8"), ("REWORK", "5")])
        self.assertEqual([(row["voucher_number"], row["quantity"], row["source"]) for row in received],
                         [(result["return_number"], "3", "REWORK")])
        reminder, = [row["reminder"] for row in self.client.get(REMINDERS, query).data["data"]
                     if row["order_id"] == str(order.pk)]
        self.assertEqual((reminder["label"], reminder["quantity"], reminder["unit"]), ("未约定交期", "2", "支"))


@override_settings(TUBE_OUTSOURCING_ENABLED=False, PUBLIC_STOCK_FLOW_ENABLED=False, PUBLIC_STOCK_ISSUES_ENABLED=False)
class PowderCoatingWarehouseHistoryTests(MaterialFlowFixture, APITestCase):
    def test_raw_pipe_returns_reduce_the_factory_debt_without_rewriting_dispatch(self):
        order_id = self.create()
        _, source = self.dispatch(order_id)
        self.raw_return(order_id, source, 2)
        self.reconcile(order_id, source, "RAW_INPUT", 65)
        self.return_goods(order_id, source, 390)
        query = {"task_number": source.dispatch.order.schedule.production_task.task_number}
        self.assertEqual(self.client.get(REMINDERS, query).data["data"], [])
        sent, = self.client.get(URL, query).data["data"]
        received, = self.client.get(URL, {**query, "direction": "receipt"}).data["data"]
        self.assertEqual((Decimal(sent["quantity"]), Decimal(received["quantity"])), (Decimal(402), Decimal(390)))

        OutsourcingRawReturnLine.objects.filter(dispatch_line=source).update(piece_quantity_equivalent=None)
        self.assertEqual(self.client.get(REMINDERS, query).data["data"], [])
        source.snapshot.pop("pieces_per_bar")
        source.save(update_fields=["snapshot"])
        row, = self.client.get(REMINDERS, {**query, "follow_up": "REVIEW"}).data["data"]
        self.assertEqual((row["reminder"]["label"], row["reminder"]["quantity"]), ("数量待核", None))

    def test_original_warehouse_voucher_uses_piece_count_and_receipts_group_quality_splits(self):
        order_id = self.create()
        _, source = self.dispatch(order_id)
        self.reconcile(order_id, source, "RAW_INPUT", 67)
        self.return_goods(order_id, source, 380, 5)
        receipt = OutsourcingReturn.objects.get(order_id=order_id)
        query = {"task_number": source.dispatch.order.schedule.production_task.task_number}
        dispatched = self.client.get(URL, query).data["data"]
        received = self.client.get(URL, {**query, "direction": "receipt"}).data["data"]
        self.assertEqual([(row["voucher_number"], row["quantity"], row["unit"]) for row in dispatched],
                         [(source.dispatch.dispatch_number, "402", "支")])
        self.assertEqual([(row["voucher_number"], Decimal(row["quantity"]), row["unit"]) for row in received],
                         [(receipt.return_number, Decimal("385"), "支")])
        row, = self.client.get(REMINDERS, query).data["data"]
        self.assertEqual((Decimal(row["reminder"]["quantity"]), row["reminder"]["unit"]), (Decimal(17), "支"))
        for return_line in OutsourcingReturnLine.objects.filter(return_record=receipt):
            return_line.snapshot = {**return_line.snapshot, "unit": "米"}
            return_line.save(update_fields=["snapshot"])
        row, = self.client.get(REMINDERS, {**query, "follow_up": "REVIEW"}).data["data"]
        self.assertEqual((row["reminder"]["label"], row["reminder"]["quantity"]), ("数量待核", None))
