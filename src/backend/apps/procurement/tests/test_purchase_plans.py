from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.core.delivery_reminders import business_today
from apps.inventory.models import MaterialInbound, MaterialInboundLine, Warehouse, WarehouseZone

from ..models import PurchaseOrder, PurchaseContractTemplate, PurchaseReturn, PurchaseReturnLine, SupplierPurchaseSheet
from ..tracking_models import PurchaseTrackingPolicy
from . import test_purchase_order_api as order_fixtures
from . import test_tracking_queries as tracking_fixtures


@override_settings(PURCHASE_TRACKING_ENABLED=False, PURCHASE_TRACKING_POLICY_ENABLED=False)
class PurchasePlanTests(ScopedActorMixin, APITestCase):
    url = "/api/v1/purchase-plans/"
    make_task = order_fixtures.PurchaseOrderApiTests.make_task
    make_product_line = order_fixtures.PurchaseOrderApiTests.make_product_line
    make_bom = order_fixtures.PurchaseOrderApiTests.make_bom

    def setUp(self):
        order_fixtures.PurchaseOrderApiTests.setUp(self)
        self.task = self.make_task("PLAN")
        self.product_line = self.make_product_line(self.task, quantity=1000)
        self.bom, self.fabric = self.fabric_bom(self.product_line, "原布", "1000")
        warehouse = Warehouse.objects.create(warehouse_number="PLAN-QA", warehouse_name="采购计划验收仓", warehouse_type="MATERIAL")
        self.zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name="布面与管材验收区")
        self.sequence = 0

    def fabric_bom(self, product, name, quantity, **changes):
        bom, line = self.make_bom(product, section_type="FABRIC", part_name=name, material="牛津布",
                            specification="600D", unit="米", total_purchase_quantity=quantity, **changes)
        line.section.title = "面料类"
        line.section.save(update_fields=["title"])
        line.raw_values = {**line.raw_values, "fabric_width": "1.5", "fabric_color_name": "本色", "fabric_coating": "PU"}
        line.save(update_fields=["raw_values"])
        return bom, line

    def order_line(self, source, quantity, *, status="PURCHASING", supplier=None, unit="米", **overrides):
        self.sequence += 1
        bom = source.section.bom
        task = bom.production_task
        order = PurchaseOrder.objects.create(
            order_number=f"CGDD261120{self.sequence:03d}", production_task=task,
            production_task_number_snapshot=task.task_number, sales_order_number_snapshot=task.order_number,
            customer_name_snapshot=self.customer.account_name, source_revision="plan-verification",
            status=status, created_by_employee=self.employee, currency=self.cny, currency_code_snapshot="CNY",
        )
        supplier = supplier or self.supplier
        values = {
            "bom": bom, "bom_line": source, "line_number": 1, "source_bom_line_id_snapshot": source.pk,
            "product_line_id_snapshot": bom.product_line_id, "bom_number_snapshot": bom.bom_number,
            "product_name_snapshot": bom.product_name_snapshot, "section_type_snapshot": source.section.section_type,
            "section_title_snapshot": source.section.title, "part_name_snapshot": source.part_name,
            "material_snapshot": source.material, "specification_snapshot": source.specification,
            "material_selection_snapshot": source.material_selection_snapshot,
            "required_quantity": Decimal(source.total_purchase_quantity or quantity), "source_unit_text": unit,
            "quantity_parse_status": "READY", "actual_purchase_quantity": quantity, "supplier": supplier,
            "supplier_name_snapshot": supplier.supplier_name, "delivery_date": date(2026, 11, 25),
            "unit_price": 2, "amount": Decimal(quantity) * 2,
        }
        return order.lines.create(**{**values, **overrides})

    def arrival(self, order_line, quantity, day, *, status="CONFIRMED", returns=0, **measurements):
        self.sequence += 1
        inbound = MaterialInbound.objects.create(
            inbound_number=f"CLRK261120{self.sequence:03d}", inbound_date=date(2026, 11, day),
            purchase_order=order_line.purchase_order, status=status, received_by_employee=self.employee,
            quality_confirmed_at=timezone.now() if returns else None,
        )
        return MaterialInboundLine.objects.create(
            inbound=inbound, purchase_order_line=order_line, zone=self.zone,
            raw_material_information=self.inventory_material,
            source_unit_text_snapshot=order_line.source_unit_text, purchased_quantity_snapshot=order_line.actual_purchase_quantity,
            received_quantity=quantity, accepted_quantity=Decimal(quantity) - Decimal(returns),
            return_quantity=returns, **measurements,
        )

    def sheet(self, line, series, version, day, status, template, *, current):
        order = line.purchase_order
        return SupplierPurchaseSheet.objects.create(
            series_id=series, version_number=version, status=status, is_current=current, purchase_order=order,
            template_version=template, supplier=line.supplier, supplier_number_snapshot=line.supplier.supplier_number,
            supplier_name_snapshot=line.supplier_name_snapshot, sheet_number=order.order_number,
            content_snapshot={"purchase_date": f"2026-11-{day:02d}", "lines": [{"source_purchase_order_line_id": str(line.pk)}]},
            published_at=timezone.now() if status == "PUBLISHED" else None,
        )

    def listing(self, category="FABRIC", **query):
        response = self.client.get(self.url, {"category": category, "task_number": self.task.task_number, **query})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def source_detail(self, line, category="FABRIC"):
        response = self.client.get(f"{self.url}{line.pk}/", {"task_id": line.section.bom.production_task_id, "category": category})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def test_confirmed_bom_without_a_valid_order_and_only_original_fabric(self):
        section = self.fabric.section
        section.lines.create(line_number=2, part_name="加工好的布面",
                             material_selection_snapshot={"category_key": "FABRIC", "processing_state": "PROCESSED"})
        section.lines.create(line_number=3, part_name="厂家外供", raw_values={"purchase_required": False})
        section.lines.create(line_number=4, part_name="历史缺量", unit="米")
        self.order_line(self.fabric, "500", status="DRAFT")
        page = self.listing(page_size=1)
        self.assertEqual(page["total"], 2)
        row, = self.listing(q="600d")["data"]
        self.assertEqual(row["task_number"], self.task.task_number)
        self.assertEqual((row["task_quantity"], row["name"], row["coating"], row["fabric_width"], row["fabric_color"]),
                         (1000, "原布", "PU", "1.5", "本色"))
        self.assertEqual((Decimal(row["required"]["quantity"]), row["required"]["unit"]), (Decimal(1000), "米"))
        self.assertEqual((row["ordered"], row["received"], row["progress"]),
                         ([{"quantity": "0", "unit": "米"}], [{"quantity": "0", "unit": "米"}], "未下单"))
        self.assertIsNone(self.listing(q="历史缺量")["data"][0]["required"])
        self.assertEqual(self.source_detail(self.fabric)["batches"], [])

    def test_completed_history_retains_all_batches_receipts_and_returns(self):
        first = self.order_line(self.fabric, "600", status="COMPLETED")
        second = self.order_line(self.fabric, "400", status="COMPLETED", supplier=self.disabled_supplier)
        template = PurchaseContractTemplate.objects.create(template_code="PLAN-QA", template_name="计划表验证").versions.create(version_number=1)
        series = uuid4()
        self.sheet(first, series, 1, 20, "PUBLISHED", template, current=False)
        self.sheet(first, series, 2, 21, "PUBLISHED", template, current=False)
        self.sheet(first, series, 3, 26, "DRAFT", template, current=True)
        self.sheet(second, uuid4(), 1, 24, "DRAFT", template, current=True)
        self.arrival(first, 300, 21)
        returned = self.arrival(first, 300, 23, returns=5)
        ret = PurchaseReturn.objects.create(return_number="TH261123001", purchase_order=first.purchase_order,
            inbound=returned.inbound, supplier=first.supplier, supplier_name_snapshot=first.supplier_name_snapshot,
            supplier_number_snapshot=first.supplier.supplier_number, generated_by_employee=self.employee)
        PurchaseReturnLine.objects.create(return_order=ret, inbound_line=returned, quantity=5)
        self.arrival(first, 20, 25)
        self.arrival(second, 400, 26, status="PENDING_QUALITY")
        self.task.status = "COMPLETED"
        self.task.save(update_fields=["status"])

        row, = self.listing()["data"]
        self.assertEqual((Decimal(row["required"]["quantity"]), Decimal(row["ordered"][0]["quantity"]),
                          Decimal(row["received"][0]["quantity"]), row["progress"]),
                         (Decimal(1000), Decimal(1000), Decimal(1020), "已购到齐"))
        a, b = self.source_detail(self.fabric)["batches"]
        self.assertEqual((a["ordered_on"], a["expected_on"], a["complete_on"]), ("2026-11-21", "2026-11-25", "2026-11-23"))
        self.assertEqual([(event["date"], Decimal(event["amount"]["quantity"]), event["days"], event["status"])
                          for event in a["arrivals"]],
                         [("2026-11-21", Decimal(300), 0, ""), ("2026-11-23", Decimal(300), 2, "本次到齐"),
                          ("2026-11-25", Decimal(20), 4, "后续到货")])
        self.assertEqual((a["returns"][0]["number"], Decimal(a["returns"][0]["amount"]["quantity"])),
                         (ret.return_number, Decimal(5)))
        self.assertEqual((b["supplier"], b["ordered_on"], b["arrivals"][0]["days"]),
                         (second.supplier_name_snapshot, None, None))
        self.assertEqual(a["unit_price"]["unit"], "米")

    def test_shared_batch_keeps_frozen_product_demands_without_splitting_receipts(self):
        other_product = self.make_product_line(self.task, line_number=2, quantity=25)
        other_bom, other_fabric = self.fabric_bom(other_product, "另一款用布", "60")
        other_bom.product_name_snapshot = "采购计划另一款"
        other_bom.save(update_fields=["product_name_snapshot"])
        contributions = [
            {"bom_id": str(self.bom.pk), "bom_line_id": str(self.fabric.pk),
             "product_line_id": str(self.product_line.pk), "required_quantity": "1000", "source_unit_text": "米"},
            {"bom_id": str(other_bom.pk), "bom_line_id": str(other_fabric.pk),
             "product_line_id": str(other_product.pk), "required_quantity": "60", "source_unit_text": "米"},
        ]
        batch = self.order_line(self.fabric, "1060", calculation_snapshot={"group_source_contributions": contributions})
        self.arrival(batch, 900, 22)
        rows = self.listing()["data"]
        self.assertEqual({Decimal(row["required"]["quantity"]) for row in rows}, {Decimal(1000), Decimal(60)})
        self.assertTrue(all(row["progress"] == "共采待分配" and not row["ordered"] and not row["received"] for row in rows))
        for line in (self.fabric, other_fabric):
            detail, = self.source_detail(line)["batches"]
            self.assertTrue(detail["shared"])
            self.assertEqual(detail["id"], str(batch.pk))
            self.assertEqual(set(detail["products"]), {self.bom.product_name_snapshot, other_bom.product_name_snapshot})
            self.assertEqual(Decimal(detail["arrivals"][0]["amount"]["quantity"]), Decimal(900))

    def test_copied_component_keeps_purchases_and_identifies_quantity_or_material_changes(self):
        selection = {"category_key": "FABRIC", "processing_state": "RAW", "attributes": {"finish": "PU"}}
        self.fabric.material_selection_snapshot = selection
        self.fabric.raw_values.pop("fabric_coating")
        self.fabric.save(update_fields=["material_selection_snapshot", "raw_values"])
        old_order = self.order_line(self.fabric, "1000", status="COMPLETED")
        self.arrival(old_order, 1000, 25)
        new_bom, new_line = self.fabric_bom(self.product_line, "原布", "1000", version=2)
        new_line.component_identity = self.fabric.component_identity
        new_line.material_selection_snapshot = selection
        new_line.raw_values.pop("fabric_coating")
        new_line.save(update_fields=["component_identity", "material_selection_snapshot", "raw_values"])

        row, = self.listing()["data"]
        self.assertEqual((row["id"], row["progress"], row["coating"], row["note"]),
                         (str(new_line.pk), "已购到齐", "PU", ""))
        self.assertEqual(Decimal(row["ordered"][0]["quantity"]), Decimal(1000))
        detail = self.source_detail(new_line)
        self.assertEqual(detail["batches"][0]["bom_numbers"], [self.bom.bom_number])

        new_line.total_purchase_quantity = "1200"
        new_line.save(update_fields=["total_purchase_quantity"])
        row, = self.listing()["data"]
        self.assertEqual(row["note"], "BOM 用量变更，待核对")
        detail = self.source_detail(new_line)
        self.assertEqual([(source["bom_number"], Decimal(source["required"]["quantity"])) for source in detail["source_versions"]],
                         [(self.bom.bom_number, Decimal(1000)), (new_bom.bom_number, Decimal(1200))])

        new_line.specification = "900D"
        new_line.save(update_fields=["specification"])
        rows = {row["specification"]: row for row in self.listing()["data"]}
        self.assertEqual(set(rows), {"600D", "900D"})
        self.assertEqual(rows["600D"]["coating"], "PU")
        self.assertEqual(Decimal(rows["600D"]["ordered"][0]["quantity"]), Decimal(1000))
        self.assertIsNone(rows["600D"]["reminder"])
        self.assertEqual(rows["900D"]["ordered"], [{"quantity": "0", "unit": "米"}])
        self.assertEqual(rows["900D"]["note"], "BOM 物料变更，待核对")
        self.assertEqual(rows["900D"]["reminder"]["action"], "待下单")

    def test_new_pipe_uses_roots_and_old_weighed_pipe_uses_contract_kilograms(self):
        bom, first = self.make_bom(self.product_line, version=2, section_type="PROFILE", part_name="新管", hardness="T5",
                            cutting_length_mm=500, pieces_per_product=1, pieces_per_bar=12, raw_bar_length_m=6,
                            suggested_bar_count=5, suggested_purchase_meters=30, total_purchase_quantity="12")
        section = bom.sections.get()
        second = section.lines.create(line_number=2, part_name="旧管", unit="米", total_purchase_quantity="12")
        sizes = {"actual_bar_count": 5, "actual_purchase_meters": 30, "actual_purchase_weight_kg": 12,
                 "raw_bar_length_m": 6, "raw_bar_weight_kg": Decimal("2.4"), "suggested_bar_count": 5,
                 "suggested_purchase_meters": 30, "suggested_purchase_weight_kg": 12}
        root_order = self.order_line(first, "12", unit="KG", delivery_date=business_today() + timedelta(days=5), **sizes)
        weight_order = self.order_line(second, "12", unit="KG", **sizes)
        self.arrival(root_order, 30, 21, returns=12, received_bar_count=5, accepted_bar_count=3, return_bar_count=2,
                     measurement_kind="PIPE", raw_bar_length_m=6, calculation_snapshot={"receipt_quantity_mode": "ROOTS"})
        self.arrival(weight_order, 24, 22, received_bar_count=4, accepted_bar_count=4, return_bar_count=0,
                     measurement_kind="PIPE", raw_bar_length_m=6, received_weight_kg=12, accepted_weight_kg=12, return_weight_kg=0)
        rows = {row["name"]: row for row in self.listing("TUBE")["data"]}
        self.assertEqual((rows["新管"]["received"], rows["新管"]["progress"], rows["新管"]["hardness"],
                          rows["新管"]["cutting_length"], Decimal(rows["新管"]["raw_length"])),
                         ([{"quantity": "5", "unit": "根"}], "待补收", "T5", "500", Decimal(6)))
        root_batch, = self.source_detail(first, "TUBE")["batches"]
        self.assertEqual((root_batch["complete_on"], root_batch["remaining"], root_batch["returns"][0]["amount"]),
                         ("2026-11-21", {"quantity": "2", "unit": "根"}, {"quantity": "2", "unit": "根"}))
        self.assertEqual((root_batch["reminder"]["status"], root_batch["reminder"]["quantity"], root_batch["reminder"]["unit"]),
                         ("NEAR_DUE", "2", "根"))
        self.arrival(root_order, 12, 23, status="PENDING_QUALITY", received_bar_count=2, accepted_bar_count=2, return_bar_count=0,
                     measurement_kind="PIPE", raw_bar_length_m=6, calculation_snapshot={"receipt_quantity_mode": "ROOTS"})
        replenished, = self.source_detail(first, "TUBE")["batches"]
        self.assertEqual((replenished["complete_on"], replenished["progress"], replenished["remaining"]),
                         ("2026-11-21", "已到齐", {"quantity": "0", "unit": "根"}))
        self.assertIsNone(replenished["reminder"])
        weighed = rows["旧管"]
        self.assertEqual((Decimal(weighed["received"][0]["quantity"]), weighed["received"][0]["unit"], weighed["progress"]),
                         (Decimal(12), "KG", "已购到齐"))

    @override_settings(PURCHASE_TRACKING_POLICY_ENABLED=True)
    def test_partial_purchase_keeps_both_the_order_deadline_and_the_unbought_quantity(self):
        today = business_today()
        policy = PurchaseTrackingPolicy.objects.get(key="default")
        policy.category_lead_days = {**policy.category_lead_days, "FABRIC": 3}
        policy.save(update_fields=["category_lead_days"])
        scheduled = tracking_fixtures.TrackingQueryTests.schedule(self)
        scheduled.material_inbound_date = today + timedelta(days=3)
        scheduled.save(update_fields=["material_inbound_date"])

        early = self.order_line(self.fabric, "200", delivery_date=today - timedelta(days=2))
        self.arrival(early, 200, 21)
        current = self.order_line(self.fabric, "400", supplier=self.disabled_supplier, delivery_date=today + timedelta(days=3))
        self.arrival(current, 200, 22)
        no_date = self.fabric.section.lines.create(line_number=2, part_name="缺交期", unit="米", total_purchase_quantity="50")
        self.order_line(no_date, "50", delivery_date=None)

        main, = self.listing(follow_up="DUE_TODAY", page_size=1)["data"]
        self.assertEqual((main["reminder"]["status"], main["reminder"]["action"], main["reminder"]["due"],
                          Decimal(main["reminder"]["quantity"]), main["reminder"]["owner"]),
                         ("DUE_TODAY", "待下单", today.isoformat(), Decimal(400), "采购"))
        self.assertEqual(self.listing(follow_up="OVERDUE")["total"], 0)
        supplier, = self.listing(follow_up="FOLLOW_UP", owner=self.disabled_supplier.supplier_name, page_size=1)["data"]
        self.assertEqual((supplier["reminder"]["status"], supplier["reminder"]["action"], Decimal(supplier["reminder"]["quantity"])),
                         ("NEAR_DUE", "催到货", Decimal(200)))
        missing, = self.listing(follow_up="REVIEW")["data"]
        self.assertEqual(missing["reminder"]["label"], "未约定交期")
        batches = {batch["id"]: batch["reminder"] for batch in self.source_detail(self.fabric)["batches"]}
        self.assertIsNone(batches[str(early.pk)])
        self.assertEqual(batches[str(current.pk)]["reference"], current.purchase_order.order_number)
        current.delivery_date = today + timedelta(days=4)
        current.save(update_fields=["delivery_date"])
        self.assertEqual(self.listing(follow_up="NEAR_DUE")["total"], 0)

        policy.bom_timeout_days = 2
        policy.save(update_fields=["bom_timeout_days"])
        self.bom.confirmed_at = timezone.now() - timedelta(days=4)
        self.bom.save(update_fields=["confirmed_at"])
        scheduled.material_inbound_date = today + timedelta(days=4)
        scheduled.save(update_fields=["material_inbound_date"])
        primary, = self.listing(q="原布")["data"]
        self.assertEqual(primary["reminder"]["status"], "OVERDUE")
        overdue, = self.listing(q="原布", owner="采购", follow_up="OVERDUE")["data"]
        near, = self.listing(q="原布", owner="采购", follow_up="NEAR_DUE")["data"]
        self.assertEqual(overdue["reminder"]["reason"], "BOM 确认后采购期限")
        self.assertEqual((near["reminder"]["due"], near["reminder"]["reason"]),
                         ((today + timedelta(days=1)).isoformat(), "最晚采购日"))
        self.assertCountEqual([item["status"] for item in self.source_detail(self.fabric)["purchase_reminders"]],
                              ["OVERDUE", "NEAR_DUE"])

    def test_bom_revision_in_demand_is_reviewed_without_suppressing_an_actual_purchase_batch(self):
        order = self.order_line(self.fabric, "1000", delivery_date=business_today() - timedelta(days=1))
        self.arrival(order, 800, 25)
        _, current = self.fabric_bom(self.product_line, "原布", "1200", version=2)
        current.component_identity = self.fabric.component_identity
        current.save(update_fields=["component_identity"])

        review_row, = self.listing(follow_up="REVIEW", owner="采购")["data"]
        self.assertEqual((review_row["reminder"]["status"], review_row["reminder"]["label"], review_row["reminder"]["quantity"]),
                         ("REVIEW", "需求待核", None))
        row, = self.listing(follow_up="OVERDUE", owner=self.supplier.supplier_name)["data"]
        self.assertEqual((row["reminder"]["action"], Decimal(row["reminder"]["quantity"])), ("催到货", Decimal(200)))

    @override_settings(PURCHASE_TRACKING_POLICY_ENABLED=True)
    def test_unscheduled_material_uses_existing_bom_timeout(self):
        PurchaseTrackingPolicy.objects.filter(key="default").update(bom_timeout_days=2)
        self.bom.confirmed_at = timezone.now() - timedelta(days=4)
        self.bom.save(update_fields=["confirmed_at"])
        row, = self.listing(follow_up="OVERDUE")["data"]
        self.assertEqual((row["reminder"]["label"], row["reminder"]["reason"], Decimal(row["reminder"]["quantity"])),
                         ("逾期 2 天", "BOM 确认后采购期限", Decimal(1000)))

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_list_and_expansion_both_use_the_existing_production_purchase_scope(self):
        private = self.make_task("PLAN-HIDDEN")
        hidden_bom, hidden = self.fabric_bom(self.make_product_line(private), "保密规格", "10")
        self.order_line(hidden, "10")
        self.scoped_actor()
        self.grant("inventory.receive_material")
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.grant("procurement.view_purchaseorder", "FOLLOWED")
        self.task.followers.add(self.scope_employee)
        visible = self.listing(task_number="")["data"]
        self.assertEqual([row["id"] for row in visible], [str(self.fabric.pk)])
        self.assertEqual(self.listing(task_number=private.task_number)["total"], 0)
        self.assertEqual(self.client.get(f"{self.url}{hidden.pk}/",
            {"task_id": hidden_bom.production_task_id, "category": "FABRIC"}).status_code, 404)
        self.assertEqual(self.client.get(f"{self.url}{hidden.pk}/",
            {"task_id": self.task.pk, "category": "FABRIC"}).status_code, 404)
        self.assertEqual(self.client.get(f"{self.url}{self.fabric.pk}/", {"category": "FABRIC"}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"category": "OUTSOURCING"}).status_code, 400)
        self.assertEqual(self.source_detail(self.fabric)["task_id"], str(self.task.pk))
        self.assertEqual(self.client.post(self.url, {}, format="json").status_code, 405)
