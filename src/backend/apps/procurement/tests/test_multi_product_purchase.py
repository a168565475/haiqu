from copy import deepcopy
from decimal import Decimal

from django.contrib.auth.models import Permission
from rest_framework.test import APITestCase

from apps.boms.models import BomSectionType
from apps.inventory.models import MaterialInboundLine, PublicStockBalance, Warehouse, WarehouseZone
from apps.material_catalog.models import MaterialCatalog
from apps.material_catalog.snapshots import build_material_snapshot
from apps.material_issues.catalog_requirements import catalog_requirement_rows
from apps.reference_data.models import ProductionUnit

from ..models import PurchaseGroup, PurchaseOrder, SupplierPurchaseSheet
from ..tracking_selectors import arrival_rows, coverage_rows
from . import test_purchase_groups as group_fixtures
from . import test_purchase_order_api as order_fixtures
from .group_test_fixtures import ensure_group_test_reference_data


class MultiProductPurchaseFixture:
    make_task = order_fixtures.PurchaseOrderApiTests.make_task
    make_product_line = order_fixtures.PurchaseOrderApiTests.make_product_line
    make_bom = order_fixtures.PurchaseOrderApiTests.make_bom
    get_source = order_fixtures.PurchaseOrderApiTests.get_source
    detail = group_fixtures.PurchaseGroupApiTests.detail
    batch = group_fixtures.PurchaseGroupApiTests.batch
    batch_payload = group_fixtures.PurchaseGroupApiTests.batch_payload
    receive = group_fixtures.PurchaseGroupApiTests.receive

    def setUp(self):
        ensure_group_test_reference_data()
        order_fixtures.PurchaseOrderApiTests.setUp(self)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=["inventory", "production_tasks"]))
        self.task = self.make_task("TWO-COLORS")
        self.red = self.make_product_line(self.task, quantity=400)
        self.blue = self.make_product_line(self.task, line_number=2, quantity=100)
        self.hardware = MaterialCatalog.objects.create(category_key="HARDWARE", template_key="HARDWARE", name="十字螺钉")
        unit = self.inventory_material.unit
        self.hardware.allowed_units.create(scope="BASE", unit=unit)
        self.hardware.attribute_values.create(scope="BASE", field_key="specification", value="5×33")
        selected = build_material_snapshot(catalog=self.hardware, scope="BASE", processing_state="RAW",
            attributes={"specification": "5×33"}, unit_id=unit.pk, required_fields=["specification"])
        for product, color in ((self.red, "红"), (self.blue, "蓝")):
            product.color_name_snapshot = color
            product.save(update_fields=["color_name_snapshot"])
        self.red_bom, self.red_screw = self.make_bom(self.red, section_type=BomSectionType.ACCESSORY,
            part_name=self.hardware.name, budget_quantity="1600", material_catalog=self.hardware, material_selection_snapshot=selected)
        self.blue_bom, self.blue_screw = self.make_bom(self.blue, section_type=BomSectionType.ACCESSORY,
            part_name=self.hardware.name, budget_quantity="400", material_catalog=self.hardware, material_selection_snapshot=selected)
        warehouse = Warehouse.objects.create(warehouse_number="MULTI-WH", warehouse_name="合并采购材料仓", warehouse_type="MATERIAL")
        self.zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name="收货区")

    def payload(self):
        sources = []
        for bom in (self.red_bom, self.blue_bom):
            response = self.get_source(self.task, bom)
            self.assertEqual(response.status_code, 200, response.data)
            sources.append({"bom_id": str(bom.pk), "source_revision": response.data["data"]["source_revision"]})
        return {"production_task_id": str(self.task.pk), "sources": sources}

    def create_group(self):
        result = self.client.post("/api/v1/purchase-groups/", self.payload(), format="json")
        self.assertEqual(result.status_code, 201, result.data)
        data = result.data["data"]
        self.group_id = data["id"]
        self.line_id = next(row["id"] for row in data["progress"]["lines"]
            if str(row["source_snapshot"]["material_catalog_id"]) == str(self.hardware.pk))
        return data

    def add_fabrics(self, colors):
        catalog = MaterialCatalog.objects.create(category_key="FABRIC", template_key="FABRIC", name="600D 面料")
        unit, _ = ProductionUnit.objects.get_or_create(unit_name="米", catalog_owner=None, defaults={"unit_code": "MULTI-M"})
        catalog.allowed_units.create(scope="BASE", unit=unit)
        attributes = {"material": "涤纶", "fabric_spec": "600D", "width": "150cm"}
        for key, value in attributes.items():
            catalog.attribute_values.create(scope="BASE", field_key=key, value=value)
        for bom, (name, code) in zip((self.red_bom, self.blue_bom), colors, strict=True):
            color = catalog.attribute_values.create(scope="BASE", field_key="color", value=name, color_card="C", color_code=code)
            selected = build_material_snapshot(catalog=catalog, scope="BASE", processing_state="RAW",
                attributes={**attributes, "color": name}, unit_id=unit.pk, required_fields=[*attributes, "color"], color_option=color)
            section = bom.sections.create(line_number=2, section_type=BomSectionType.FABRIC, title="面料类")
            section.lines.create(line_number=1, material_catalog=catalog, material_selection_snapshot=selected,
                part_name=catalog.name, unit="米", total_purchase_quantity=str(bom.order_quantity))
        return catalog


class MultiProductPurchaseTests(MultiProductPurchaseFixture, APITestCase):
    def test_select_two_products_combines_screws_but_preserves_material_colors_and_contributions(self):
        fabric = self.add_fabrics([("红", "R1"), ("蓝", "B1")])
        data = self.create_group()
        self.assertCountEqual([(row["product_line_id"], row["color_name"]) for row in data["products"]],
            [(str(self.red.pk), "红"), (str(self.blue.pk), "蓝")])
        lines = data["progress"]["lines"]
        self.assertEqual(len(lines), 3)
        screw = next(row for row in lines if row["id"] == self.line_id)
        self.assertEqual(Decimal(screw["required_quantity"]), 2000)
        self.assertCountEqual([(row["bom_id"], row["bom_line_id"], row["product_line_id"], Decimal(row["required_quantity"]))
            for row in screw["source_snapshot"]["source_contributions"]], [
            (str(self.red_bom.pk), str(self.red_screw.pk), str(self.red.pk), Decimal(1600)),
            (str(self.blue_bom.pk), str(self.blue_screw.pk), str(self.blue.pk), Decimal(400)),
        ])
        fabrics = [row for row in lines if str(row["source_snapshot"]["material_catalog_id"]) == str(fabric.pk)]
        self.assertCountEqual([(row["source_snapshot"]["material_selection_snapshot"]["color_code"], Decimal(row["required_quantity"]))
            for row in fabrics], [("R1", Decimal(400)), ("B1", Decimal(100))])

    def test_same_fabric_color_name_with_two_color_codes_stays_separate(self):
        fabric = self.add_fabrics([("红", "R1"), ("红", "R2")])
        lines = self.create_group()["progress"]["lines"]
        codes = [row["source_snapshot"]["material_selection_snapshot"]["color_code"] for row in lines
            if str(row["source_snapshot"]["material_catalog_id"]) == str(fabric.pk)]
        self.assertCountEqual(codes, ["R1", "R2"])

    def test_tracking_counts_merged_material_once_and_detects_second_products_bom_changes(self):
        self.add_fabrics([("红", "R1"), ("蓝", "B1")])
        self.create_group()
        self.batch("1500")
        rows = coverage_rows(task_ids=[self.task.pk])
        self.assertEqual(len(rows), 3)
        screw, = [row for row in rows if row["material_name"] == self.hardware.name]
        self.assertTrue(screw["source_reliable"], screw["verification_notes"])
        self.assertEqual((Decimal(screw["required_quantity"]), Decimal(screw["purchased_quantity"]),
            Decimal(screw["remaining_quantity"])), (2000, 1500, 500))
        self.assertIn("红", screw["product_name"])
        self.assertIn("蓝", screw["product_name"])
        arrival, = arrival_rows(task_ids=[self.task.pk])
        self.assertEqual(arrival["product_name"], screw["product_name"])
        self.blue_screw.budget_quantity = "401"
        self.blue_screw.save(update_fields=["budget_quantity"])
        rows = coverage_rows(task_ids=[self.task.pk])
        changed, = [row for row in rows if row["material_name"] == self.hardware.name]
        self.assertIn("DEMAND_CHANGED", [risk["code"] for risk in changed["risks"]])
        self.assertIsNone(changed["remaining_quantity"])

    def test_partial_batch_sheet_receipt_and_product_issue_balances(self):
        self.create_group()
        first = self.batch("1500", confirm=False)
        self.assertEqual(len(first["lines"]), 1)
        self.assertEqual(Decimal(first["total_amount"]), 3000)
        progress = self.detail().data["data"]["progress"]["lines"][0]
        self.assertEqual(Decimal(progress["purchased_quantity"]), 0)
        self.assertEqual(Decimal(progress["remaining_purchase_quantity"]), 500)
        confirmed = self.client.post(f"/api/v1/purchase-orders/{first['id']}/confirm/", {}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.receive(confirmed.data["data"], "1500")
        sheet_lines = SupplierPurchaseSheet.objects.get().content_snapshot["lines"]
        self.assertEqual(len(sheet_lines), 1)
        self.assertEqual(Decimal(sheet_lines[0]["quantity"]), 1500)
        self.assertEqual(MaterialInboundLine.objects.get().accepted_quantity, 1500)
        self.assertEqual(PublicStockBalance.objects.get().quantity, 1500)
        progress = self.detail().data["data"]["progress"]["lines"][0]
        self.assertEqual(tuple(Decimal(progress[field]) for field in ("purchased_quantity", "accepted_quantity",
            "remaining_purchase_quantity")), (1500, 1500, 500))
        requirements = []
        for product, quantity in ((self.red, 1600), (self.blue, 400)):
            rows, blockers = catalog_requirement_rows(self.task.pk, product.pk)
            self.assertEqual(blockers, [])
            self.assertEqual(len(rows), 1)
            self.assertEqual((Decimal(rows[0]["required_quantity"]), Decimal(rows[0]["available_stock"])), (quantity, 1500))
            requirements.append(rows[0]["requirement_id"])
        self.assertNotEqual(*requirements)
        self.batch("500", confirm=False)
        self.assertEqual(Decimal(self.detail().data["data"]["progress"]["lines"][0]["remaining_purchase_quantity"]), 0)

    def test_existing_single_product_demands_carry_their_batches_into_combined_remaining(self):
        payload = self.payload()
        previous = []
        for source in payload["sources"]:
            created = self.client.post("/api/v1/purchase-groups/",
                {"production_task_id": payload["production_task_id"], **source}, format="json")
            self.assertEqual(created.status_code, 201, created.data)
            group = created.data["data"]
            previous.append((group["id"], group["progress"]["lines"][0]["id"]))
        self.group_id, self.line_id = previous[0]
        draft = self.batch("1000", confirm=False)
        # 兼容更新前仅在总单表头记录来源的采购需求。
        PurchaseGroup.objects.get(pk=self.group_id).bom_sources.all().delete()
        source = self.get_source(self.task)
        self.assertEqual(source.status_code, 200, source.data)
        options = source.data["data"]["bom_options"]
        self.assertTrue(all(option["can_combine"] for option in options), options)
        payload["sources"] = [{"bom_id": option["bom_id"], "source_revision": option["combine_source_revision"]} for option in options]
        combined = self.client.post("/api/v1/purchase-groups/", payload, format="json")
        self.assertEqual(combined.status_code, 201, combined.data)
        group = combined.data["data"]
        row, = group["progress"]["lines"]
        self.assertEqual(tuple(Decimal(row[key]) for key in ("required_quantity", "planned_purchase_quantity", "remaining_purchase_quantity")),
            (2000, 1000, 1000))
        self.assertEqual(str(PurchaseOrder.objects.get(pk=draft["id"]).purchase_group_id), previous[0][0])
        blocked = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", self.batch_payload("1"),
            format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(blocked.status_code, 409, blocked.data)
        confirmed = self.client.post(f"/api/v1/purchase-orders/{draft['id']}/confirm/", {}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.group_id, self.line_id = group["id"], row["id"]
        self.batch("500")
        self.assertEqual(Decimal(self.detail().data["data"]["progress"]["lines"][0]["remaining_purchase_quantity"]), 500)
        tracked, = coverage_rows(task_ids=[self.task.pk])
        self.assertTrue(tracked["source_reliable"], tracked["verification_notes"])
        self.assertEqual((Decimal(tracked["required_quantity"]), Decimal(tracked["purchased_quantity"]),
            Decimal(tracked["remaining_quantity"])), (2000, 1500, 500))
        before_delete = self.detail()
        old_url = f"/api/v1/purchase-orders/{draft['id']}/"
        removed = self.client.delete(old_url, HTTP_IF_MATCH=self.client.get(old_url)["ETag"])
        self.assertEqual(removed.status_code, 204, removed.data)
        refreshed = self.detail()
        self.assertNotEqual(refreshed["ETag"], before_delete["ETag"])
        self.assertEqual(Decimal(refreshed.data["data"]["progress"]["lines"][0]["remaining_purchase_quantity"]), 1500)

    def test_deleting_a_draft_restores_only_that_batch_to_remaining(self):
        self.create_group()
        self.batch("100")
        draft = self.batch("600", confirm=False)
        item = f"/api/v1/purchase-orders/{draft['id']}/"
        self.assertEqual(Decimal(self.detail().data["data"]["progress"]["lines"][0]["remaining_purchase_quantity"]), 1300)
        removed = self.client.delete(item, HTTP_IF_MATCH=self.client.get(item)["ETag"])
        self.assertEqual(removed.status_code, 204, removed.data)
        self.assertEqual(Decimal(self.detail().data["data"]["progress"]["lines"][0]["remaining_purchase_quantity"]), 1900)

    def test_different_order_and_stale_second_bom_do_not_partially_create(self):
        payload = self.payload()
        foreign_task = self.make_task("FOREIGN")
        foreign_product = self.make_product_line(foreign_task)
        foreign_bom, _ = self.make_bom(foreign_product, section_type=BomSectionType.ACCESSORY, budget_quantity="50")
        foreign_revision = self.get_source(foreign_task, foreign_bom).data["data"]["source_revision"]
        stale_source = {**payload["sources"][1], "source_revision": "0" * 64}
        for source in ({"bom_id": str(foreign_bom.pk), "source_revision": foreign_revision}, stale_source):
            with self.subTest(bom_id=source["bom_id"]):
                changed = deepcopy(payload)
                changed["sources"][1] = source
                response = self.client.post("/api/v1/purchase-groups/", changed, format="json")
                self.assertIn(response.status_code, (400, 404, 409), response.data)
                self.assertFalse(PurchaseGroup.objects.exists())

    def test_retry_with_reversed_products_returns_same_group(self):
        payload = self.payload()
        created = self.client.post("/api/v1/purchase-groups/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        payload["sources"].reverse()
        repeated = self.client.post("/api/v1/purchase-groups/", payload, format="json")
        self.assertEqual(repeated.status_code, 201, repeated.data)
        self.assertEqual(created.data["data"]["id"], repeated.data["data"]["id"])
        self.assertEqual(PurchaseGroup.objects.count(), 1)
