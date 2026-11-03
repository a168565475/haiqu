from copy import deepcopy
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.material_catalog.models import MaterialCatalog, MaterialAttributeValue
from apps.material_catalog.public_configuration import public_options, require_public_value
from apps.organizations.models import Employee
from apps.reference_data.models import (
    AccessoryProductName, AccessorySpecification, MaterialAttributePublicValue,
    ProductionUnit, TubeCoatingColor, TubeDiameter, TubeShape, TubeShapeDimension,
)
from apps.boms.catalog_selection import apply_catalog_selection
from apps.boms.material_save_plan import build_material_save_plan
from apps.boms.models import Bom, BomLine, BomSection


class CatalogExistingPublicOnlyTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="select_only_admin", password="SelectOnlyTest123!", email="")
        employee = Employee.objects.create(user=self.admin, employee_code="SELECT_ONLY_ADMIN", display_name="只选配置测试")
        self.request = SimpleNamespace(user=self.admin, employee=employee, META={}, headers={}, data={})
        self.catalog = MaterialCatalog.objects.create(category_key="HARDWARE", template_key="HARDWARE", name="只选公共五金", spray_enabled=True)
        self.unit = ProductionUnit.objects.create(unit_code="SELECT-ONLY", unit_name="只选公共单位")
        self.public = MaterialAttributePublicValue.objects.create(category_key="HARDWARE", template_key="HARDWARE", scope="BASE", field_key="specification", value="只选已有规格")
        self.bom = Bom(order_quantity=10)

    def data(self, **changes):
        self.catalog.refresh_from_db()
        selection = {"scope": "BASE", "catalog_version": self.catalog.updated_at.isoformat(), "processing_state": "RAW",
                     "attributes": {"specification": self.public.value}, "unit_id": str(self.unit.pk)}
        selection.update(changes)
        return {"material_catalog_id": str(self.catalog.pk), "material_selection": selection}

    def line(self):
        return BomLine(section=BomSection(bom=self.bom, title="五金件", section_type="ACCESSORY"), line_number=1, raw_values={})

    def plan(self, data, *, persist=False, request=None):
        with transaction.atomic():
            return build_material_save_plan(bom=self.bom,
                sections=[{"title": "五金件", "section_type": "ACCESSORY", "lines": [data]}],
                request=request or self.request, for_update=persist)

    def counts(self):
        return (MaterialAttributePublicValue.objects.count(), ProductionUnit.objects.count(),
                self.catalog.attribute_values.count(), self.catalog.allowed_units.count(), AuditLog.objects.count())

    def test_bom_entry_rejects_new_or_catalog_only_values_even_for_admin_and_forged_flag(self):
        MaterialAttributeValue.objects.create(catalog=self.catalog, scope="BASE", field_key="specification", value="仅品名已有规格")
        before = self.counts()
        for value in ("BOM禁止补录的新规格", "仅品名已有规格"):
            for persist in (False, True):
                with self.subTest(value=value, persist=persist):
                    data = self.data(attributes={"specification": value})
                    data["allow_public_creation"] = True
                    with self.assertRaisesMessage(ValidationError, "生产维护"):
                        self.plan(data, persist=persist)
                    self.assertEqual(self.counts(), before)

    def test_existing_public_values_record_usage_without_maintenance_permission_and_preserve_history(self):
        user = get_user_model().objects.create_user(username="select_only_editor")
        employee = Employee.objects.create(user=user, employee_code="SELECT_ONLY_EDITOR", display_name="只选配置编辑员")
        for app, code in (("material_catalog", "view_materialcatalog"), ("boms", "change_bom")):
            user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=code))
        request = SimpleNamespace(user=user, employee=employee, META={}, headers={}, data={})
        self.assertFalse(user.has_perm("material_catalog.change_materialcatalog"))
        before_public = MaterialAttributePublicValue.objects.count()
        plan = self.plan(self.data(), persist=True, request=request)
        old = plan["lines"][(0, 1)]
        self.assertTrue(self.catalog.attribute_values.filter(value=self.public.value).exists())
        self.assertTrue(self.catalog.allowed_units.filter(unit=self.unit).exists())
        self.assertEqual(MaterialAttributePublicValue.objects.count(), before_public)
        before_snapshot = deepcopy(old.material_selection_snapshot)
        self.public.status = "INACTIVE"
        self.public.save(update_fields=["status", "updated_at"])
        self.unit.status = "INACTIVE"
        self.unit.save(update_fields=["status", "updated_at"])
        line = self.line()
        apply_catalog_selection(line, {"material_catalog_id": str(self.catalog.pk)}, old=old, request=None,
                                persist=True, versions={}, allow_public_creation=False)
        self.assertEqual(line.material_selection_snapshot, before_snapshot)
        with self.assertRaises(ValidationError):
            self.plan(self.data(), persist=True, request=request)

    def test_new_inactive_units_and_flow_unit_fail_without_partial_usage_or_audit(self):
        inactive = ProductionUnit.objects.create(unit_code="SELECT-OFF", unit_name="只选停用单位", status="INACTIVE")
        inputs = [self.data(unit_id=None, unit_name="BOM不能创建的新单位"), self.data(unit_id=str(inactive.pk)),
                  self.data(attributes={"specification": self.public.value, "flow_unit": "BOM不能创建的流转单位"})]
        before = self.counts()
        for data in inputs:
            with self.subTest(selection=data["material_selection"]):
                with self.assertRaises(ValidationError):
                    self.plan(data, persist=True)
                self.assertEqual(self.counts(), before)

    def test_spray_color_must_already_be_active_and_records_usage_only(self):
        before = self.counts()
        color = TubeCoatingColor.objects.create(color_name="只选喷塑颜色", status="INACTIVE")
        for value in ("BOM不能创建的新喷塑色", color.color_name):
            data = {**self.data(), "powder_coating_color": value}
            with self.assertRaisesMessage(ValidationError, "生产维护"):
                self.plan(data, persist=True)
            self.assertEqual(self.counts(), before)
        color.status = "ACTIVE"
        color.save(update_fields=["status", "updated_at"])
        colors_before = TubeCoatingColor.objects.count()
        self.plan({**self.data(), "powder_coating_color": color.color_name}, persist=True)
        self.assertTrue(self.catalog.attribute_values.filter(scope="SPRAY", field_key="color", value=color.color_name).exists())
        self.assertEqual(TubeCoatingColor.objects.count(), colors_before)

    def test_shape_dimension_matches_public_candidates_without_creating_relations(self):
        catalog = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="只选关系管材")
        shape = TubeShape.objects.create(shape_name="只选形状甲")
        other = TubeShape.objects.create(shape_name="只选形状乙")
        bound = TubeDiameter.objects.create(diameter_value="只选绑定尺寸")
        unbound = TubeDiameter.objects.create(diameter_value="只选通用尺寸")
        relation = TubeShapeDimension.objects.create(shape=shape, diameter=bound)
        before = TubeShapeDimension.objects.count()
        self.assertEqual(require_public_value(catalog, "BASE", "section_size", bound.diameter_value, parent_value=shape.shape_name, lock=True).pk, relation.pk)
        with self.assertRaises(ValidationError):
            require_public_value(catalog, "BASE", "section_size", bound.diameter_value, parent_value=other.shape_name)
        self.assertEqual(require_public_value(catalog, "BASE", "section_size", unbound.diameter_value, parent_value=other.shape_name, lock=True).pk, unbound.pk)
        relation.status = "INACTIVE"
        relation.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError):
            require_public_value(catalog, "BASE", "section_size", bound.diameter_value, parent_value=shape.shape_name)
        options = public_options("TUBE", "TUBE", "BASE")["values"]
        self.assertIn((unbound.diameter_value, str(other.pk)), {(row["value"], row["parent_id"]) for row in options})
        self.assertNotIn(bound.diameter_value, [row["value"] for row in options])
        self.assertEqual(TubeShapeDimension.objects.count(), before)

    def test_derived_weight_remains_selectable_but_explicit_archive_masks_it(self):
        catalog = MaterialCatalog.objects.create(category_key="AUXILIARY", template_key="COTTON", name="只选克重辅料")
        product = AccessoryProductName.objects.create(product_name="只选克重原分组", unit_name="米")
        spec = AccessorySpecification.objects.create(product_name=product, specification_value="只选克重旧规格", weight=" 只选派生克重 ")
        before = MaterialAttributePublicValue.objects.count()
        self.assertEqual(require_public_value(catalog, "BASE", "gram_weight", "只选派生克重", lock=True).pk, spec.pk)
        self.assertEqual(MaterialAttributePublicValue.objects.count(), before)
        MaterialAttributePublicValue.objects.create(category_key="AUXILIARY", template_key="COTTON", scope="BASE", field_key="gram_weight", value="只选派生克重", archived_at=timezone.now())
        with self.assertRaises(ValidationError):
            require_public_value(catalog, "BASE", "gram_weight", "只选派生克重")

    def test_shared_non_bom_callers_keep_existing_creation_policy(self):
        data = self.data(attributes={"specification": "其他调用仍可补公共规格"})
        with transaction.atomic():
            apply_catalog_selection(self.line(), data, old=None, request=self.request, persist=True, versions={})
        self.assertTrue(MaterialAttributePublicValue.objects.filter(category_key="HARDWARE", field_key="specification", value="其他调用仍可补公共规格").exists())
