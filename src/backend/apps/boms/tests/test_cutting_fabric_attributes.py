from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit
from ..material_flow_bom import inherit_cutting_fabric_attributes
from ..material_save_plan import build_material_save_plan
from ..models import Bom, BomLine, BomSection


class CuttingFabricAttributeTests(SimpleTestCase):
    def test_source_overrides_manual_attributes_without_changing_cutting_specification(self):
        bom = Bom(order_quantity=10)
        fabric = BomLine(section=BomSection(bom=bom, section_type="FABRIC", title="面料类"),
                         material="PU", raw_values={"fabric_color_name": "绿色"})
        cutting = BomLine(section=BomSection(bom=bom, section_type="FABRIC", title="裁剪明细"),
                          fabric_source_line=fabric, material="210D", specification="20", unit="套",
                          raw_values={"cutting_color": "红色", "cutting_material_original": "210D"})
        inherit_cutting_fabric_attributes(cutting)
        self.assertEqual((cutting.material, cutting.raw_values["cutting_color"], cutting.specification, cutting.unit),
                         ("PU", "绿色", "20", "套"))
        self.assertNotIn("cutting_material_original", cutting.raw_values)
        fabric.material = "PVC"
        fabric.raw_values = {"fabric_color_code": "5865C"}
        inherit_cutting_fabric_attributes(cutting)
        self.assertEqual((cutting.material, cutting.raw_values["cutting_color"]), ("PVC", "5865C"))

    def test_missing_source_clears_hidden_attributes_and_legacy_value(self):
        cutting = BomLine(section=BomSection(section_type="FABRIC", title="裁剪明细"),
                          material="PU", raw_values={"cutting_color": "绿色", "cutting_material_original": "210D"})
        inherit_cutting_fabric_attributes(cutting)
        self.assertEqual((cutting.material, cutting.raw_values["cutting_color"]), ("", ""))
        self.assertNotIn("cutting_material_original", cutting.raw_values)

    def test_legacy_pipe_cutting_keeps_its_own_attributes(self):
        for category, cutting_category in (("管材半成品", ""), ("", "管材")):
            with self.subTest(category=category, cutting_category=cutting_category):
                cutting = BomLine(section=BomSection(section_type="FABRIC", title="裁剪明细"),
                                  category=category, material="Q195",
                                  raw_values={"cutting_color": "黑色", "cutting_category": cutting_category})
                inherit_cutting_fabric_attributes(cutting)
                self.assertEqual((cutting.material, cutting.raw_values["cutting_color"]), ("Q195", "黑色"))

    def plan(self, *, foreign_source=False):
        key, color_id = uuid4(), uuid4()
        source = RawMaterialInformation(
            item_type="SEMI_FINISHED", material_number="CUT-TEST", material_name="外袋", material="旧材质",
            specification="20", category=ProductCategory(item_type="SEMI_FINISHED", category_name="裁片"),
            unit=ProductionUnit(unit_name="套"), color_snapshot="红色",
        )
        cutting = {"part_name": "外袋", "material": "210D", "cutting_color": "红色",
                   "specification": "20", "_pending_raw_source": source,
                   "fabric_source_line_id": uuid4()} if foreign_source else {
                       "part_name": "外袋", "material": "210D", "cutting_color": "红色",
                       "specification": "20", "_pending_raw_source": source, "fabric_source_client_key": key,
                   }
        sections = [
            {"section_type": "FABRIC", "title": "裁剪明细", "lines": [cutting]},
            {"section_type": "FABRIC", "title": "面料类", "lines": [{"client_key": key,
                "part_name": "布料", "material": "PU", "fabric_color_name": "绿色",
                "source_product_color_id": color_id}]},
        ]
        with ExitStack() as stack:
            stack.enter_context(patch("apps.boms.material_save_plan.BomLine.objects.filter")).return_value.select_related.return_value = []
            for name in ("FabricMaterial", "AccessoryMaterial"):
                stack.enter_context(patch(f"apps.boms.material_save_plan.{name}.objects.filter")).return_value.exclude.return_value.values_list.return_value = []
            stack.enter_context(patch("apps.boms.material_save_plan.RawMaterialInformation.objects.annotate")).return_value.filter.return_value.select_related.return_value.order_by.return_value = []
            stack.enter_context(patch("apps.boms.material_save_plan.synchronize_fabric_material"))
            stack.enter_context(patch("apps.boms.material_flow_bom.apply_line_quantities"))
            resolve = stack.enter_context(patch("apps.boms.material_save_plan._generic_source", return_value=source))
            plan = build_material_save_plan(bom=Bom(order_quantity=10), sections=sections, request=SimpleNamespace())
        return plan, resolve.call_args.args[0], source, color_id

    def test_pending_cutting_archive_inherits_before_matching_even_when_submitted_first(self):
        plan, proposed, original, color_id = self.plan()
        self.assertEqual((proposed.material, str(proposed.color_id), proposed.color_snapshot), ("PU", str(color_id), "绿色"))
        self.assertEqual((original.material, original.color_snapshot), ("旧材质", "红色"))
        self.assertEqual((plan["lines"][(0, 1)].material, plan["lines"][(0, 1)].raw_values["cutting_color"]),
                         ("PU", "绿色"))

    def test_pending_cutting_cannot_use_a_fabric_line_outside_submitted_bom(self):
        with self.assertRaisesMessage(ValidationError, "本 BOM 保留的面料行"):
            self.plan(foreign_source=True)
