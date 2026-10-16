import importlib
import importlib.util
import json
from copy import deepcopy
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductionUnit

from ..models import MaterialAllowedUnit, MaterialAttributeValue, MaterialCatalog


class MaterialCatalogImportTests(TestCase):
    def setUp(self):
        self.unit = ProductionUnit.objects.create(unit_code="IMPORT_BAR", unit_name="导入测试根")
        self.second_unit = ProductionUnit.objects.create(unit_code="IMPORT_METER", unit_name="导入测试米")
        self.payload = {
            "version": 1,
            "source": {"filename": "原料信息.xlsx", "sha256": "a" * 64},
            "catalogs": [{
                "category_key": "TUBE", "template_key": "TUBE", "name": "导入铁管",
                "spray_enabled": True,
                "values": [
                    {"scope": "BASE", "field_key": "material", "value": "Q235"},
                    {"scope": "BASE", "field_key": "section_size", "value": "20×20", "parent_value": "方管"},
                    {"scope": "BASE", "field_key": "shape", "value": "方管"},
                    {"scope": "SPRAY", "field_key": "color", "value": "黑色"},
                ],
                "units": [
                    {"scope": "BASE", "unit_name": self.unit.unit_name},
                    {"scope": "BASE", "unit_name": self.second_unit.unit_name},
                    {"scope": "SPRAY", "unit_name": self.second_unit.unit_name},
                ],
            }],
        }

    def importer(self):
        module = "apps.material_catalog.importing"
        self.assertIsNotNone(importlib.util.find_spec(module), "尚未实现原料导入执行层")
        return importlib.import_module(module)

    def run_import(self, payload=None, **kwargs):
        return self.importer().import_catalog_payload(payload or self.payload, **kwargs)

    def counts(self):
        return tuple(model.objects.count() for model in (
            MaterialCatalog, MaterialAttributeValue, MaterialAllowedUnit, AuditLog, ProductionUnit,
        ))

    def test_flow_unit_import_stays_separate_from_allowed_units_and_is_idempotent(self):
        payload = deepcopy(self.payload)
        payload["catalogs"] = [{
            "name": "导入五金", "category_key": "HARDWARE", "template_key": "HARDWARE",
            "spray_enabled": False,
            "values": [{"scope": "BASE", "field_key": "flow_unit", "value": "KG"}],
            "units": [{"scope": "BASE", "unit_name": self.unit.unit_name}],
        }]
        before = self.counts()
        preview = self.run_import(payload)
        self.assertEqual(self.counts(), before)
        self.assertEqual(preview["values_created"], 2)
        self.assertEqual(preview["units_created"], 1)
        self.run_import(payload, apply=True)
        catalog = MaterialCatalog.objects.get(name="导入五金")
        self.assertEqual(catalog.attribute_values.get(field_key="flow_unit").value, "KG")
        self.assertEqual(list(catalog.allowed_units.values_list("unit_id", flat=True)), [self.unit.pk])
        before_repeat = self.counts()
        result = self.run_import(payload, apply=True)
        self.assertEqual(self.counts(), before_repeat)
        self.assertEqual(result["catalogs_unchanged"], 1)
        self.assertEqual((result["values_created"], result["units_created"]), (0, 0))

    def test_packaging_box_shapes_import_once_without_generating_combinations(self):
        payload = deepcopy(self.payload)
        payload["catalogs"] = [{
            "name": f"箱子形状-{template}", "category_key": "PACKAGING", "template_key": template,
            "spray_enabled": False,
            "values": [
                {"scope": "BASE", "field_key": "box_type", "value": "半盖"},
                {"scope": "BASE", "field_key": "box_type", "value": "天地盖"},
                {"scope": "BASE", "field_key": size_field, "value": "95*65"},
            ],
            "units": [{"scope": "BASE", "unit_name": self.unit.unit_name}],
        } for template, size_field in (("CARTON", "size"), ("BAG", "size"), ("PACKAGING_GENERAL", "specification"))]
        before = self.counts()
        preview = self.run_import(payload)
        self.assertEqual(self.counts(), before)
        self.assertEqual((preview["catalogs_created"], preview["values_created"], preview["units_created"]), (3, 12, 3))
        self.run_import(payload, apply=True)
        self.assertEqual(MaterialCatalog.objects.count(), 3)
        for catalog in MaterialCatalog.objects.all():
            self.assertEqual(set(catalog.attribute_values.filter(field_key="box_type").values_list("value", flat=True)), {"半盖", "天地盖"})
            self.assertEqual(catalog.attribute_values.count(), 4)
        before_repeat = self.counts()
        result = self.run_import(payload, apply=True)
        self.assertEqual(self.counts(), before_repeat)
        self.assertEqual((result["catalogs_unchanged"], result["values_created"], result["units_created"]), (3, 0, 0))

    def test_packaging_models_import_as_independent_values_and_are_idempotent(self):
        payload = deepcopy(self.payload)
        payload["catalogs"] = [{
            "name": f"型号-{template}", "category_key": "PACKAGING", "template_key": template,
            "spray_enabled": False,
            "values": [
                {"scope": "BASE", "field_key": "model", "value": "2.5MM"},
                {"scope": "BASE", "field_key": "model", "value": "10.1*7.6"},
                {"scope": "BASE", "field_key": size_field, "value": "78*65"},
            ],
            "units": [{"scope": "BASE", "unit_name": self.unit.unit_name}],
        } for template, size_field in (("CARTON", "size"), ("BAG", "size"), ("PACKAGING_GENERAL", "specification"))]
        before = self.counts()
        preview = self.run_import(payload)
        self.assertEqual(self.counts(), before)
        self.assertEqual((preview["catalogs_created"], preview["values_created"], preview["units_created"]), (3, 12, 3))
        self.run_import(payload, apply=True)
        self.assertEqual(MaterialCatalog.objects.count(), 3)
        for catalog in MaterialCatalog.objects.all():
            self.assertEqual(set(catalog.attribute_values.filter(field_key="model").values_list("value", flat=True)), {"2.5MM", "10.1*7.6"})
            self.assertEqual(catalog.attribute_values.count(), 4)
            self.assertEqual(list(catalog.allowed_units.values_list("unit_id", flat=True)), [self.unit.pk])
        before_repeat = self.counts()
        result = self.run_import(payload, apply=True)
        self.assertEqual(self.counts(), before_repeat)
        self.assertEqual((result["catalogs_unchanged"], result["values_created"], result["units_created"]), (3, 0, 0))

    def test_fabric_semi_width_import_preserves_text_and_is_idempotent(self):
        payload = deepcopy(self.payload)
        payload["catalogs"] = [{
            "name": "导入椅面", "category_key": "FABRIC_SEMI", "template_key": "FABRIC_SEMI",
            "spray_enabled": False,
            "values": [
                {"scope": "BASE", "field_key": "width", "value": "1.5"},
                {"scope": "BASE", "field_key": "width", "value": "1.50"},
                {"scope": "BASE", "field_key": "specification", "value": "103*60/49*80/29"},
            ],
            "units": [{"scope": "BASE", "unit_name": self.unit.unit_name}],
        }]
        before = self.counts()
        preview = self.run_import(payload)
        self.assertEqual(self.counts(), before)
        self.assertEqual((preview["catalogs_created"], preview["values_created"], preview["units_created"]), (1, 4, 1))
        self.run_import(payload, apply=True)
        catalog = MaterialCatalog.objects.get(name="导入椅面")
        self.assertEqual(set(catalog.attribute_values.filter(field_key="width").values_list("value", flat=True)), {"1.5", "1.50"})
        self.assertEqual(catalog.attribute_values.get(field_key="specification").value, "103*60/49*80/29")
        self.assertEqual(list(catalog.allowed_units.values_list("unit_id", flat=True)), [self.unit.pk])
        before_repeat = self.counts()
        result = self.run_import(payload, apply=True)
        self.assertEqual(self.counts(), before_repeat)
        self.assertEqual((result["catalogs_unchanged"], result["values_created"], result["units_created"]), (1, 0, 0))

    def test_default_dry_run_validates_and_writes_nothing(self):
        before = self.counts()
        result = self.run_import()
        self.assertEqual(self.counts(), before)
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(result["catalogs_created"], 1)
        self.assertEqual(result["units_created"], 3)

    def test_apply_groups_spray_shapes_and_units_under_one_catalog(self):
        before_legacy = list(RawMaterialInformation.objects.values_list("id", "updated_at"))
        result = self.run_import(apply=True)
        catalog = MaterialCatalog.objects.get(name="导入铁管")
        self.assertTrue(catalog.spray_enabled)
        self.assertEqual(MaterialCatalog.objects.count(), 1)
        dimension = catalog.attribute_values.get(field_key="section_size")
        self.assertEqual(dimension.parent.value, "方管")
        self.assertEqual(dimension.parent.catalog_id, catalog.pk)
        self.assertEqual(catalog.allowed_units.count(), 3)
        self.assertEqual(catalog.attribute_values.filter(value="无颜色").count(), 2)
        self.assertEqual(result["values_created"], 6)
        self.assertEqual(before_legacy, list(RawMaterialInformation.objects.values_list("id", "updated_at")))
        audit = AuditLog.objects.get(object_type="MATERIAL_CATALOG", object_id=catalog.pk)
        self.assertEqual(audit.action, "IMPORTED")
        self.assertIsNone(audit.actor_employee_id)
        self.assertEqual(audit.after_data["import_source"], self.payload["source"])
        self.assertEqual(audit.after_data["import_method"], "AUTHORIZED_MANAGEMENT_COMMAND")

    def test_repeated_apply_is_idempotent_and_does_not_change_version_or_audit(self):
        self.run_import(apply=True)
        before = self.counts()
        version = MaterialCatalog.objects.get().updated_at
        result = self.run_import(apply=True)
        self.assertEqual(self.counts(), before)
        self.assertEqual(MaterialCatalog.objects.get().updated_at, version)
        self.assertEqual(result["catalogs_changed"], 0)
        self.assertEqual(result["catalogs_unchanged"], 1)

    def test_generic_templates_import_multiple_values_without_touching_legacy_and_are_idempotent(self):
        before_legacy = list(RawMaterialInformation.objects.order_by("id").values_list("id", "updated_at"))
        payload = deepcopy(self.payload)
        payload["catalogs"] = [{
            "name": "通用品名", "category_key": category, "template_key": template,
            "spray_enabled": False,
            "values": [
                {"scope": "BASE", "field_key": "material", "value": "通用材质"},
                {"scope": "BASE", "field_key": "color", "value": "白色"},
                {"scope": "BASE", "field_key": "specification", "value": "10×20"},
                {"scope": "BASE", "field_key": "specification", "value": "30×40"},
            ],
            "units": [
                {"scope": "BASE", "unit_name": self.unit.unit_name},
                {"scope": "BASE", "unit_name": self.second_unit.unit_name},
            ],
        } for category, template in (
            ("PACKAGING", "PACKAGING_GENERAL"),
            ("AUXILIARY", "AUXILIARY_GENERAL"),
        )]
        preview = self.run_import(payload)
        self.assertEqual(preview["catalogs_created"], 2)
        result = self.run_import(payload, apply=True)
        self.assertEqual(result["catalogs_created"], 2)
        self.assertEqual(result["values_created"], 10)
        self.assertEqual(result["units_created"], 4)
        for catalog in MaterialCatalog.objects.all():
            self.assertFalse(catalog.spray_enabled)
            self.assertEqual(set(catalog.attribute_values.values_list("field_key", flat=True)), {"material", "color", "specification"})
            self.assertEqual(catalog.attribute_values.filter(field_key="specification").count(), 2)
        before_repeat = self.counts()
        self.assertEqual(self.run_import(payload, apply=True)["catalogs_unchanged"], 2)
        self.assertEqual(self.counts(), before_repeat)
        self.assertEqual(before_legacy, list(RawMaterialInformation.objects.order_by("id").values_list("id", "updated_at")))

    def test_duplicate_input_catalogs_and_options_are_merged(self):
        payload = deepcopy(self.payload)
        payload["catalogs"].append(deepcopy(payload["catalogs"][0]))
        payload["catalogs"][1]["values"].append({"scope": "BASE", "field_key": "thickness", "value": "0.8"})
        result = self.run_import(payload, apply=True)
        self.assertEqual(result["catalogs_total"], 1)
        self.assertEqual(MaterialCatalog.objects.count(), 1)
        self.assertEqual(MaterialAttributeValue.objects.filter(field_key="material").count(), 1)
        self.assertTrue(MaterialAttributeValue.objects.filter(field_key="thickness", value="0.8").exists())

    def test_confirmed_templates_import_verbatim_specifications_as_independent_values(self):
        payload = deepcopy(self.payload)
        payload["catalogs"] = [{
            "name": f"{template}规格原文", "category_key": category, "template_key": template,
            "spray_enabled": False,
            "values": [
                {"scope": "BASE", "field_key": "specification", "value": "Φ20×30 / 厚0.8；A型"},
                {"scope": "BASE", "field_key": "specification", "value": "30×40×2（含接头）\n按图加工"},
                {"scope": "BASE", "field_key": "material", "value": "材质甲"},
                {"scope": "BASE", "field_key": "material", "value": "材质乙"},
            ],
            "units": [],
        } for category, template in (
            ("PLASTIC", "PLASTIC"), ("FABRIC_SEMI", "FABRIC_SEMI"),
            ("AUXILIARY", "TAPE"), ("AUXILIARY", "COTTON"),
        )]
        result = self.run_import(payload, apply=True)
        self.assertEqual(result["catalogs_created"], 4)
        self.assertEqual(result["values_created"], 20)
        for catalog in MaterialCatalog.objects.all():
            self.assertFalse(catalog.spray_enabled)
            self.assertEqual(catalog.attribute_values.count(), 5)
            self.assertEqual(
                list(catalog.attribute_values.filter(field_key="specification").values_list("value", flat=True)),
                ["Φ20×30 / 厚0.8；A型", "30×40×2（含接头）\n按图加工"],
            )
        self.assertEqual(self.run_import(payload, apply=True)["catalogs_unchanged"], 4)

    def test_existing_catalog_additions_refresh_version_once_and_preserve_values(self):
        self.run_import(apply=True)
        catalog = MaterialCatalog.objects.get()
        before_version = catalog.updated_at
        payload = deepcopy(self.payload)
        payload["catalogs"][0]["spray_enabled"] = False
        payload["catalogs"][0]["values"] = [{"scope": "BASE", "field_key": "thickness", "value": "0.8"}]
        payload["catalogs"][0]["units"] = []
        result = self.run_import(payload, apply=True)
        catalog.refresh_from_db()
        self.assertGreater(catalog.updated_at, before_version)
        self.assertTrue(catalog.spray_enabled)
        self.assertEqual(result["catalogs_changed"], 1)
        self.assertEqual(AuditLog.objects.filter(object_type="MATERIAL_CATALOG").count(), 2)
        self.assertTrue(catalog.attribute_values.filter(field_key="material", value="Q235").exists())

    def test_missing_parent_and_foreign_catalog_shape_are_rejected(self):
        self.importer()
        other = MaterialCatalog.objects.create(category_key="TUBE", template_key="TUBE", name="别的铁管")
        MaterialAttributeValue.objects.create(catalog=other, scope="BASE", field_key="shape", value="方管")
        payload = deepcopy(self.payload)
        payload["catalogs"][0]["values"] = [payload["catalogs"][0]["values"][1]]
        before = self.counts()
        with self.assertRaises(ValidationError):
            self.run_import(payload, apply=True)
        self.assertEqual(self.counts(), before)

    def test_existing_live_shape_may_parent_new_dimensions(self):
        self.run_import(apply=True)
        payload = deepcopy(self.payload)
        payload["catalogs"][0]["values"] = [
            {"scope": "BASE", "field_key": "section_size", "value": "30×30", "parent_value": "方管"},
        ]
        self.run_import(payload, apply=True)
        self.assertEqual(MaterialAttributeValue.objects.filter(field_key="section_size").count(), 2)

    def test_unknown_and_invalid_payloads_are_rejected_before_any_write(self):
        self.importer()
        invalid = []
        for key, value in (("unknown", True), ("version", 2), ("version", True)):
            candidate = deepcopy(self.payload)
            candidate[key] = value
            invalid.append(candidate)
        for key, value in (("filename", "../原料.xlsx"), ("sha256", "not-a-hash")):
            candidate = deepcopy(self.payload)
            candidate["source"][key] = value
            invalid.append(candidate)
        for key, value in (("template_key", "FABRIC"), ("spray_enabled", "true"), ("name", "  ")):
            candidate = deepcopy(self.payload)
            candidate["catalogs"][0][key] = value
            invalid.append(candidate)
        for invalid_value in (
            {"scope": "BASE", "field_key": "unknown", "value": "X"},
            {"scope": "BASE", "field_key": "unit", "value": "根"},
            {"scope": "BASE", "field_key": "material", "value": "X", "parent_value": "方管"},
            {"scope": "BASE", "field_key": "section_size", "value": "20×20"},
            {"scope": "SPRAY", "field_key": "material", "value": "X"},
        ):
            candidate = deepcopy(self.payload)
            candidate["catalogs"][0]["values"].append(invalid_value)
            invalid.append(candidate)
        before = self.counts()
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    self.run_import(payload, apply=True)
                self.assertEqual(self.counts(), before)

    def test_invalid_second_catalog_rejects_entire_batch(self):
        self.importer()
        payload = deepcopy(self.payload)
        payload["catalogs"].append(deepcopy(payload["catalogs"][0]))
        payload["catalogs"][1]["name"] = "第二个物料"
        payload["catalogs"][1]["units"][0]["unit_name"] = "不存在的单位"
        before = self.counts()
        with self.assertRaises(ValidationError):
            self.run_import(payload, apply=True)
        self.assertEqual(self.counts(), before)

    def test_disabled_or_archived_dictionary_unit_is_rejected(self):
        self.importer()
        for changes in ({"status": "INACTIVE"}, {"archived_at": timezone.now()}):
            with self.subTest(changes=changes):
                ProductionUnit.objects.filter(pk=self.unit.pk).update(status="ACTIVE", archived_at=None)
                ProductionUnit.objects.filter(pk=self.unit.pk).update(**changes)
                before = self.counts()
                with self.assertRaises(ValidationError):
                    self.run_import(apply=True)
                self.assertEqual(self.counts(), before)

    def test_archived_catalog_value_or_unit_is_never_restored(self):
        self.run_import(apply=True)
        catalog = MaterialCatalog.objects.get()
        targets = [catalog, catalog.attribute_values.get(field_key="material"), catalog.allowed_units.first()]
        for target in targets:
            with self.subTest(target=type(target).__name__):
                target.archived_at = timezone.now()
                target.save(update_fields=["archived_at"])
                before = self.counts()
                with self.assertRaises(ValidationError):
                    self.run_import(apply=True)
                self.assertEqual(self.counts(), before)
                target.refresh_from_db()
                self.assertIsNotNone(target.archived_at)
                target.archived_at = None
                target.save(update_fields=["archived_at"])

    def test_existing_or_duplicate_template_conflicts_are_rejected(self):
        self.importer()
        MaterialCatalog.objects.create(category_key="PACKAGING", template_key="CARTON", name="包装")
        payload = deepcopy(self.payload)
        payload["catalogs"] = [{
            "category_key": "PACKAGING", "template_key": "BAG", "name": "包装",
            "spray_enabled": False, "values": [], "units": [],
        }]
        before = self.counts()
        with self.assertRaises(ValidationError):
            self.run_import(payload, apply=True)
        self.assertEqual(self.counts(), before)
        payload["catalogs"][0]["name"] = "新包装"
        payload["catalogs"].append({**payload["catalogs"][0], "template_key": "CARTON"})
        with self.assertRaises(ValidationError):
            self.run_import(payload, apply=True)
        self.assertEqual(self.counts(), before)

    def test_intermediate_failure_rolls_back_catalogs_values_units_and_audit(self):
        importer = self.importer()
        payload = deepcopy(self.payload)
        payload["catalogs"].append({**deepcopy(payload["catalogs"][0]), "name": "第二个物料"})
        original = importer.write_audit_log
        calls = 0

        def fail_second_audit(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("模拟审计写入故障")
            return original(**kwargs)

        before = self.counts()
        with patch.object(importer, "write_audit_log", side_effect=fail_second_audit):
            with self.assertRaisesRegex(RuntimeError, "模拟审计写入故障"):
                self.run_import(payload, apply=True)
        self.assertEqual(self.counts(), before)

    def test_command_defaults_to_dry_run_and_requires_apply_to_write(self):
        self.importer()
        output = StringIO()
        with patch("apps.material_catalog.management.commands.import_material_catalog.Path.read_text", return_value=json.dumps(self.payload)):
            call_command("import_material_catalog", "confirmed.json", stdout=output)
        self.assertEqual(MaterialCatalog.objects.count(), 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "dry-run")
        output = StringIO()
        with patch("apps.material_catalog.management.commands.import_material_catalog.Path.read_text", return_value=json.dumps(self.payload)):
            call_command("import_material_catalog", "confirmed.json", apply=True, stdout=output)
        self.assertEqual(MaterialCatalog.objects.count(), 1)
        self.assertEqual(json.loads(output.getvalue())["mode"], "apply")

    def test_command_reports_malformed_file_without_writing(self):
        self.importer()
        with patch("apps.material_catalog.management.commands.import_material_catalog.Path.read_text", return_value="{bad"):
            with self.assertRaises(CommandError):
                call_command("import_material_catalog", "confirmed.json", apply=True)
        self.assertEqual(MaterialCatalog.objects.count(), 0)
