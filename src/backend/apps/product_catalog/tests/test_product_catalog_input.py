from uuid import uuid4

from django.test import SimpleTestCase

from ..api.serializers import ColorCreateSerializer, NameCreateSerializer, NamePatchSerializer


class ProductCatalogInputTests(SimpleTestCase):
    def test_name_create_and_patch_preserve_complete_original_text(self):
        for serializer in (
            NameCreateSerializer(data={"category_id": str(uuid4()), "name": "  完整月亮椅（白色款）  "}),
            NamePatchSerializer(data={"name": "  完整月亮椅（白色款）  "}),
        ):
            with self.subTest(serializer=type(serializer).__name__):
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(serializer.validated_data["name"], "  完整月亮椅（白色款）  ")

    def test_whitespace_only_names_are_rejected_without_changing_color_contract(self):
        for serializer in (
            NameCreateSerializer(data={"category_id": str(uuid4()), "name": " \t\n "}),
            NamePatchSerializer(data={"name": " \t\n "}),
        ):
            self.assertFalse(serializer.is_valid())
            self.assertIn("name", serializer.errors)
        color = ColorCreateSerializer(data={"value": "  红色  "})
        self.assertTrue(color.is_valid())
        self.assertEqual(color.validated_data["value"], "红色")
