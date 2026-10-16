from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from ..importing import ImportPayloadSerializer, _merge_catalogs, _prepare_catalog


class MaterialCatalogPackagingModelValidationTests(SimpleTestCase):
    def test_packaging_model_preserves_original_text_without_reclassifying_it(self):
        for template, size_field in (("CARTON", "size"), ("BAG", "size"), ("PACKAGING_GENERAL", "specification")):
            with self.subTest(template=template):
                serializer = ImportPayloadSerializer(data={
                    "version": 1,
                    "source": {"filename": "原料信息.xlsx", "sha256": "a" * 64},
                    "catalogs": [{
                        "name": "包材型号", "category_key": "PACKAGING", "template_key": template,
                        "spray_enabled": False,
                        "values": [
                            {"scope": "BASE", "field_key": "model", "value": "2.5MM"},
                            {"scope": "BASE", "field_key": "model", "value": "10.1*7.6"},
                            {"scope": "BASE", "field_key": size_field, "value": "78*65"},
                        ],
                        "units": [],
                    }],
                })
                serializer.is_valid(raise_exception=True)
                try:
                    plan = _prepare_catalog(_merge_catalogs(serializer.validated_data["catalogs"])[0], None, {})
                except ValidationError as exc:
                    self.fail(f"已确认的包材型号被拒绝：{exc.detail}")
                self.assertEqual(
                    {(value["field_key"], value["value"]) for value in plan["values"]},
                    {("model", "2.5MM"), ("model", "10.1*7.6"), (size_field, "78*65"), ("color", "无颜色")},
                )
                self.assertEqual(plan["units"], [])
