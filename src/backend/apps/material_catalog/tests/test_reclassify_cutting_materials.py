from io import StringIO
from types import SimpleNamespace

from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TestCase

from apps.boms.catalog_selection import apply_catalog_selection, required_fields
from apps.boms.models import BomLine, BomSection
from apps.inventory.catalog_stock_identity import build_catalog_stock_identity
from apps.inventory.catalog_stock_queries import catalog_stock_summary
from apps.inventory.models import PublicStockBalance, PublicStockMovement
from apps.inventory.public_inventory_queries import public_raw_inventory_page
from apps.inventory.tests.test_public_stock_services import PublicStockFixture
from apps.material_catalog.models import MaterialAllowedUnit, MaterialAttributeValue, MaterialCatalog
from apps.material_catalog.snapshots import build_material_snapshot
from apps.procurement.services import _source_quantity, _supplier_category_suggestion
from apps.reference_data.models import ProductionUnit


class CuttingMaterialReclassificationTests(PublicStockFixture, TestCase):
    def test_existing_stock_and_new_fabric_bom_purchase_share_identity_after_reclassification(self):
        meter, _ = ProductionUnit.objects.get_or_create(unit_name="米", defaults={"unit_code": "TEST_METER"})
        mesh_piece = MaterialCatalog.objects.create(category_key="FABRIC_SEMI", template_key="FABRIC_SEMI", name="网布")
        generic = MaterialCatalog.objects.create(category_key="AUXILIARY", template_key="AUXILIARY_GENERAL", name="普通网布")
        archive = MaterialCatalog.objects.create(category_key="FABRIC", template_key="FABRIC", name="裁片")
        fabric = BomSection.objects.create(bom=self.bom_line.section.bom, title="面料类", section_type="FABRIC", line_number=702)
        self.user.user_permissions.add(Permission.objects.get(codename="view_materialcatalog"))
        request = SimpleNamespace(user=self.user, employee=self.employee, META={}, headers={})
        old_stock = []
        for name, template, attrs in (
            ("珍珠棉", "COTTON", {"material": "PE", "specification": "1.5", "thickness": "1.5", "color": "白色"}),
            ("网布", "AUXILIARY_GENERAL", {"material": "尼龙", "specification": "粗孔", "color": "黑色"}),
        ):
            item = MaterialCatalog.objects.create(category_key="AUXILIARY", template_key=template, name=name)
            MaterialAllowedUnit.objects.create(catalog=item, unit=meter, scope="BASE")
            for key, value in attrs.items():
                MaterialAttributeValue.objects.create(catalog=item, scope="BASE", field_key=key, value=value)
            saved = build_material_snapshot(catalog=item, scope="BASE", processing_state="RAW", attributes=attrs,
                                            unit_id=meter.pk, required_fields=required_fields(template, attrs))
            before = build_catalog_stock_identity(material_catalog_id=item.pk, material_selection_snapshot=saved)
            original = self.credit(3, identity=before)
            old_stock.append((item, attrs, before, original))
        call_command("reclassify_cutting_materials", "--dry-run", stdout=StringIO())
        self.assertFalse(MaterialCatalog.objects.filter(category_key="FABRIC", name="网布").exists())
        call_command("reclassify_cutting_materials", "--apply", stdout=StringIO())
        rerun = StringIO()
        call_command("reclassify_cutting_materials", "--apply", stdout=rerun)
        self.assertIn('"变更": []', rerun.getvalue())
        for item, attrs, before, original in old_stock:
            with self.subTest(item=item.name):
                item.refresh_from_db()
                line = BomLine(section=fabric, line_number=1)
                apply_catalog_selection(line, {"material_catalog_id": item.pk, "material_selection": {
                    "catalog_version": item.updated_at.isoformat(), "scope": "BASE", "processing_state": "RAW",
                    "attributes": attrs, "unit_id": str(meter.pk),
                }}, old=None, request=request, persist=False, versions={}, require_catalog_options=True, require_fabric_meter=True)
                after = build_catalog_stock_identity(material_catalog_id=item.pk, material_selection_snapshot=line.material_selection_snapshot)
                self.assertEqual(before["identity_key"], after["identity_key"])
                self.assertEqual(line.unit, "米")
                line.total_purchase_quantity = "25"
                self.assertEqual(_source_quantity(line, fabric.bom)[0], 25)
                self.assertEqual(_supplier_category_suggestion(line)[0], "FABRIC")
                source = self.source()
                receipt = self.credit(2, identity=after, **source)
                self.assertEqual(original.balance_id, receipt.balance_id)
                self.assertEqual(self.credit(2, identity=after, **source).pk, receipt.pk)
                balance = PublicStockBalance.objects.get(pk=receipt.balance_id)
                self.assertEqual(balance.quantity, 5)
                self.assertEqual(balance.identity_snapshot["material_selection_snapshot"]["category_key"], "AUXILIARY")
                self.assertEqual(catalog_stock_summary(balance)["category"], "面料")
                count, rows = public_raw_inventory_page(page=1, page_size=10, keyword=item.name, bom_section="FABRIC")
                self.assertEqual(count, 1)
                self.assertEqual(rows[0]["raw_material__category__category_name"], "面料类")
                old_count, _ = public_raw_inventory_page(page=1, page_size=10, keyword=item.name, bom_section="AUXILIARY")
                self.assertEqual(old_count, 0)
        self.assertEqual(PublicStockMovement.objects.count(), 4)
        self.assertTrue(MaterialCatalog.objects.filter(pk=archive.pk, archived_at__isnull=False).exists())
        self.assertTrue(MaterialCatalog.objects.filter(category_key="FABRIC_SEMI", name="珍珠棉片", archived_at=None).exists())
        self.assertTrue(MaterialCatalog.objects.filter(pk=mesh_piece.pk, archived_at=None).exists())
        self.assertTrue(MaterialCatalog.objects.filter(pk=generic.pk, category_key="AUXILIARY", archived_at=None).exists())
