from django.test import SimpleTestCase

from ..api.serializers import CatalogCreateSerializer
from ..importing import ImportPayloadSerializer


class MaterialCatalogGenericTemplateValidationTests(SimpleTestCase):
    def test_creation_accepts_generic_template_in_its_own_category(self):
        for category, template in (
            ("PACKAGING", "PACKAGING_GENERAL"),
            ("AUXILIARY", "AUXILIARY_GENERAL"),
        ):
            with self.subTest(category=category):
                serializer = CatalogCreateSerializer(data={
                    "name": "通用品名", "category_key": category, "template_key": template,
                })
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(serializer.validated_data["template_key"], template)

    def test_generic_template_cannot_cross_categories(self):
        for category, template in (
            ("PACKAGING", "AUXILIARY_GENERAL"),
            ("AUXILIARY", "PACKAGING_GENERAL"),
        ):
            with self.subTest(category=category):
                serializer = CatalogCreateSerializer(data={
                    "name": "通用品名", "category_key": category, "template_key": template,
                })
                self.assertFalse(serializer.is_valid())
                self.assertIn("template_key", serializer.errors)

    def test_import_accepts_both_generic_templates(self):
        serializer = ImportPayloadSerializer(data={
            "version": 1,
            "source": {"filename": "原料信息.xlsx", "sha256": "a" * 64},
            "catalogs": [{
                "name": "通用品名", "category_key": category, "template_key": template,
                "spray_enabled": False,
                "values": [{"scope": "BASE", "field_key": "specification", "value": "10×20"}],
                "units": [],
            } for category, template in (
                ("PACKAGING", "PACKAGING_GENERAL"),
                ("AUXILIARY", "AUXILIARY_GENERAL"),
            )],
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(len(serializer.validated_data["catalogs"]), 2)

    def test_generic_import_rejects_spray_switch(self):
        for category, template in (
            ("PACKAGING", "PACKAGING_GENERAL"),
            ("AUXILIARY", "AUXILIARY_GENERAL"),
        ):
            with self.subTest(category=category):
                serializer = ImportPayloadSerializer(data={
                    "version": 1,
                    "source": {"filename": "原料信息.xlsx", "sha256": "a" * 64},
                    "catalogs": [{
                        "name": "通用品名", "category_key": category, "template_key": template,
                        "spray_enabled": True, "values": [], "units": [],
                    }],
                })
                self.assertFalse(serializer.is_valid())
                self.assertIn("spray_enabled", serializer.errors["catalogs"][0])
