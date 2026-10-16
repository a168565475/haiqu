from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from ..importing import ImportPayloadSerializer, _merge_catalogs, _prepare_catalog


class MaterialCatalogFabricWidthValidationTests(SimpleTestCase):
    def test_semi_finished_width_keeps_text_separate_from_specification(self):
        serializer = ImportPayloadSerializer(data={
            "version": 1,
            "source": {"filename": "原料信息.xlsx", "sha256": "a" * 64},
            "catalogs": [{
                "name": "椅面", "category_key": "FABRIC_SEMI", "template_key": "FABRIC_SEMI",
                "spray_enabled": False,
                "values": [
                    {"scope": "BASE", "field_key": "width", "value": "1.5"},
                    {"scope": "BASE", "field_key": "width", "value": "1.50"},
                    {"scope": "BASE", "field_key": "specification", "value": "103*60/49*80/29"},
                ],
                "units": [],
            }],
        })
        serializer.is_valid(raise_exception=True)
        try:
            plan = _prepare_catalog(_merge_catalogs(serializer.validated_data["catalogs"])[0], None, {})
        except ValidationError as exc:
            self.fail(f"已确认的委外布面门幅被拒绝：{exc.detail}")
        self.assertEqual(
            {(value["field_key"], value["value"]) for value in plan["values"]},
            {("width", "1.5"), ("width", "1.50"), ("specification", "103*60/49*80/29"), ("color", "无颜色")},
        )
        self.assertEqual(plan["units"], [])
