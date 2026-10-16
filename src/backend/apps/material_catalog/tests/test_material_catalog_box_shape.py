from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from ..definitions import TEMPLATES
from ..importing import ImportPayloadSerializer, _merge_catalogs, _prepare_catalog


class MaterialCatalogBoxShapeValidationTests(SimpleTestCase):
    def prepare(self, template, category="PACKAGING", scope="BASE"):
        serializer = ImportPayloadSerializer(data={
            "version": 1,
            "source": {"filename": "原料信息.xlsx", "sha256": "a" * 64},
            "catalogs": [{
                "name": "包材箱子形状", "category_key": category, "template_key": template,
                "spray_enabled": scope == "SPRAY",
                "values": [
                    {"scope": scope, "field_key": "box_type", "value": "半盖"},
                    {"scope": scope, "field_key": "box_type", "value": "天地盖"},
                ],
                "units": [],
            }],
        })
        serializer.is_valid(raise_exception=True)
        return _prepare_catalog(_merge_catalogs(serializer.validated_data["catalogs"])[0], None, {})

    def test_all_packaging_templates_keep_multiple_box_shapes_in_one_field(self):
        for template in ("CARTON", "BAG", "PACKAGING_GENERAL"):
            with self.subTest(template=template):
                try:
                    plan = self.prepare(template)
                except ValidationError as exc:
                    self.fail(f"包材箱子形状被拒绝：{exc.detail}")
                fields = [field for field in TEMPLATES[template]["fields"] if field["key"] == "box_type"]
                self.assertEqual(fields, [{"key": "box_type", "label": "箱子形状", "kind": "text"}])
                self.assertEqual([value["value"] for value in plan["values"] if value["field_key"] == "box_type"], ["半盖", "天地盖"])
                self.assertEqual(plan["units"], [])

    def test_other_categories_and_spray_reject_box_shape(self):
        for category, template, scope in (
            ("TUBE", "TUBE", "BASE"), ("HARDWARE", "HARDWARE", "BASE"),
            ("FABRIC", "FABRIC", "BASE"), ("PLASTIC", "PLASTIC", "BASE"),
            ("AUXILIARY", "AUXILIARY_GENERAL", "BASE"), ("FABRIC_SEMI", "FABRIC_SEMI", "BASE"),
            ("TUBE", "TUBE", "SPRAY"), ("HARDWARE", "HARDWARE", "SPRAY"),
        ):
            with self.subTest(template=template, scope=scope), self.assertRaises(ValidationError):
                self.prepare(template, category, scope)
