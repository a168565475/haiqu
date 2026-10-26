import json
import re
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.organizations.models import Employee
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit

from ..models import (
    MaterialInbound,
    MaterialInboundLine,
    MaterialStockBalance,
    MaterialStockMovement,
    PublicStockBalance,
    PublicStockCutoverControl,
    PublicStockMovement,
    Warehouse,
    WarehouseLocation,
    WarehouseZone,
)
from ..public_stock_identity import build_pipe_stock_identity


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class PublicInventoryPaginationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="public_inventory_page_admin", is_superuser=True, is_staff=True,
        )
        cls.employee = Employee.objects.create(
            user=cls.user, employee_code="PUBLIC_INVENTORY_PAGE", display_name="公共库存分页测试",
        )
        cls.unit, _ = ProductionUnit.objects.get_or_create(unit_name="根", defaults={"unit_code": "PAGE_ROOT"})
        cls.ordinary_category, _ = ProductCategory.objects.get_or_create(
            category_name="分页测试面料", defaults={"item_type": "MATERIAL"},
        )
        cls.pipe_category, _ = ProductCategory.objects.get_or_create(
            category_name="管材", defaults={"item_type": "MATERIAL"},
        )
        cls.warehouse = Warehouse.objects.create(
            warehouse_number="PUBLIC_PAGE_WH", warehouse_name="分页材料仓", warehouse_type="MATERIAL",
        )
        cls.zone = WarehouseZone.objects.create(id=UUID(int=200), warehouse=cls.warehouse, zone_name="分页一区")
        cls.other_zone = WarehouseZone.objects.create(id=UUID(int=100), warehouse=cls.warehouse, zone_name="分页二区")
        cls.location = WarehouseLocation.objects.create(zone=cls.zone, location_number="PAGE_LOCATION")

    def setUp(self):
        self.client.force_authenticate(self.user)

    def material(self, number, *, pipe=False, material_id=None):
        values = {"id": UUID(int=material_id)} if material_id is not None else {}
        return RawMaterialInformation.objects.create(
            material_number=number, material_name=number, item_type="MATERIAL",
            category=self.pipe_category if pipe else self.ordinary_category,
            unit=self.unit, specification="分页测试规格", material="分页测试材质",
            warehouse_number=self.warehouse.warehouse_number, warehouse_name=self.warehouse.warehouse_name,
            **values,
        )

    def ordinary(self, material, *, zone=None, quantity="5", quality="AVAILABLE", occurred_at=None):
        balance = MaterialStockBalance.objects.create(
            raw_material=material, zone=zone or self.zone, unit=self.unit,
            quantity=Decimal(quantity), quality=quality,
        )
        if occurred_at is not None:
            self.movement(balance, quantity=quantity, occurred_at=occurred_at)
        return balance

    def pipe(self, material, *, zone=None, length="3.05", quantity="2", quality="AVAILABLE", occurred_at=None):
        identity = build_pipe_stock_identity(raw_material=material, raw_bar_length_m=length, unit=self.unit)
        balance = PublicStockBalance.objects.create(
            stock_kind="RAW_PIPE", identity_key=identity["identity_key"],
            identity_snapshot=identity["identity_snapshot"], raw_material=material,
            raw_bar_length_m=Decimal(length), unit=self.unit, zone=zone or self.zone,
            quantity=Decimal(quantity), meter_quantity=Decimal(quantity) * Decimal(length), quality=quality,
        )
        if occurred_at is not None:
            self.movement(balance, quantity=quantity, occurred_at=occurred_at)
        return balance

    def movement(self, balance, *, quantity, occurred_at, before="0"):
        model = PublicStockMovement if isinstance(balance, PublicStockBalance) else MaterialStockMovement
        values = {}
        if isinstance(balance, PublicStockBalance):
            values = {
                "meter_quantity": Decimal(quantity) * balance.raw_bar_length_m,
                "before_meter_quantity": Decimal(before) * balance.raw_bar_length_m,
                "after_meter_quantity": (Decimal(before) + Decimal(quantity)) * balance.raw_bar_length_m,
            }
        return model.objects.create(
            balance=balance, direction="IN", quantity=Decimal(quantity), before_quantity=Decimal(before),
            after_quantity=Decimal(before) + Decimal(quantity), source_type="PAGINATION_TEST",
            source_id=uuid4(), source_line_id=uuid4(), actor_employee=self.employee,
            occurred_at=occurred_at, **values,
        )

    def inventory(self, **params):
        response = self.client.get(
            "/api/v1/material-inventory/",
            {"stock_kind": "RAW", "warehouse_id": str(self.warehouse.pk), **params},
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {"count", "next", "previous", "results"})
        return response.data

    def test_both_public_raw_branches_limit_candidate_rows_before_merging(self):
        for index in range(3):
            self.ordinary(self.material(f"PAGE_LIMIT_OTHER_{index}"))
            self.pipe(self.material(f"PAGE_LIMIT_PIPE_{index}", pipe=True))
        for page in (1, 2):
            candidate_rows = {}

            def record_candidates(execute, sql, params, many, context):
                result = execute(sql, params, many, context)
                for source, table in (("ordinary", "inventory_material_stock_balance"),
                                      ("pipe", "inventory_public_stock_balance")):
                    if (f'FROM "{table}"' in sql and 'AS "latest_inbound_time"' in sql
                            and not re.match(r"\s*SELECT\s+COUNT\s*\(", sql, re.IGNORECASE)):
                        candidate_rows[source] = context["cursor"].rowcount
                return result

            with (self.subTest(page=page), CaptureQueriesContext(connection) as captured,
                  connection.execute_wrapper(record_candidates)):
                result = self.inventory(page=page, page_size=2)
            self.assertEqual(result["count"], 6)
            self.assertEqual(len(result["results"]), 2)
            self.assertEqual(set(candidate_rows), {"ordinary", "pipe"})
            for rowcount in candidate_rows.values():
                self.assertGreaterEqual(rowcount, 0)
                self.assertLessEqual(rowcount, page * 2)
            print(json.dumps({"page": page, "total": result["count"],
                              "candidate_rows_by_source": candidate_rows}, sort_keys=True))
            for table in ("inventory_material_stock_balance", "inventory_public_stock_balance"):
                selected = [
                    entry["sql"] for entry in captured.captured_queries
                    if f'FROM "{table}"' in entry["sql"]
                    and 'AS "latest_inbound_time"' in entry["sql"]
                    and not re.match(r"\s*SELECT\s+COUNT\s*\(", entry["sql"], re.IGNORECASE)
                ]
                self.assertEqual(len(selected), 1, selected)
                # 内层流水子查询已有 LIMIT 1；只认可最外层末尾的分页上限。
                self.assertRegex(selected[0], rf"\bLIMIT\s+{page * 2}\s*$")

    def test_mixed_rows_keep_sort_order_lengths_and_stable_cross_page_results(self):
        occurred_at = timezone.now()
        high = self.material("PAGE_ORDER_HIGH", material_id=300)
        pipe = self.material("PAGE_ORDER_PIPE", pipe=True, material_id=200)
        low = self.material("PAGE_ORDER_LOW", material_id=100)
        no_movement = self.material("PAGE_ORDER_NULL", material_id=400)
        self.ordinary(high, occurred_at=occurred_at)
        self.pipe(pipe, length="3.05", occurred_at=occurred_at)
        self.pipe(pipe, length="6.10", occurred_at=occurred_at)
        self.pipe(pipe, zone=self.other_zone, length="3.05", occurred_at=occurred_at)
        self.ordinary(low, occurred_at=occurred_at)
        self.ordinary(no_movement)
        full = self.inventory(page_size=100)
        self.assertEqual(full["count"], 6)
        rows = full["results"]
        self.assertEqual(
            [str(row["stock_item_id"]) for row in rows],
            [str(item.pk) for item in (high, pipe, pipe, pipe, low, no_movement)],
        )
        self.assertEqual([str(row["zone_id"]) for row in rows[1:4]],
                         [str(self.zone.pk), str(self.zone.pk), str(self.other_zone.pk)])
        self.assertEqual({row["raw_bar_length_m"] for row in rows[1:3]}, {Decimal("3.05"), Decimal("6.10")})
        self.assertIsNone(rows[-1]["latest_inbound_time"])
        self.assertTrue(all(row["stock_mode"] == "PUBLIC_V2" for row in rows))
        full_keys = [row["inventory_key"] for row in rows]
        for _ in range(2):
            paged_keys = []
            for page in (1, 2, 3):
                result = self.inventory(page=page, page_size=2)
                self.assertEqual(result["count"], 6)
                paged_keys.extend(row["inventory_key"] for row in result["results"])
            self.assertEqual(paged_keys, full_keys)
            self.assertEqual(len(set(paged_keys)), 6)
        self.assertEqual(self.inventory(page=4, page_size=2)["results"], [])

    def test_multiple_inbound_movements_do_not_multiply_ordinary_quantity_or_count(self):
        material = self.material("PAGE_ORDINARY_AGGREGATION")
        balance = self.ordinary(material, quantity="5")
        self.movement(balance, quantity="2", occurred_at=timezone.now() - timedelta(days=1))
        self.movement(balance, quantity="3", before="2", occurred_at=timezone.now())
        self.ordinary(material, zone=self.other_zone, quantity="7")
        result = self.inventory()
        self.assertEqual(result["count"], 2)
        by_zone = {str(row["zone_id"]): row for row in result["results"]}
        self.assertEqual(by_zone[str(self.zone.pk)]["inventory_quantity"], Decimal("5"))
        self.assertEqual(by_zone[str(self.zone.pk)]["inbound_count"], 2)
        self.assertEqual(by_zone[str(self.other_zone.pk)]["inventory_quantity"], Decimal("7"))

    def test_keyword_section_zone_and_location_filters_keep_existing_meanings(self):
        ordinary = self.material("PAGE_FILTER_ORDINARY")
        pipe = self.material("PAGE_FILTER_PIPE", pipe=True)
        self.ordinary(ordinary)
        self.pipe(pipe, zone=self.other_zone)
        receipt = MaterialInbound.objects.create(
            inbound_number="PAGE_FILTER_INBOUND", status="CONFIRMED", stock_mode="PUBLIC_V2",
            received_by_employee=self.employee,
        )
        MaterialInboundLine.objects.create(
            inbound=receipt, raw_material_information=ordinary, zone=self.zone, location=self.location,
            received_quantity=1, accepted_quantity=1, purchased_quantity_snapshot=1,
            section_type_snapshot="FABRIC", section_title_snapshot="分页裁剪明细",
            part_name_snapshot="分页普通材料", source_unit_text_snapshot=self.unit.unit_name,
            material_pinyin_search="pagefilterpinyin",
        )
        cases = (
            ({"q": "PAGE_FILTER_ORDINARY"}, ordinary),
            ({"q": "PAGE_FILTER_PIPE"}, pipe),
            ({"q": "pagefilterpinyin"}, ordinary),
            ({"section_title": "分页裁剪明细"}, ordinary),
            ({"section_title": "管材"}, pipe),
            ({"zone_id": str(self.zone.pk)}, ordinary),
            ({"zone_id": str(self.other_zone.pk)}, pipe),
        )
        for params, expected in cases:
            with self.subTest(params=params):
                result = self.inventory(**params)
                self.assertEqual(result["count"], 1)
                self.assertEqual(str(result["results"][0]["stock_item_id"]), str(expected.pk))
        # 余额按库区记账，历史入库位置不能冒充库位净库存。
        self.assertEqual(self.inventory(location_id=str(self.location.pk))["count"], 0)
        self.assertEqual(self.inventory(q="PAGE_FILTER_MISSING")["results"], [])

    def test_zero_and_defective_balances_are_excluded_from_rows_and_count(self):
        ordinary = self.material("PAGE_QUALITY_ORDINARY")
        pipe = self.material("PAGE_QUALITY_PIPE", pipe=True)
        self.ordinary(ordinary, quantity="0")
        self.ordinary(ordinary, quality="DEFECTIVE", quantity="3")
        self.pipe(pipe, quantity="0")
        self.pipe(pipe, quality="DEFECTIVE", quantity="3")
        self.pipe(pipe, length="6.10", quantity="2")
        result = self.inventory(page_size=1)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["raw_bar_length_m"], Decimal("6.10"))
        self.assertEqual(result["results"][0]["inventory_quantity"], Decimal("2"))

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=False)
    def test_public_cutover_keeps_public_rows_enabled_when_setting_is_false(self):
        PublicStockCutoverControl.objects.create(state="PUBLIC", reason="隔离测试已完成切换")
        material = self.material("PAGE_CUTOVER_PIPE", pipe=True)
        self.pipe(material)
        result = self.inventory()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["stock_mode"], "PUBLIC_V2")

    def test_ordinary_unit_names_keep_stable_order_across_pages(self):
        material = self.material("PAGE_UNIT_ORDER")
        occurred_at = timezone.now()
        names = ("PAGE_A", "分页单位", "PAGE_Z")
        for index, name in enumerate(names):
            unit = ProductionUnit.objects.create(unit_code=f"PAGE_SORT_{index}", unit_name=name)
            balance = MaterialStockBalance.objects.create(
                raw_material=material, zone=self.zone, unit=unit, quantity=Decimal("1"),
            )
            self.movement(balance, quantity="1", occurred_at=occurred_at)
        expected = ["分页单位", "PAGE_Z", "PAGE_A"]
        full = self.inventory(page_size=100)
        self.assertEqual(full["count"], 3)
        self.assertEqual([row["unit"] for row in full["results"]], expected)
        for _ in range(2):
            paged = [self.inventory(page=page, page_size=1)["results"][0] for page in (1, 2, 3)]
            self.assertEqual([row["unit"] for row in paged], expected)
            self.assertEqual(len({row["inventory_key"] for row in paged}), 3)

    def test_opening_movement_updates_latest_time_but_not_inbound_count(self):
        balance = self.pipe(self.material("PAGE_OPENING_PIPE", pipe=True), quantity="3")
        latest = timezone.now()
        self.movement(balance, quantity="1", occurred_at=latest - timedelta(days=1))
        opening = self.movement(balance, quantity="2", before="1", occurred_at=latest)
        PublicStockMovement.objects.filter(pk=opening.pk).update(source_type="PUBLIC_STOCK_OPENING")
        result = self.inventory()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["inbound_count"], 1)
        self.assertEqual(result["results"][0]["latest_inbound_time"], latest)
        self.assertEqual(result["results"][0]["inventory_quantity"], Decimal("3"))

    def test_list_requires_login_and_inventory_permission(self):
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/v1/material-inventory/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 401)
        denied_user = get_user_model().objects.create_user(username="public_page_denied")
        Employee.objects.create(user=denied_user, employee_code="PUBLIC_PAGE_DENIED", display_name="无库存权限")
        self.client.force_authenticate(denied_user)
        response = self.client.get("/api/v1/material-inventory/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 403)

    def test_invalid_parameters_are_rejected_and_huge_page_is_empty(self):
        self.ordinary(self.material("PAGE_PARAMETER_OTHER"))
        invalid = (
            {"stock_kind": "INVALID"}, {"page": "invalid"}, {"page": 0}, {"page_size": 0},
            {"warehouse_id": "invalid"}, {"zone_id": "invalid"}, {"location_id": "invalid"},
        )
        for params in invalid:
            with self.subTest(params=params):
                response = self.client.get("/api/v1/material-inventory/", params, HTTP_HOST="localhost")
                self.assertEqual(response.status_code, 400, response.data)
        result = self.inventory(page=10 ** 30, page_size=100)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"], [])

    @override_settings(PUBLIC_STOCK_FLOW_ENABLED=False)
    def test_legacy_list_keeps_page_count_and_stock_mode(self):
        latest = timezone.now()
        older = self.material("PAGE_LEGACY_OLDER")
        newer = self.material("PAGE_LEGACY_NEWER")
        self.ordinary(older, occurred_at=latest - timedelta(days=1))
        self.ordinary(newer, occurred_at=latest)
        self.ordinary(self.material("PAGE_LEGACY_ZERO"), quantity="0")
        self.pipe(self.material("PAGE_LEGACY_PUBLIC_PIPE", pipe=True), occurred_at=latest)
        for page, expected in ((1, newer), (2, older)):
            with self.subTest(page=page):
                result = self.inventory(page=page, page_size=1)
                self.assertEqual(result["count"], 2)
                self.assertEqual(len(result["results"]), 1)
                self.assertEqual(str(result["results"][0]["stock_item_id"]), str(expected.pk))
                self.assertEqual(result["results"][0]["stock_mode"], "LEGACY")
        beyond = self.inventory(page=3, page_size=1)
        self.assertEqual(beyond["count"], 2)
        self.assertEqual(beyond["results"], [])
