"""总单产品展示的纯契约回归；禁止数据库访问。"""
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from ..api.group_serializers import PurchaseGroupSerializer
from ..group_selectors import purchase_groups_with_context


class PurchaseGroupProductDisplayTests(SimpleTestCase):
    def setUp(self):
        self.task_id, self.product_id = uuid4(), uuid4()
        self.product = SimpleNamespace(
            pk=self.product_id, production_task_id=self.task_id,
            product_name_snapshot="订单产品", specification_snapshot="订单规格", material_snapshot="铝合金",
            color_card_snapshot="色卡", color_name_snapshot="蓝", color_code_snapshot="B01",
            quantity=9007199254740993, unit_id=uuid4(), unit=SimpleNamespace(unit_name="套"),
        )
        self.snapshot = {"product_name_snapshot": "冻结产品", "product_specification_snapshot": "80x90；颜色：蓝；材质：铝合金",
                         "material_snapshot": "这是材料，不是产品材质", "required_quantity": "999"}
        self.source = SimpleNamespace(product_line_id_snapshot=self.product_id, source_snapshot=self.snapshot)
        self.sources = [self.source]
        self.task = SimpleNamespace(delivery_date=date(2026, 11, 7), purchase_group_products=[self.product])
        self.group = SimpleNamespace(production_task=self.task, production_task_id=self.task_id,
                                     product_line_id_snapshot=self.product_id, lines=SimpleNamespace(all=lambda: self.sources))
        self.serializer = PurchaseGroupSerializer()

    def test_exact_product_and_frozen_fields_without_queries_or_mutation(self):
        before = deepcopy(self.snapshot)
        self.task.purchase_group_products.insert(0, SimpleNamespace(pk=uuid4(), production_task_id=self.task_id))
        self.sources.insert(0, SimpleNamespace(product_line_id_snapshot=uuid4(), source_snapshot={"product_name_snapshot": "不应选首行"}))
        result = self.serializer.get_product(self.group)
        self.assertEqual(result, {"product_line_id": str(self.product_id), "product_name": "冻结产品", "specification": "80x90",
            "material": "铝合金", "color_card": "色卡", "color_name": "蓝", "color_code": "B01",
            "order_quantity": "9007199254740993", "order_unit": "套"})
        self.assertEqual(self.snapshot, before)

    def test_missing_relation_keeps_only_exact_frozen_name_and_specification(self):
        self.task.purchase_group_products = []
        result = self.serializer.get_product(self.group)
        self.assertEqual(result["product_name"], "冻结产品")
        self.assertEqual(result["specification"], self.snapshot["product_specification_snapshot"])
        self.assertIsNone(result["order_quantity"])
        for field in ("material", "color_card", "color_name", "color_code", "order_unit"):
            self.assertEqual(result[field], "")

    def test_cross_task_product_is_not_used(self):
        self.product.production_task_id = uuid4()
        self.assertIsNone(self.serializer.get_product(self.group)["order_quantity"])
        self.sources.clear()
        self.assertIsNone(self.serializer.get_product(self.group))

    def test_null_id_does_not_match_null_source_or_first_product(self):
        self.group.product_line_id_snapshot = None
        self.source.product_line_id_snapshot = None
        self.assertIsNone(self.serializer.get_product(self.group))

    def test_legal_product_without_source_uses_only_its_order_snapshot(self):
        self.snapshot.update(product_name_snapshot="", product_specification_snapshot="")
        result = self.serializer.get_product(self.group)
        self.assertEqual(result["product_name"], "")
        self.assertEqual(result["specification"], "")
        self.snapshot.clear()
        result = self.serializer.get_product(self.group)
        self.assertEqual(result["product_name"], "订单产品")
        self.assertEqual(result["specification"], "订单规格")
        self.sources.clear()
        result = self.serializer.get_product(self.group)
        self.assertEqual(result["product_name"], "订单产品")
        self.assertEqual(result["specification"], "订单规格")
        self.assertEqual(result["order_quantity"], str(self.product.quantity))

    def test_missing_product_and_unmatched_source_returns_null(self):
        self.task.purchase_group_products = []
        self.source.product_line_id_snapshot = uuid4()
        self.assertIsNone(self.serializer.get_product(self.group))

    def test_order_date_is_read_only_nullable_and_independent_of_product(self):
        field = self.serializer.fields["order_delivery_date"]
        self.assertTrue(field.read_only)
        self.assertTrue(field.allow_null)
        self.assertEqual(field.to_representation(field.get_attribute(self.group)), "2026-11-07")
        self.task.delivery_date = None
        self.assertIsNone(field.get_attribute(self.group))
        self.assertTrue(self.serializer.fields["product"].read_only)

    def test_selector_loads_product_and_unit_context_without_query_evaluation(self):
        queryset = purchase_groups_with_context()
        self.assertIn("production_task", queryset.query.select_related)
        lookup = next(item for item in queryset._prefetch_related_lookups if getattr(item, "to_attr", None) == "purchase_group_products")
        self.assertEqual(lookup.prefetch_through, "production_task__products")
        self.assertIn("unit", lookup.queryset.query.select_related)
        fields = lookup.queryset.query.deferred_loading[0]
        self.assertTrue({"quantity", "unit_id", "unit__unit_name", "production_task_id", "material_snapshot"}.issubset(fields))
