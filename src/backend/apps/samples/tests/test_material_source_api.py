from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.material_catalog.models import MaterialCatalog
from apps.organizations.models import Employee


@override_settings(MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False)
class SampleMaterialSourceApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="sample_material_source")
        self.employee = Employee.objects.create(user=self.user, employee_code="SAMPLE_SOURCE", display_name="打样填料")
        self.permission = Permission.objects.get(content_type__app_label="samples", codename="edit_sample_materials")
        self.user.user_permissions.add(self.permission)
        self.client.force_authenticate(self.user)
        self.catalog = MaterialCatalog.objects.create(name="窄源测试管", category_key="TUBE", template_key="TUBE")
        self.root = "/api/v1/sample-material-sources/"

    def test_fill_permission_can_select_without_full_catalog_or_bom_permission(self):
        self.assertFalse(self.user.has_perm("material_catalog.view_materialcatalog"))
        self.assertFalse(self.user.has_perm("boms.change_bom"))
        for suffix in ("", "options/", f"{self.catalog.pk}/", "crafts/"):
            with self.subTest(suffix=suffix):
                response = self.client.get(self.root + suffix)
                self.assertEqual(response.status_code, 200, response.data)
        public = self.client.get(self.root + "public-options/", {"category_key": "TUBE", "template_key": "TUBE"})
        self.assertEqual(public.status_code, 200, public.data)
        self.assertEqual(self.client.get(self.root + "options/").data["data"]["warehouses"], [])
        self.assertEqual(self.client.get("/api/v1/material-catalog/").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/boms/").status_code, 403)

    def test_read_only_and_validated_input(self):
        for method, suffix in (("post", ""), ("patch", f"{self.catalog.pk}/"), ("delete", f"{self.catalog.pk}/")):
            response = getattr(self.client, method)(self.root + suffix, {}, format="json")
            self.assertIn(response.status_code, (403, 405))
        self.assertEqual(self.client.get(self.root + "not-a-uuid/").status_code, 400)
        self.assertEqual(self.client.get(self.root, {"category": "INVALID"}).status_code, 400)
        self.assertEqual(self.client.get(self.root + "public-options/", {"category_key": "TUBE"}).status_code, 400)
        self.catalog.archived_at = timezone.now()
        self.catalog.save(update_fields=["archived_at"])
        self.assertEqual(self.client.get(self.root + f"{self.catalog.pk}/").status_code, 404)
        self.assertEqual(self.client.get(self.root).data["data"], [])

    def test_missing_permission_and_inactive_employee_are_denied(self):
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get(self.root).status_code, 403)
        self.user.user_permissions.add(self.permission)
        self.employee.status = "INACTIVE"
        self.employee.save(update_fields=["status"])
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get(self.root).status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.root).status_code, (401, 403))
