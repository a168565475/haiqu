from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductionUnit


ROOT = "/api/v1/material-catalog/"


class MaterialCatalogApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="catalog_admin", password="CatalogTestPassword123!", email=""
        )
        self.employee = Employee.objects.create(
            user=self.user, employee_code="CATALOG_ADMIN", display_name="原料管理测试员"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.sequence = 0

    def create_catalog(self, **overrides):
        self.sequence += 1
        payload = {"name": f"铁管 {self.sequence}", "category_key": "TUBE", "template_key": "TUBE"}
        payload.update(overrides)
        response = self.client.post(ROOT, payload, format="json")
        self.assertEqual(response.status_code, 201, getattr(response, "data", None))
        self.assertIn("ETag", response)
        return response

    def write(self, previous, method, suffix="", payload=None):
        url = f"{ROOT}{previous.data['data']['id']}/{suffix}"
        return getattr(self.client, method)(
            url, payload or {}, format="json", HTTP_IF_MATCH=previous["ETag"]
        )

    def add_value(self, previous, field="material", value="Q235", scope="BASE", parent_id=None):
        return self.write(previous, "post", "values/", {
            "scope": scope, "field_key": field, "value": value, "parent_id": parent_id,
        })

    def assert_write(self, response):
        self.assertEqual(response.status_code, 200, getattr(response, "data", None))
        self.assertIn("ETag", response)
        return response

    def test_options_exposes_fixed_templates_and_available_units(self):
        response = self.client.get(f"{ROOT}options/")
        self.assertEqual(response.status_code, 200)
        categories = {row["key"]: row for row in response.data["data"]["categories"]}
        self.assertEqual(set(categories), {"TUBE", "FABRIC", "HARDWARE", "PLASTIC", "PACKAGING", "AUXILIARY", "FABRIC_SEMI"})
        self.assertEqual({row["key"] for row in categories["PACKAGING"]["templates"]}, {"CARTON", "BAG", "PACKAGING_GENERAL"})
        self.assertEqual({row["key"] for row in categories["AUXILIARY"]["templates"]}, {"TAPE", "COTTON", "AUXILIARY_GENERAL"})
        self.assertTrue(categories["TUBE"]["templates"][0]["supports_spray"])
        self.assertFalse(categories["FABRIC"]["templates"][0]["supports_spray"])
        self.assertEqual({row["key"] for row in response.data["data"]["spray_fields"]}, {"color", "length", "unit"})
        self.assertEqual({row["id"] for row in response.data["data"]["units"]},
                         {str(pk) for pk in ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).values_list("pk", flat=True)})

    def test_creation_trims_name_adds_no_color_and_preserves_legacy_materials(self):
        before = list(RawMaterialInformation.objects.order_by("id").values_list("id", "updated_at"))
        response = self.create_catalog(name="  铁管  ")
        data = response.data["data"]
        self.assertEqual(data["name"], "铁管")
        self.assertFalse(data["spray_enabled"])
        self.assertEqual([(v["scope"], v["field_key"], v["value"]) for v in data["values"]], [("BASE", "color", "无颜色")])
        self.assertEqual(data["units"], [])
        detail = self.client.get(f"{ROOT}{data['id']}/")
        self.assertEqual(detail["ETag"], response["ETag"])
        self.assertEqual(before, list(RawMaterialInformation.objects.order_by("id").values_list("id", "updated_at")))
        audit = AuditLog.objects.get(object_type="MATERIAL_CATALOG", object_id=data["id"])
        self.assertEqual(audit.actor_employee_id, self.employee.pk)
        self.assertEqual(audit.after_data["name"], "铁管")

    def test_hardware_flow_unit_save_and_delete_preserve_allowed_units(self):
        current = self.create_catalog(name="螺丝", category_key="HARDWARE", template_key="HARDWARE")
        unit = ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        current = self.assert_write(self.write(current, "post", "units/", {"scope": "BASE", "unit_id": str(unit.pk)}))
        allowed_units = current.data["data"]["units"]
        current = self.assert_write(self.add_value(current, field="flow_unit", value="KG"))
        self.assertEqual(current.data["data"]["units"], allowed_units)
        self.assertEqual(self.add_value(current, field="flow_unit", value="KG").status_code, 400)
        option = next(value for value in current.data["data"]["values"] if value["field_key"] == "flow_unit")
        self.assertEqual((option["scope"], option["value"]), ("BASE", "KG"))
        current = self.assert_write(self.write(current, "delete", f"values/{option['id']}/"))
        self.assertEqual(current.data["data"]["units"], allowed_units)
        self.assertFalse(any(value["field_key"] == "flow_unit" for value in current.data["data"]["values"]))
        model = apps.get_model("material_catalog", "MaterialAttributeValue")
        self.assertIsNotNone(model.objects.get(pk=option["id"]).archived_at)

    def test_flow_unit_is_rejected_outside_hardware_base_group(self):
        tube = self.create_catalog()
        self.assertEqual(self.add_value(tube, field="flow_unit", value="KG").status_code, 400)
        hardware = self.create_catalog(category_key="HARDWARE", template_key="HARDWARE")
        hardware = self.assert_write(self.write(hardware, "patch", payload={"spray_enabled": True}))
        self.assertEqual(self.add_value(hardware, field="flow_unit", value="KG", scope="SPRAY").status_code, 400)

    def test_packaging_box_shapes_are_independent_options_and_delete_without_losing_size(self):
        for template, size_field in (("CARTON", "size"), ("BAG", "size"), ("PACKAGING_GENERAL", "specification")):
            with self.subTest(template=template):
                current = self.create_catalog(category_key="PACKAGING", template_key=template)
                current = self.assert_write(self.add_value(current, field=size_field, value="95*65"))
                if template == "BAG":
                    current = self.assert_write(self.add_value(current, field="bag_type", value="自封袋"))
                current = self.assert_write(self.add_value(current, field="box_type", value="半盖"))
                current = self.assert_write(self.add_value(current, field="box_type", value="天地盖"))
                self.assertEqual(self.add_value(current, field="box_type", value="半盖").status_code, 400)
                shapes = [value for value in current.data["data"]["values"] if value["field_key"] == "box_type"]
                self.assertEqual({value["value"] for value in shapes}, {"半盖", "天地盖"})
                self.assertTrue(all(value["scope"] == "BASE" and value["parent_id"] is None for value in shapes))
                current = self.assert_write(self.write(current, "delete", f"values/{shapes[0]['id']}/"))
                self.assertEqual(sum(value["field_key"] == "box_type" for value in current.data["data"]["values"]), 1)
                self.assertTrue(any(value["field_key"] == size_field and value["value"] == "95*65" for value in current.data["data"]["values"]))
                if template == "BAG":
                    self.assertTrue(any(value["field_key"] == "bag_type" and value["value"] == "自封袋" for value in current.data["data"]["values"]))
                self.assertEqual(current.data["data"]["units"], [])

    def test_packaging_models_save_and_delete_preserve_size_box_shape_thickness_and_units(self):
        options = self.client.get(f"{ROOT}options/").data["data"]["categories"]
        templates = next(category for category in options if category["key"] == "PACKAGING")["templates"]
        self.assertTrue(all({"key": "model", "label": "型号", "kind": "text"} in template["fields"] for template in templates))
        unit = ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        for template, size_field in (("CARTON", "size"), ("BAG", "size"), ("PACKAGING_GENERAL", "specification")):
            with self.subTest(template=template):
                current = self.create_catalog(category_key="PACKAGING", template_key=template)
                current = self.assert_write(self.add_value(current, field=size_field, value="78*65"))
                current = self.assert_write(self.add_value(current, field="box_type", value="半盖"))
                if template == "BAG":
                    current = self.assert_write(self.add_value(current, field="thickness", value="3丝"))
                current = self.assert_write(self.write(current, "post", "units/", {"scope": "BASE", "unit_id": str(unit.pk)}))
                original_values, original_units = current.data["data"]["values"], current.data["data"]["units"]
                for model in ("2.5MM", "10.1*7.6"):
                    current = self.assert_write(self.add_value(current, field="model", value=model))
                self.assertEqual(self.add_value(current, field="model", value="2.5MM").status_code, 400)
                models = [value for value in current.data["data"]["values"] if value["field_key"] == "model"]
                self.assertEqual({value["value"] for value in models}, {"2.5MM", "10.1*7.6"})
                current = self.assert_write(self.write(current, "delete", f"values/{models[0]['id']}/"))
                self.assertEqual(sum(value["field_key"] == "model" for value in current.data["data"]["values"]), 1)
                self.assertEqual([value for value in current.data["data"]["values"] if value["field_key"] != "model"], original_values)
                self.assertEqual(current.data["data"]["units"], original_units)
                self.assertEqual(self.add_value(current, field="model", value="2.5MM", scope="SPRAY").status_code, 400)

    def test_fabric_semi_width_save_and_delete_preserve_specification_and_units(self):
        options = self.client.get(f"{ROOT}options/").data["data"]["categories"]
        fields = next(category for category in options if category["key"] == "FABRIC_SEMI")["templates"][0]["fields"]
        self.assertIn({"key": "width", "label": "门幅", "kind": "text"}, fields)
        current = self.create_catalog(name="椅面", category_key="FABRIC_SEMI", template_key="FABRIC_SEMI")
        current = self.assert_write(self.add_value(current, field="specification", value="103*60/49*80/29"))
        unit = ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        current = self.assert_write(self.write(current, "post", "units/", {"scope": "BASE", "unit_id": str(unit.pk)}))
        allowed_units = current.data["data"]["units"]
        for width in ("1.5", "1.50"):
            current = self.assert_write(self.add_value(current, field="width", value=width))
        self.assertEqual(self.add_value(current, field="width", value="1.5").status_code, 400)
        widths = [value for value in current.data["data"]["values"] if value["field_key"] == "width"]
        self.assertEqual({value["value"] for value in widths}, {"1.5", "1.50"})
        current = self.assert_write(self.write(current, "delete", f"values/{widths[0]['id']}/"))
        self.assertEqual(sum(value["field_key"] == "width" for value in current.data["data"]["values"]), 1)
        self.assertTrue(any(value["field_key"] == "specification" and value["value"] == "103*60/49*80/29" for value in current.data["data"]["values"]))
        self.assertEqual(current.data["data"]["units"], allowed_units)
        self.assertEqual(self.add_value(current, field="width", value="1.5", scope="SPRAY").status_code, 400)

    def test_duplicate_names_are_rejected_within_category_only(self):
        self.create_catalog(name="圆管")
        duplicate = self.client.post(ROOT, {"name": " 圆管 ", "category_key": "TUBE", "template_key": "TUBE"}, format="json")
        self.assertEqual(duplicate.status_code, 400)
        self.create_catalog(name="圆管", category_key="HARDWARE", template_key="HARDWARE")

    def test_invalid_category_template_and_unknown_payload_keys_are_rejected(self):
        for payload in (
            {"name": "A", "category_key": "UNKNOWN", "template_key": "UNKNOWN"},
            {"name": "A", "category_key": "PACKAGING", "template_key": "TUBE"},
            {"name": "A", "category_key": "AUXILIARY"},
            {"name": " ", "category_key": "TUBE", "template_key": "TUBE"},
            {"name": "A", "category_key": "TUBE", "template_key": "TUBE", "unit": "米"},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(ROOT, payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("field_errors", response.data["error"])

    def test_list_filters_category_and_name_without_generating_combinations(self):
        first = self.create_catalog(name="钢管")
        self.create_catalog(name="钢管", category_key="HARDWARE", template_key="HARDWARE")
        self.create_catalog(name="铜管")
        current = self.assert_write(self.add_value(first, value="Q235"))
        self.assert_write(self.add_value(current, value="Q345"))
        response = self.client.get(ROOT, {"category": "TUBE", "q": "钢", "page_size": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["meta"]["total"], 1)
        self.assertEqual(response.data["data"][0]["id"], first.data["data"]["id"])
        self.assertEqual(self.client.get(ROOT).data["meta"]["total"], 3)
        self.assertEqual(self.client.get(ROOT, {"category": "OTHER"}).status_code, 400)

    def test_values_are_per_catalog_and_reject_duplicates_and_blank_values(self):
        first = self.create_catalog()
        second = self.create_catalog()
        current = self.assert_write(self.add_value(first, value=" Q235 "))
        self.assertNotEqual(current["ETag"], first["ETag"])
        self.assertEqual(self.add_value(current, value="Q235").status_code, 400)
        self.assertEqual(self.add_value(current, value="  ").status_code, 400)
        self.assert_write(self.add_value(second, value="Q235"))
        self.assertEqual(len(current.data["data"]["values"]), 2)

    def test_fixed_template_fields_and_scope_are_enforced(self):
        catalog = self.create_catalog()
        for field, scope in (("fabric_spec", "BASE"), ("unit", "BASE"), ("material", "SPRAY"), ("color", "OTHER")):
            with self.subTest(field=field, scope=scope):
                self.assertEqual(self.add_value(catalog, field=field, scope=scope).status_code, 400)
        self.assertEqual(self.add_value(catalog, field="color", value="黑色", scope="SPRAY").status_code, 400)

    def test_section_sizes_require_live_shape_in_same_catalog(self):
        first = self.create_catalog()
        second = self.create_catalog()
        shaped = self.assert_write(self.add_value(first, field="shape", value="异形管"))
        shape_id = next(v["id"] for v in shaped.data["data"]["values"] if v["field_key"] == "shape")
        self.assertEqual(self.add_value(shaped, field="section_size", value="20×30").status_code, 400)
        self.assertEqual(self.add_value(second, field="section_size", value="20×30", parent_id=shape_id).status_code, 400)
        self.assertEqual(self.add_value(shaped, field="material", parent_id=shape_id).status_code, 400)
        sized = self.assert_write(self.add_value(shaped, field="section_size", value="20×30", parent_id=shape_id))
        size_id = next(v["id"] for v in sized.data["data"]["values"] if v["field_key"] == "section_size")
        self.assertEqual(self.add_value(sized, field="section_size", value="30×40", parent_id=size_id).status_code, 400)
        self.assertEqual(self.write(sized, "delete", f"values/{shape_id}/").status_code, 400)
        without_size = self.assert_write(self.write(sized, "delete", f"values/{size_id}/"))
        without_shape = self.assert_write(self.write(without_size, "delete", f"values/{shape_id}/"))
        self.assertEqual(self.add_value(without_shape, field="section_size", value="20×30", parent_id=shape_id).status_code, 400)

    def test_same_dimension_text_can_belong_to_different_shapes(self):
        current = self.create_catalog()
        current = self.assert_write(self.add_value(current, field="shape", value="方管"))
        current = self.assert_write(self.add_value(current, field="shape", value="矩形管"))
        shapes = [v["id"] for v in current.data["data"]["values"] if v["field_key"] == "shape"]
        for shape in shapes:
            current = self.assert_write(self.add_value(current, field="section_size", value="20×20", parent_id=shape))
        self.assertEqual(sum(v["field_key"] == "section_size" for v in current.data["data"]["values"]), 2)

    def test_value_delete_is_soft_and_readdition_restores_with_audit(self):
        current = self.assert_write(self.add_value(self.create_catalog()))
        option_id = next(v["id"] for v in current.data["data"]["values"] if v["field_key"] == "material")
        deleted = self.assert_write(self.write(current, "delete", f"values/{option_id}/"))
        model = apps.get_model("material_catalog", "MaterialAttributeValue")
        self.assertIsNotNone(model.objects.get(pk=option_id).archived_at)
        self.assertEqual(self.write(deleted, "delete", f"values/{option_id}/").status_code, 404)
        restored = self.assert_write(self.add_value(deleted))
        self.assertIn(option_id, [v["id"] for v in restored.data["data"]["values"]])
        self.assertIsNone(model.objects.get(pk=option_id).archived_at)
        actions = set(AuditLog.objects.filter(object_type="MATERIAL_CATALOG", object_id=current.data["data"]["id"]).values_list("action", flat=True))
        self.assertTrue({"VALUE_REMOVED", "VALUE_RESTORED"}.issubset(actions))

    def test_spray_toggle_preserves_same_catalog_and_hidden_group_values(self):
        original = self.create_catalog()
        enabled = self.assert_write(self.write(original, "patch", payload={"spray_enabled": True}))
        self.assertEqual(original.data["data"]["id"], enabled.data["data"]["id"])
        self.assertEqual([(v["field_key"], v["value"]) for v in enabled.data["data"]["values"] if v["scope"] == "SPRAY"], [("color", "无颜色")])
        colored = self.assert_write(self.add_value(enabled, field="color", value="黑色", scope="SPRAY"))
        disabled = self.assert_write(self.write(colored, "patch", payload={"spray_enabled": False}))
        self.assertEqual(colored.data["data"]["values"], disabled.data["data"]["values"])
        self.assertEqual(self.add_value(disabled, field="length", value="100", scope="SPRAY").status_code, 400)
        restored = self.assert_write(self.write(disabled, "patch", payload={"spray_enabled": True}))
        self.assertEqual(colored.data["data"]["values"], restored.data["data"]["values"])

    def test_spray_rejected_for_fabric_and_main_patch_cannot_rename_or_change_category(self):
        fabric = self.create_catalog(category_key="FABRIC", template_key="FABRIC")
        self.assertEqual(self.write(fabric, "patch", payload={"spray_enabled": True}).status_code, 400)
        for payload in ({"name": "新名称"}, {"category_key": "TUBE"}, {"spray_enabled": "yes"}, {}):
            with self.subTest(payload=payload):
                self.assertEqual(self.write(fabric, "patch", payload=payload).status_code, 400)

    def test_reenabling_spray_does_not_restore_a_deliberately_removed_default_color(self):
        current = self.assert_write(self.write(self.create_catalog(), "patch", payload={"spray_enabled": True}))
        color_id = next(v["id"] for v in current.data["data"]["values"] if v["scope"] == "SPRAY")
        current = self.assert_write(self.write(current, "delete", f"values/{color_id}/"))
        current = self.assert_write(self.write(current, "patch", payload={"spray_enabled": False}))
        current = self.assert_write(self.write(current, "patch", payload={"spray_enabled": True}))
        self.assertFalse(any(v["scope"] == "SPRAY" for v in current.data["data"]["values"]))

    def test_spray_options_can_be_managed_for_hardware_without_duplicating_base(self):
        current = self.create_catalog(category_key="HARDWARE", template_key="HARDWARE")
        current = self.assert_write(self.add_value(current, field="surface_finish", value="镀锌"))
        current = self.assert_write(self.write(current, "patch", payload={"spray_enabled": True}))
        current = self.assert_write(self.add_value(current, field="length", value="按图纸", scope="SPRAY"))
        unit = ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        current = self.assert_write(self.write(current, "post", "units/", {"scope": "SPRAY", "unit_id": str(unit.pk)}))
        self.assertEqual(sum(v["field_key"] == "surface_finish" for v in current.data["data"]["values"]), 1)
        option_id = current.data["data"]["units"][0]["id"]
        self.assert_write(self.write(current, "delete", f"units/{option_id}/"))

    def test_every_confirmed_template_accepts_its_distinct_fields(self):
        examples = [
            ("FABRIC", "FABRIC", "finish", "PU涂层"),
            ("HARDWARE", "HARDWARE", "thread", "M6"),
            ("PLASTIC", "PLASTIC", "tube_size", "20×30"),
            ("PACKAGING", "CARTON", "layers", "五层"),
            ("PACKAGING", "BAG", "bag_type", "自封袋"),
            ("PACKAGING", "PACKAGING_GENERAL", "specification", "10×20"),
            ("AUXILIARY", "TAPE", "width", "20"),
            ("AUXILIARY", "COTTON", "gram_weight", "120"),
            ("AUXILIARY", "AUXILIARY_GENERAL", "specification", "30×40"),
            ("FABRIC_SEMI", "FABRIC_SEMI", "process", "双线车缝V1"),
        ]
        for category, template, field, value in examples:
            with self.subTest(template=template):
                current = self.create_catalog(category_key=category, template_key=template)
                result = self.assert_write(self.add_value(current, field=field, value=value))
                self.assertTrue(any(row["field_key"] == field and row["value"] == value for row in result.data["data"]["values"]))

    def test_generic_templates_keep_independent_values_and_reject_specialized_fields_and_spray(self):
        for category, template, specialized in (
            ("PACKAGING", "PACKAGING_GENERAL", "CARTON"),
            ("AUXILIARY", "AUXILIARY_GENERAL", "TAPE"),
        ):
            with self.subTest(template=template):
                current = self.create_catalog(name="通用品名", category_key=category, template_key=template)
                for field, value in (("material", "通用材质"), ("color", "白色"), ("specification", "10×20"), ("specification", "30×40")):
                    current = self.assert_write(self.add_value(current, field=field, value=value))
                self.assertEqual(
                    {row["value"] for row in current.data["data"]["values"] if row["field_key"] == "specification"},
                    {"10×20", "30×40"},
                )
                unit = ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
                current = self.assert_write(self.write(current, "post", "units/", {"scope": "BASE", "unit_id": str(unit.pk)}))
                for field in ("layers", "width", "size"):
                    self.assertEqual(self.add_value(current, field=field, value="不能套用专用属性").status_code, 400)
                self.assertEqual(self.write(current, "patch", payload={"spray_enabled": True}).status_code, 400)
                duplicate = self.client.post(ROOT, {
                    "name": "通用品名", "category_key": category, "template_key": specialized,
                }, format="json")
                self.assertEqual(duplicate.status_code, 400)
                detail = self.client.get(f"{ROOT}{current.data['data']['id']}/")
                self.assertEqual(detail.data, current.data)

    def test_confirmed_templates_save_verbatim_specifications_without_attribute_combinations(self):
        for category, template in (
            ("PLASTIC", "PLASTIC"), ("FABRIC_SEMI", "FABRIC_SEMI"),
            ("AUXILIARY", "TAPE"), ("AUXILIARY", "COTTON"),
        ):
            with self.subTest(template=template):
                current = self.create_catalog(category_key=category, template_key=template)
                for field, value in (
                    ("specification", "Φ20×30 / 厚0.8；A型"),
                    ("specification", "30×40×2（含接头）\n按图加工"),
                    ("material", "材质甲"), ("material", "材质乙"),
                ):
                    current = self.assert_write(self.add_value(current, field=field, value=value))
                detail = self.client.get(f"{ROOT}{current.data['data']['id']}/")
                self.assertEqual(detail.status_code, 200)
                values = detail.data["data"]["values"]
                self.assertEqual(len(values), 5)
                self.assertEqual(
                    [row["value"] for row in values if row["field_key"] == "specification"],
                    ["Φ20×30 / 厚0.8；A型", "30×40×2（含接头）\n按图加工"],
                )
                self.assertEqual(self.add_value(current, field="specification", value="喷塑不能维护", scope="SPRAY").status_code, 400)

    def test_unconfirmed_templates_and_enabled_spray_reject_specification(self):
        for category, template in (
            ("TUBE", "TUBE"), ("FABRIC", "FABRIC"),
            ("PACKAGING", "CARTON"), ("PACKAGING", "BAG"),
        ):
            with self.subTest(template=template):
                current = self.create_catalog(category_key=category, template_key=template)
                self.assertEqual(self.add_value(current, field="specification", value="不适用规格").status_code, 400)
        current = self.create_catalog(category_key="HARDWARE", template_key="HARDWARE")
        current = self.assert_write(self.write(current, "patch", payload={"spray_enabled": True}))
        self.assertEqual(self.add_value(current, field="specification", value="喷塑不能维护", scope="SPRAY").status_code, 400)

    def test_generic_template_category_and_spray_rules_are_enforced_by_database(self):
        model = apps.get_model("material_catalog", "MaterialCatalog")
        for category, template, other_category in (
            ("PACKAGING", "PACKAGING_GENERAL", "AUXILIARY"),
            ("AUXILIARY", "AUXILIARY_GENERAL", "PACKAGING"),
        ):
            with self.subTest(template=template):
                model.objects.create(name="合法通用档案", category_key=category, template_key=template)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    model.objects.create(name="错配类别", category_key=other_category, template_key=template)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    model.objects.create(name="不允许喷塑", category_key=category, template_key=template, spray_enabled=True)

    def test_allowed_units_are_options_without_conversion_and_use_soft_delete(self):
        current = self.create_catalog()
        units = list(ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True)[:2])
        for unit in units:
            current = self.assert_write(self.write(current, "post", "units/", {"scope": "BASE", "unit_id": str(unit.pk)}))
        self.assertEqual({row["unit_id"] for row in current.data["data"]["units"]}, {str(unit.pk) for unit in units})
        for row in current.data["data"]["units"]:
            self.assertEqual(set(row), {"id", "scope", "unit_id", "unit_name"})
        self.assertEqual(self.write(current, "post", "units/", {"scope": "BASE", "unit_id": str(units[0].pk)}).status_code, 400)
        option_id = current.data["data"]["units"][0]["id"]
        deleted = self.assert_write(self.write(current, "delete", f"units/{option_id}/"))
        self.assertIsNotNone(apps.get_model("material_catalog", "MaterialAllowedUnit").objects.get(pk=option_id).archived_at)
        self.assert_write(self.write(deleted, "post", "units/", {"scope": "BASE", "unit_id": str(units[0].pk)}))

    def test_unit_selection_rejects_disabled_unknown_and_wrong_scope_units(self):
        current = self.create_catalog()
        unit = ProductionUnit.objects.filter(status="ACTIVE").first()
        unit.status = "INACTIVE"
        unit.save()
        for payload in (
            {"scope": "BASE", "unit_id": str(unit.pk)},
            {"scope": "BASE", "unit_id": str(uuid4())},
            {"scope": "SPRAY", "unit_id": str(unit.pk)},
            {"scope": "BASE", "unit_id": str(unit.pk), "conversion_rate": 1000},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.write(current, "post", "units/", payload).status_code, 400)

    def test_missing_and_stale_etag_reject_writes_without_side_effects(self):
        first = self.create_catalog()
        url = f"{ROOT}{first.data['data']['id']}/values/"
        payload = {"scope": "BASE", "field_key": "material", "value": "Q235"}
        missing = self.client.post(url, payload, format="json")
        self.assertEqual(missing.status_code, 428)
        updated = self.assert_write(self.add_value(first))
        stale = self.add_value(first, value="Q345")
        self.assertEqual(stale.status_code, 412)
        self.assertEqual(self.client.get(f"{ROOT}{first.data['data']['id']}/").data, updated.data)

    def test_cross_catalog_deletions_and_nonexistent_children_are_rejected(self):
        first = self.assert_write(self.add_value(self.create_catalog()))
        second = self.create_catalog()
        value_id = next(v["id"] for v in first.data["data"]["values"] if v["field_key"] == "material")
        self.assertEqual(self.write(second, "delete", f"values/{value_id}/").status_code, 404)
        self.assertEqual(self.write(second, "delete", f"units/{uuid4()}/").status_code, 404)
        self.assertEqual(self.write(first, "delete").status_code, 405)

    def test_all_mutation_routes_require_parent_etag(self):
        current = self.create_catalog()
        catalog_id = current.data["data"]["id"]
        value_id = current.data["data"]["values"][0]["id"]
        unit = ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        current = self.assert_write(self.write(current, "post", "units/", {"scope": "BASE", "unit_id": str(unit.pk)}))
        option_id = current.data["data"]["units"][0]["id"]
        for method, suffix, payload in (
            ("patch", "", {"spray_enabled": True}),
            ("post", "units/", {"scope": "BASE", "unit_id": str(unit.pk)}),
            ("delete", f"values/{value_id}/", {}),
            ("delete", f"units/{option_id}/", {}),
        ):
            with self.subTest(method=method, suffix=suffix):
                response = getattr(self.client, method)(f"{ROOT}{catalog_id}/{suffix}", payload, format="json")
                self.assertEqual(response.status_code, 428)

    def test_value_and_main_etag_roll_back_when_audit_write_fails(self):
        original = self.create_catalog()
        with patch("apps.material_catalog.services.write_audit_log", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                self.add_value(original)
        detail = self.client.get(f"{ROOT}{original.data['data']['id']}/")
        self.assertEqual(detail.data, original.data)
        self.assertEqual(detail["ETag"], original["ETag"])

    def test_duplicate_name_is_also_prevented_at_database_boundary(self):
        original = self.create_catalog(name="铁管")
        model = apps.get_model("material_catalog", "MaterialCatalog")
        with self.assertRaises(IntegrityError), transaction.atomic():
            model.objects.create(name=original.data["data"]["name"], category_key="TUBE", template_key="TUBE")

    def test_module_permission_catalog_registers_new_resource(self):
        self.create_catalog()
        from apps.access_control.catalog import catalog
        entries = [row for row in catalog() if row["code"].startswith("material_catalog.")]
        self.assertEqual({row["code"] for row in entries}, {
            "material_catalog.view_materialcatalog", "material_catalog.add_materialcatalog", "material_catalog.change_materialcatalog",
        })
        self.assertTrue(all(row["available"] and row["resource_name"] == "原料管理" for row in entries))

    @override_settings(ACCESS_MANAGEMENT_ENABLED=False, SALES_ACCESS_ENABLED=False, MODULE_ACCESS_ENABLED=False)
    def test_view_permission_does_not_authorize_any_write(self):
        catalog = self.create_catalog()
        user = get_user_model().objects.create_user(username="catalog_reader")
        Employee.objects.create(user=user, employee_code="CATALOG_READER", display_name="只读员工")
        user.user_permissions.add(Permission.objects.get(content_type__app_label="material_catalog", codename="view_materialcatalog"))
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(ROOT).status_code, 200)
        self.assertEqual(self.client.get(f"{ROOT}options/").status_code, 200)
        self.assertEqual(self.client.post(ROOT, {"name": "A", "category_key": "TUBE", "template_key": "TUBE"}, format="json").status_code, 403)
        self.assertEqual(self.add_value(catalog).status_code, 403)
        self.assertEqual(self.write(catalog, "patch", payload={"spray_enabled": True}).status_code, 403)
        self.assertEqual(self.write(catalog, "delete", f"values/{catalog.data['data']['values'][0]['id']}/").status_code, 403)

    def test_anonymous_and_inactive_employee_cannot_access_catalog(self):
        response = self.client.get(ROOT)
        self.assertEqual(response.status_code, 200)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(ROOT).status_code, 401)
        user = get_user_model().objects.create_user(username="catalog_inactive")
        Employee.objects.create(user=user, employee_code="CATALOG_INACTIVE", display_name="停用员工", status="INACTIVE")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(ROOT).status_code, 403)

    def test_session_writes_require_csrf(self):
        self.assertEqual(self.client.get(ROOT).status_code, 200)
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        payload = {"name": "Session 原料", "category_key": "TUBE", "template_key": "TUBE"}
        self.assertEqual(client.post(ROOT, payload, format="json").status_code, 403)
        client.get("/api/auth/me/")
        token = client.cookies["csrftoken"].value
        response = client.post(ROOT, payload, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201, response.data)
