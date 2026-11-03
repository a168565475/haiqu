from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.boms.api.views import BomViewSet
from apps.boms.models import Bom


class CatalogCategoryFilterTests(SimpleTestCase):
    """仅检查查询构造，不替代数据库/API 业务验收。"""

    category_id = "ABCDEFAB-1234-4321-ABCD-ABCDEFABCDEF"

    def build_query(self, params):
        view = BomViewSet()
        view.request = Request(APIRequestFactory().get("/api/v1/boms/", params))
        with patch("apps.boms.api.views.accessible_boms", return_value=Bom.objects.all()):
            return view._filtered_queryset().query.sql_with_params()

    def test_catalog_category_uses_frozen_snapshot_and_normalizes_uuid(self):
        sql, params = self.build_query({"product_catalog_category_id": self.category_id})
        self.assertIn('"bom"."product_catalog_id" IS NOT NULL', sql)
        self.assertIn('"bom"."product_selection_snapshot" ->', sql)
        self.assertNotIn('JOIN "product_catalog', sql)
        self.assertIn("category_id", params)
        self.assertIn(self.category_id.lower(), [getattr(value, "obj", value) for value in params])

    def test_legacy_category_keeps_existing_foreign_key_filter(self):
        sql, params = self.build_query({"product_category_id": self.category_id})
        self.assertIn('"bom"."product_category_id" =', sql)
        self.assertIn(UUID(self.category_id), params)
        self.assertNotIn('"bom"."product_selection_snapshot" ->', sql)

    def test_invalid_or_ambiguous_categories_are_rejected(self):
        for params in (
            {"product_catalog_category_id": "invalid"},
            {"product_category_id": self.category_id, "product_catalog_category_id": self.category_id},
        ):
            with self.subTest(params=params), self.assertRaises(ValidationError):
                self.build_query(params)
