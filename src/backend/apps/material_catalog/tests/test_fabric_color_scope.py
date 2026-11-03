from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from apps.material_catalog.colors import uses_product_color_identity
from apps.material_catalog.editing import _plan_values
from apps.material_catalog.models import MaterialCatalog
from apps.material_catalog.public_configuration import (
    ACTIVE, context, ensure_public_draft, ensure_public_value, public_options, require_public_value,
)
from apps.material_catalog.selectors import catalog_detail
from apps.material_catalog import services
from apps.reference_data.models import ProductColor


class FabricColorScopeTests(SimpleTestCase):
    def setUp(self):
        self.colors = [SimpleNamespace(pk=uuid4(), color_card=card, color_code="01", color_name="同名红")
                       for card in ("卡A", "卡B")]

    def test_public_options_only_fabric_exposes_distinct_color_identities(self):
        cases = (("FABRIC", "FABRIC", "BASE", 2), ("TUBE", "TUBE", "BASE", 1),
                 ("HARDWARE", "HARDWARE", "BASE", 1), ("PLASTIC", "PLASTIC", "BASE", 1),
                 ("PACKAGING", "CARTON", "BASE", 1), ("FABRIC_SEMI", "FABRIC_SEMI", "BASE", 1),
                 ("TUBE", "TUBE", "SPRAY", 1))
        for category, template, scope, expected in cases:
            with self.subTest(category=category, scope=scope):
                queryset = MagicMock()
                queryset.filter.return_value = self.colors
                with patch("apps.material_catalog.public_configuration.fields_for", return_value=[{"key": "color", "source": "product-colors"}]), \
                     patch("apps.material_catalog.public_configuration.source_queryset", return_value=(queryset, "color_name")), \
                     patch("apps.material_catalog.public_configuration.ProductionUnit.objects.filter", return_value=[]):
                    values = public_options(category, template, scope)["values"]
                self.assertEqual(len(values), expected)
                self.assertEqual("product_color_id" in values[0], category == "FABRIC")
                self.assertEqual(uses_product_color_identity(context(category, template, scope), scope), category == "FABRIC")

    def test_nonfabric_require_and_ensure_match_color_name_without_empty_card_filter(self):
        for category, template in (("TUBE", "TUBE"), ("HARDWARE", "HARDWARE"), ("FABRIC_SEMI", "FABRIC_SEMI")):
            with self.subTest(category=category):
                catalog = context(category, template)
                queryset = MagicMock(model=ProductColor)
                queryset.filter.return_value.first.return_value = self.colors[0]
                with patch("apps.material_catalog.public_configuration.source_queryset", return_value=(queryset, "color_name")), \
                     patch("apps.material_catalog.public_configuration._resolve_product_color") as resolve:
                    self.assertIs(require_public_value.__wrapped__(catalog, "BASE", "color", "同名红"), self.colors[0])
                    queryset.filter.assert_called_once_with(color_name="同名红", **ACTIVE)
                    with patch("apps.material_catalog.public_configuration._ensure", return_value=self.colors[0]) as ensure:
                        self.assertIs(ensure_public_value.__wrapped__(catalog, "BASE", "color", "同名红", persist=False), self.colors[0])
                        self.assertEqual(ensure.call_args.args, (ProductColor, {"color_name": "同名红"}))
                        self.assertEqual(ensure.call_args.kwargs["defaults"], {"color_card": "", "color_code": ""})
                    resolve.assert_not_called()

    def test_full_draft_only_binds_fabric_color_and_other_categories_keep_text_values(self):
        for category in ("FABRIC", "TUBE", "HARDWARE", "FABRIC_SEMI"):
            with self.subTest(category=category):
                catalog = MaterialCatalog(category_key=category, template_key=category, name="测试品名")
                row = {"id": uuid4(), "scope": "BASE", "field_key": "color", "value": "同名红", "parent_id": None}
                with patch.object(type(catalog.attribute_values), "select_related", return_value=[]), \
                     patch.object(type(catalog.allowed_units), "filter") as units, \
                     patch("apps.material_catalog.public_configuration.ensure_public_value", return_value=self.colors[0]):
                    units.return_value.select_related.return_value = []
                    ensure_public_draft(catalog, {"values": [row], "units": []}, request=None)
                option, _, color_id = _plan_values(catalog, [row], {})[0]
                self.assertEqual(color_id, self.colors[0].pk if category == "FABRIC" else None)
                self.assertEqual(option.product_color_id, color_id)

    def test_single_value_service_does_not_bind_nonfabric_public_color(self):
        for category in ("FABRIC", "TUBE"):
            with self.subTest(category=category):
                catalog = MaterialCatalog(category_key=category, template_key=category, name="测试品名")
                with patch("apps.material_catalog.services._locked_catalog", return_value=catalog), \
                     patch("apps.material_catalog.services.catalog_detail", return_value={}), \
                     patch("apps.material_catalog.services.ensure_public_value", return_value=self.colors[0]), \
                     patch("apps.material_catalog.services.MaterialAttributeValue.objects.filter") as lookup, \
                     patch("apps.material_catalog.services.MaterialAttributeValue.objects.create") as create, \
                     patch("apps.material_catalog.services._finish_change"):
                    lookup.return_value.first.return_value = None
                    services.add_value.__wrapped__(catalog_id=catalog.pk, request=None,
                        data={"scope": "BASE", "field_key": "color", "value": "同名红"})
                self.assertEqual(create.call_args.kwargs.get("product_color_id"), self.colors[0].pk if category == "FABRIC" else None)

    def test_detail_only_fabric_emits_color_metadata(self):
        row = SimpleNamespace(pk=uuid4(), scope="BASE", field_key="color", value="同名红", parent_id=None,
                              product_color_id=None)
        for category in ("FABRIC", "TUBE", "HARDWARE", "FABRIC_SEMI"):
            with self.subTest(category=category):
                attributes, units = MagicMock(), MagicMock()
                attributes.filter.return_value.select_related.return_value = [row]
                units.filter.return_value.select_related.return_value = []
                catalog = SimpleNamespace(category_key=category, base_warehouse_id=None, semi_warehouse_id=None,
                                          attribute_values=attributes, allowed_units=units)
                with patch("apps.material_catalog.selectors.catalog_summary", return_value={}):
                    detail = catalog_detail(catalog)["values"][0]
                self.assertEqual(detail["value"], row.value)
                self.assertEqual("color_card" in detail, category == "FABRIC")
