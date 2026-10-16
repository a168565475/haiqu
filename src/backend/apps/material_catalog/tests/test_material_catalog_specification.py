from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from ..importing import ImportPayloadSerializer, _merge_catalogs, _prepare_catalog


class MaterialCatalogSpecificationValidationTests(SimpleTestCase):
    def prepare(self, category, template, *, scope="BASE", spray_enabled=False):
        serializer = ImportPayloadSerializer(data={
            "version": 1,
            "source": {"filename": "原料信息.xlsx", "sha256": "a" * 64},
            "catalogs": [{
                "name": "规格原文档案", "category_key": category, "template_key": template,
                "spray_enabled": spray_enabled,
                "values": [
                    {"scope": scope, "field_key": "specification", "value": "Φ20×30 / 厚0.8；A型"},
                    {"scope": scope, "field_key": "specification", "value": "30×40×2（含接头）\n按图加工"},
                    {"scope": "BASE", "field_key": "material", "value": "材质甲"},
                    {"scope": "BASE", "field_key": "material", "value": "材质乙"},
                ],
                "units": [],
            }],
        })
        serializer.is_valid(raise_exception=True)
        row = _merge_catalogs(serializer.validated_data["catalogs"])[0]
        return _prepare_catalog(row, None, {})

    def test_confirmed_templates_keep_multiple_verbatim_specifications_as_independent_values(self):
        for category, template in (
            ("PLASTIC", "PLASTIC"), ("FABRIC_SEMI", "FABRIC_SEMI"),
            ("AUXILIARY", "TAPE"), ("AUXILIARY", "COTTON"),
        ):
            with self.subTest(template=template):
                try:
                    plan = self.prepare(category, template)
                except ValidationError as exc:
                    self.fail(f"已确认的规格描述被拒绝：{exc.detail}")
                self.assertEqual(
                    [value["value"] for value in plan["values"] if value["field_key"] == "specification"],
                    ["Φ20×30 / 厚0.8；A型", "30×40×2（含接头）\n按图加工"],
                )
                self.assertEqual(len(plan["values"]), 5)
                self.assertFalse(plan["spray_enabled"])

    def test_unconfirmed_templates_still_reject_specification(self):
        for category, template in (
            ("TUBE", "TUBE"), ("FABRIC", "FABRIC"),
            ("PACKAGING", "CARTON"), ("PACKAGING", "BAG"),
        ):
            with self.subTest(template=template):
                with self.assertRaises(ValidationError):
                    self.prepare(category, template)

    def test_spray_group_still_rejects_specification(self):
        for template in ("TUBE", "HARDWARE"):
            with self.subTest(template=template):
                with self.assertRaises(ValidationError):
                    self.prepare(template, template, scope="SPRAY", spray_enabled=True)
