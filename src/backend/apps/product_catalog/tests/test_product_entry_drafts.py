from uuid import uuid4

from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.reference_data.models import ProductionUnit

from ..api.serializers import ProductSelectionSerializer
from ..models import ProductCatalog, ProductCatalogCategory, ProductCatalogColor, ProductCatalogName
from ..selection import resolve_product_selection


def typed_product_draft(**changes):
    values = {"category_name": "草稿类别", "name": "草稿折叠椅", "item_number": "DRAFT-01",
              "specification": "60*80", "product_code": "DRAFT-CODE", "unit_name": "未建档单位",
              "color_name": "临时红色", "material": "临时材质"}
    values.update(changes)
    values["sources"] = {key: "typed" for key in values}
    return values


class ProductEntryDraftTests(TestCase):
    def setUp(self):
        self.category = ProductCatalogCategory.objects.create(name="草稿验证类别")
        self.name = ProductCatalogName.objects.create(category=self.category, name="草稿验证品名")
        self.unit = ProductionUnit.objects.create(unit_code="ENTRY-TEST", unit_name="草稿验证单位")
        self.product = ProductCatalog.objects.create(name=self.name, item_number="SEL-1", product_code="SEL-CODE",
                                                     specification="20*30", unit=self.unit.unit_name,
                                                     materials=["铁"], thicknesses=["0.8", "1.0"])
        self.color = ProductCatalogColor.objects.create(product=self.product, value="蓝色")

    def selected_draft(self):
        return {"category_id": str(self.category.pk), "category_name": self.category.name,
                "name_id": str(self.name.pk), "name": self.name.name,
                "item_number": self.product.item_number, "specification": self.product.specification,
                "product_code": self.product.product_code, "unit_id": str(self.unit.pk), "unit_name": self.unit.unit_name,
                "color_id": str(self.color.pk), "color_name": self.color.value, "material": "铁",
                "sources": {key: "selected" for key in typed_product_draft()["sources"]}}

    def counts(self):
        return tuple(model.objects.count() for model in (
            ProductCatalogCategory, ProductCatalogName, ProductCatalog, ProductCatalogColor, ProductionUnit,
        ))

    def test_typed_draft_stores_provenance_without_creating_any_master(self):
        before = self.counts()
        product, snapshot = resolve_product_selection(None, {"draft": typed_product_draft()})
        self.assertIsNone(product)
        self.assertEqual(self.counts(), before)
        self.assertEqual(snapshot["entry_state"], "draft")
        self.assertEqual(snapshot["unit_name"], "未建档单位")
        self.assertEqual(snapshot["unit_code"], "")
        for field in ("catalog_id", "category_id", "name_id", "unit_id", "color_id"):
            self.assertIsNone(snapshot[field])
        self.assertEqual(snapshot["entry_draft"]["sources"], typed_product_draft()["sources"])

    def test_reediting_without_new_selection_preserves_unlinked_draft(self):
        _, original = resolve_product_selection(None, {"draft": typed_product_draft()})
        product, snapshot = resolve_product_selection(None, None, existing_snapshot=original)
        self.assertIsNone(product)
        self.assertEqual(snapshot, original)
        self.assertIsNot(snapshot, original)
        snapshot["entry_draft"]["color_name"] = "修改"
        self.assertEqual(original["entry_draft"]["color_name"], "临时红色")

    def test_typed_color_material_on_existing_product_do_not_mutate_master(self):
        draft = self.selected_draft()
        draft.update(color_id=None, color_name="新颜色", material="新材质")
        draft["sources"].update(color_name="typed", material="typed")
        before = self.counts()
        product, snapshot = resolve_product_selection(self.product.pk, {
            "catalog_version": self.product.updated_at.isoformat(), "draft": draft,
        }, existing_snapshot={"catalog_id": str(self.product.pk), "thickness": "0.8"})
        self.assertEqual(product.pk, self.product.pk)
        self.assertEqual(snapshot["thickness"], "0.8")
        self.assertEqual(snapshot["color_name"], "新颜色")
        self.assertEqual(self.counts(), before)
        self.product.refresh_from_db()
        self.assertEqual(self.product.materials, ["铁"])

    def test_selected_identity_requires_valid_id_matching_text_and_parent(self):
        other_category = ProductCatalogCategory.objects.create(name="其他草稿类别")
        for changes in (
            {"name_id": str(uuid4())}, {"name": "不是所选品名"},
            {"category_id": str(other_category.pk), "category_name": other_category.name},
            {"item_number": "另一个货号"}, {"material": "伪造选中材质"}, {"color_id": str(uuid4())},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                draft = self.selected_draft()
                draft.update(changes)
                resolve_product_selection(self.product.pk, {"catalog_version": self.product.updated_at.isoformat(), "draft": draft})

    def test_typed_fields_cannot_carry_master_ids(self):
        for id_field in ("category_id", "name_id", "unit_id", "color_id"):
            with self.subTest(field=id_field), self.assertRaises(ValidationError):
                draft = typed_product_draft()
                draft[id_field] = str(uuid4())
                resolve_product_selection(None, {"draft": draft})

    def test_selected_item_requires_product_link_and_version(self):
        draft = typed_product_draft()
        draft["sources"]["item_number"] = "selected"
        with self.assertRaises(ValidationError):
            resolve_product_selection(None, {"draft": draft})
        with self.assertRaises(ValidationError):
            resolve_product_selection(self.product.pk, {"draft": self.selected_draft()})

    def test_missing_unit_can_remain_draft_without_fake_unit(self):
        _, snapshot = resolve_product_selection(None, {"draft": typed_product_draft(unit_name="")})
        self.assertIsNone(snapshot["unit_id"])
        self.assertEqual(snapshot["unit_code"], "")

    def test_source_fields_and_category_length_are_validated(self):
        for draft in (typed_product_draft(category_name="类" * 151), typed_product_draft()):
            if len(draft["category_name"]) < 151:
                draft["sources"].pop("material")
            serializer = ProductSelectionSerializer(data={"draft": draft})
            self.assertFalse(serializer.is_valid())
