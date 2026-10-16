from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from ..importing import ImportPayloadSerializer, _merge_catalogs, _prepare_catalog


class MaterialCatalogFlowUnitValidationTests(SimpleTestCase):
    def prepare(self, category="HARDWARE", template="HARDWARE", scope="BASE"):
        serializer = ImportPayloadSerializer(data={
            "version": 1,
            "source": {"filename": "原料信息.xlsx", "sha256": "a" * 64},
            "catalogs": [{
                "name": "五金流转单位", "category_key": category, "template_key": template,
                "spray_enabled": template in {"HARDWARE", "TUBE"},
                "values": [{"scope": scope, "field_key": "flow_unit", "value": "KG"}],
                "units": [],
            }],
        })
        serializer.is_valid(raise_exception=True)
        row = _merge_catalogs(serializer.validated_data["catalogs"])[0]
        return _prepare_catalog(row, None, {})

    def test_hardware_flow_unit_is_an_independent_attribute_without_allowed_units(self):
        try:
            plan = self.prepare()
        except ValidationError as exc:
            self.fail(f"五金独立流转单位被拒绝：{exc.detail}")
        self.assertIn({"scope": "BASE", "field_key": "flow_unit", "value": "KG"}, plan["values"])
        self.assertEqual(plan["units"], [])

    def test_other_templates_reject_flow_unit(self):
        for category, template in (
            ("TUBE", "TUBE"), ("FABRIC", "FABRIC"), ("PLASTIC", "PLASTIC"),
            ("PACKAGING", "PACKAGING_GENERAL"), ("AUXILIARY", "AUXILIARY_GENERAL"),
            ("FABRIC_SEMI", "FABRIC_SEMI"),
        ):
            with self.subTest(template=template), self.assertRaises(ValidationError):
                self.prepare(category, template)

    def test_spray_group_rejects_flow_unit(self):
        with self.assertRaises(ValidationError):
            self.prepare(scope="SPRAY")
