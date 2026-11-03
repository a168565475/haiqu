from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.boms.catalog_selection import apply_catalog_selection


class FabricCatalogUnitTests(SimpleTestCase):
    def preview(self, unit_name, *, title="面料类", policy=None):
        category, template, attrs = {
            "面料类": ("FABRIC", "FABRIC", {"material": "涤纶", "fabric_spec": "600D", "width": "150", "color": "红"}),
            "辅料类": ("AUXILIARY", "AUXILIARY_GENERAL", {"specification": "20"}),
            "裁剪明细": ("FABRIC_SEMI", "FABRIC_SEMI", {"size": "20x30"}),
        }[title]
        catalog_id, unit_id = uuid4(), uuid4()
        version = datetime(2026, 10, 31, tzinfo=timezone.utc)
        catalog = SimpleNamespace(pk=catalog_id, category_key=category, template_key=template, name="测试品名",
            updated_at=version, spray_enabled=False, allowed_units=SimpleNamespace(filter=lambda **kwargs:
                SimpleNamespace(first=lambda: SimpleNamespace(archived_at=None))))
        unit = SimpleNamespace(pk=unit_id, unit_name=unit_name, status="ACTIVE", archived_at=None)
        color = SimpleNamespace(pk=uuid4(), color_card="", color_code="", color_name="红")
        line = SimpleNamespace(section=SimpleNamespace(title=title, section_type="FABRIC"), raw_values={})
        data = {"material_catalog_id": str(catalog_id), "material_selection": {"catalog_version": version.isoformat(),
            "scope": "BASE", "processing_state": "RAW", "attributes": attrs, "unit_id": str(unit_id)}}
        request = SimpleNamespace(user=SimpleNamespace(has_perm=lambda permission: True))
        with patch("apps.boms.catalog_selection.MaterialCatalog.objects.filter") as catalogs, \
             patch("apps.boms.catalog_selection.MaterialAttributeValue.objects.filter") as values, \
             patch("apps.boms.catalog_selection.ProductionUnit.objects.filter") as units, \
             patch("apps.boms.catalog_selection.ensure_public_value", return_value=color), \
             patch("apps.boms.catalog_selection.require_public_value", return_value=color), \
             patch("apps.boms.catalog_selection._craft_input", return_value=(None, None)):
            catalogs.return_value.first.return_value = catalog
            values.return_value.first.return_value = SimpleNamespace(archived_at=None)
            units.return_value.first.return_value = unit
            flags = {"require_fabric_meter": policy, "allow_public_creation": False} if policy is not None else {}
            apply_catalog_selection(line, data, old=None, request=request, persist=False, versions={}, **flags)
        return line

    def test_formal_bom_new_fabric_selection_requires_meter(self):
        self.assertEqual(self.preview("米", policy=True).unit, "米")
        for unit_name in ("码", "个", "公斤"):
            with self.subTest(unit=unit_name), self.assertRaisesMessage(ValidationError, "固定为米"):
                self.preview(unit_name, policy=True)

    def test_shared_sample_and_manual_call_default_remains_unrestricted(self):
        self.assertEqual(self.preview("码").unit, "码")

    def test_fabric_section_type_does_not_restrict_accessory_or_cutting_titles(self):
        for title in ("辅料类", "裁剪明细"):
            with self.subTest(title=title):
                self.assertEqual(self.preview("个", title=title, policy=True).unit, "个")

    def test_unchanged_history_keeps_original_unit_and_snapshot(self):
        catalog_id = uuid4()
        snapshot = {"catalog_id": str(catalog_id), "category_key": "FABRIC", "name": "历史面料",
                    "attributes": {"material": "涤纶", "fabric_spec": "600D", "width": "150", "color": "红"},
                    "unit_name": "码", "unit_id": str(uuid4()), "scope": "BASE", "processing_state": "RAW",
                    "completed_craft": None, "semi_kind": None}
        old = SimpleNamespace(material_catalog_id=catalog_id, material_selection_snapshot=deepcopy(snapshot),
                              material_quantity=None, raw_values={})
        line = SimpleNamespace(section=SimpleNamespace(title="面料类", section_type="FABRIC"), raw_values={})
        with patch("apps.boms.catalog_selection.MaterialCatalog.objects.filter") as catalogs:
            apply_catalog_selection(line, {"material_catalog_id": str(catalog_id)}, old=old, request=None,
                                    persist=False, versions={}, allow_public_creation=False, require_fabric_meter=True)
            catalogs.assert_not_called()
        self.assertEqual(line.unit, "码")
        self.assertEqual(line.material_selection_snapshot, snapshot)
