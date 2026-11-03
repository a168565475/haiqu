from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.material_catalog.accessory_weights import WEIGHT_FIELDS
from apps.material_catalog.models import MaterialCatalog
from apps.material_catalog.public_configuration import ensure_public_value, public_options
from apps.organizations.models import Employee
from apps.reference_data.models import AccessoryProductName, AccessorySpecification, MaterialAttributePublicValue


ROOT = "/api/v1/reference-data/material-attribute-values/"


class AccessoryWeightConsolidationTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="weight_admin", password="WeightTest123!", email="")
        self.employee = Employee.objects.create(user=self.user, employee_code="WEIGHT_ADMIN", display_name="克重维护测试")
        self.client.force_authenticate(self.user)
        self.product = AccessoryProductName.objects.create(product_name="克重原分组", unit_name="米")
        self.catalog = MaterialCatalog.objects.create(category_key="AUXILIARY", template_key="COTTON", name="克重目录品名")
        self.serial = 0

    def specification(self, weight, **extra):
        self.serial += 1
        return AccessorySpecification.objects.create(product_name=self.product, specification_value=f"克重规格{self.serial}", weight=weight, **extra)

    def values(self):
        return [row["value"] for row in public_options("AUXILIARY", "COTTON", "BASE")["values"] if row["field_key"] == "gram_weight"]

    def test_derived_candidates_trim_deduplicate_and_ignore_invalid_or_inactive_sources(self):
        first = self.specification(" 本轮聚合120g ")
        second = self.specification("\t本轮聚合120g\t")
        for value in ("", "  ", "\t/\t", "-", " — "):
            self.specification(value)
        self.specification("不应显示的停用克重", status="INACTIVE")
        inactive_parent = AccessoryProductName.objects.create(product_name="克重停用分组", unit_name="米", status="INACTIVE")
        AccessorySpecification.objects.create(product_name=inactive_parent, specification_value="旧规格", weight="停用分组克重")
        response = self.client.get(ROOT, {**WEIGHT_FIELDS, "q": "本轮聚合120g"})
        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["value"], rows[0]["source_kind"], rows[0]["source_count"]), ("本轮聚合120g", "SPECIFICATION", 2))
        self.assertFalse(rows[0]["editable"])
        self.assertIn(rows[0]["id"], [str(first.pk), str(second.pk)])
        values = self.values()
        self.assertEqual(values.count("本轮聚合120g"), 1)
        for excluded in ("", "/", "-", "—", "不应显示的停用克重", "停用分组克重"):
            self.assertNotIn(excluded, values)

    def test_explicit_public_inactive_status_masks_same_derived_value(self):
        self.specification(" 本轮遮蔽180g ")
        public = MaterialAttributePublicValue.objects.create(**WEIGHT_FIELDS, value="本轮遮蔽180g", status="INACTIVE")
        response = self.client.get(ROOT, {**WEIGHT_FIELDS, "q": "本轮遮蔽180g"})
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["data"][0]
        self.assertEqual((row["id"], row["source_kind"], row["source_count"], row["status"]), (str(public.pk), "PUBLIC", 1, "INACTIVE"))
        self.assertTrue(row["editable"])
        self.assertNotIn("本轮遮蔽180g", self.values())
        with self.assertRaises(ValidationError):
            ensure_public_value(self.catalog, "BASE", "gram_weight", "本轮遮蔽180g")
        public.archived_at = timezone.now()
        public.save(update_fields=["archived_at", "updated_at"])
        self.assertNotIn("本轮遮蔽180g", self.values())
        hidden = self.client.get(ROOT, {**WEIGHT_FIELDS, "q": "本轮遮蔽180g"})
        self.assertEqual(hidden.data["data"], [])

    def test_reuse_derived_and_add_independent_value_without_rewriting_specifications(self):
        spec = self.specification("\t本轮复用210g ")
        before = (spec.weight, spec.updated_at)
        user = get_user_model().objects.create_user(username="weight_reader")
        employee = Employee.objects.create(user=user, employee_code="WEIGHT_READER", display_name="克重选料员")
        user.user_permissions.add(Permission.objects.get(content_type__app_label="material_catalog", codename="view_materialcatalog"))
        request = SimpleNamespace(user=user, employee=employee, META={})
        with transaction.atomic():
            reused = ensure_public_value(self.catalog, "BASE", "gram_weight", "本轮复用210g", request=request)
        self.assertEqual(reused.pk, spec.pk)
        self.assertFalse(MaterialAttributePublicValue.objects.filter(**WEIGHT_FIELDS, value="本轮复用210g").exists())
        duplicate = self.client.post(ROOT, {**WEIGHT_FIELDS, "value": "本轮复用210g"}, format="json")
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        added = self.client.post(ROOT, {**WEIGHT_FIELDS, "value": "新增独立220g"}, format="json")
        self.assertEqual(added.status_code, 201, added.data)
        self.assertIn("新增独立220g", self.values())
        spec.refresh_from_db()
        self.assertEqual((spec.weight, spec.updated_at), before)
        self.assertEqual(AccessorySpecification.objects.filter(product_name=self.product).count(), 1)

    def test_derived_rows_cannot_be_mutated_through_generic_crud_and_follow_source_changes(self):
        spec = self.specification("本轮来源250g")
        url = f"{ROOT}{spec.pk}/"
        self.assertEqual(self.client.patch(url, {"value": "被误改"}, format="json", HTTP_IF_MATCH='"fake"').status_code, 404)
        self.assertEqual(self.client.post(url + "deactivate/", {"reason": "不允许误改来源"}, format="json", HTTP_IF_MATCH='"fake"').status_code, 404)
        self.assertIn(self.client.delete(url).status_code, (403, 405))
        spec.refresh_from_db()
        self.assertEqual((spec.weight, spec.status), ("本轮来源250g", "ACTIVE"))
        spec.weight = "本轮来源260g"
        spec.save(update_fields=["weight", "updated_at"])
        self.assertNotIn("本轮来源250g", self.values())
        self.assertIn("本轮来源260g", self.values())
