from copy import deepcopy
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.boms.catalog_selection import apply_catalog_selection
from apps.boms.material_flow_bom import inherit_cutting_fabric_attributes
from apps.boms.models import BomLine, BomSection


class CuttingFabricInheritanceTests(SimpleTestCase):
    def test_catalog_cutting_cannot_claim_pipe_category_to_bypass_source(self):
        cutting = BomLine(section=BomSection(title="裁剪明细", section_type="FABRIC"), category="管材",
                          raw_values={"cutting_category": "管材"})
        data = {"material_catalog_id": str(uuid4()), "material_selection": {"attributes": {"size": "伪造尺寸"}}}
        with self.assertRaisesMessage(ValidationError, "来源面料"):
            apply_catalog_selection(cutting, data, old=None, request=None, persist=False, versions={}, inherit_fabric_source=True)

    def test_catalog_cutting_records_source_spec_color_and_color_identity_without_obsolete_attributes(self):
        source = BomLine(specification="600D / 1.8", material="来源材质", raw_values={}, material_selection_snapshot={
            "attributes": {"material": "来源属性材质", "width": "1.8", "fabric_spec": "600D", "color": "蓝色"}, "product_color_id": str(uuid4()),
            "color_card": "A", "color_code": "01", "color_name": "蓝色",
        })
        original = {"name": "外袋", "unit_name": "套", "completed_craft": {"code": "CUTTING"},
                    "attributes": {"material": "裁片材质", "width": "1.5", "color": "伪造色", "size": "旧尺寸",
                                   "model": "旧款号", "process": "旧做法", "fabric_spec": "旧规格"}}
        cutting = BomLine(section=BomSection(title="裁剪明细", section_type="FABRIC"), fabric_source_line=source,
                          material_catalog_id=uuid4(), material="裁片材质", raw_values={}, material_selection_snapshot=original)
        before = deepcopy(original)
        inherit_cutting_fabric_attributes(cutting)
        self.assertEqual(cutting.specification, "600D / 1.8")
        self.assertEqual(cutting.raw_values["cutting_color"], "蓝色")
        self.assertEqual(cutting.material, "来源属性材质")
        self.assertEqual(cutting.raw_values["fabric_width"], "1.8")
        self.assertEqual(cutting.material_selection_snapshot["attributes"],
                         {"material": "来源属性材质", "width": "1.8", "color": "蓝色", "specification": "600D"})
        self.assertEqual(cutting.material_selection_snapshot["product_color_id"], source.material_selection_snapshot["product_color_id"])
        self.assertEqual(cutting.material_selection_snapshot["completed_craft"], before["completed_craft"])
        self.assertEqual(original, before)

    def test_missing_source_material_width_does_not_keep_independent_cutting_values(self):
        source = BomLine(specification="600D", raw_values={})
        cutting = BomLine(section=BomSection(title="裁剪明细", section_type="FABRIC"), fabric_source_line=source,
                          material_catalog_id=uuid4(), material="旧裁片材质", raw_values={"fabric_width": "旧门幅"},
                          material_selection_snapshot={"name": "外袋", "unit_name": "套", "attributes": {"material": "旧裁片材质", "width": "旧门幅"}})
        inherit_cutting_fabric_attributes(cutting)
        self.assertEqual((cutting.material, cutting.raw_values["fabric_width"]), ("", ""))
        self.assertEqual(cutting.material_selection_snapshot["attributes"], {"specification": "600D"})

    def test_legacy_cutting_inherits_source_and_pipe_cutting_keeps_existing_contract(self):
        source = BomLine(specification="400D", material="涤纶", raw_values={"fabric_color_name": "红色"})
        cutting = BomLine(section=BomSection(title="裁剪明细", section_type="FABRIC"),
                          fabric_source_line=source, specification="旧加工尺寸", raw_values={})
        inherit_cutting_fabric_attributes(cutting)
        self.assertEqual((cutting.material, cutting.specification, cutting.raw_values["cutting_color"]), ("涤纶", "400D", "红色"))
        cutting.category, cutting.specification = "管材", "原管材规格"
        inherit_cutting_fabric_attributes(cutting)
        self.assertEqual(cutting.specification, "原管材规格")

    def test_legacy_cutting_without_fabric_source_keeps_recorded_specification(self):
        cutting = BomLine(section=BomSection(title="裁剪明细", section_type="FABRIC"),
                          specification="旧独立裁片规格", raw_values={})
        inherit_cutting_fabric_attributes(cutting)
        self.assertEqual(cutting.specification, "旧独立裁片规格")
