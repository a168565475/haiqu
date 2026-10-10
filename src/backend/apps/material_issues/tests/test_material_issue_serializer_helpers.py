from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.material_issues.api.serializers import _semi_material


class SemiMaterialDisplayTests(SimpleTestCase):
    def test_public_identity_material_has_priority(self):
        line = SimpleNamespace(conversion_snapshot={
            "public_identity": {"identity_snapshot": {"material": "铁-中光"}},
        })
        source = SimpleNamespace(
            identity_snapshot={"material": "旧材质"},
            bom_line=SimpleNamespace(material="BOM材质"),
        )

        self.assertEqual(_semi_material(line, source), "铁-中光")

    def test_legacy_balance_falls_back_to_bom_material(self):
        line = SimpleNamespace(conversion_snapshot={})
        source = SimpleNamespace(identity_snapshot={}, bom_line=SimpleNamespace(material="涤纶"))

        self.assertEqual(_semi_material(line, source), "涤纶")
