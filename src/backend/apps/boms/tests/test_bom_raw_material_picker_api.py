from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.organizations.models import Employee
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import (
    AccessoryProductName,
    ProductCategory,
    ProductionUnit,
    ReferenceStatus,
)


class BomRawMaterialPickerApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="bom_raw_picker_user")
        Employee.objects.create(
            user=self.user,
            employee_code="BOM_RAW_PICKER",
            display_name="BOM 原料选择测试员工",
        )
        self.user.user_permissions.add(
            Permission.objects.get(
                codename="change_bom",
                content_type__app_label="boms",
            )
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.unit = ProductionUnit.objects.filter(
            status=ReferenceStatus.ACTIVE,
            archived_at__isnull=True,
        ).first()
        self.assertIsNotNone(self.unit)

    def category(self, item_type, category_name):
        return ProductCategory.objects.get(
            item_type=item_type,
            category_name=category_name,
        )

    def create_raw_material(
        self,
        *,
        material_number,
        material_name,
        category,
        number_value="",
        archived_at=None,
    ):
        return RawMaterialInformation.objects.create(
            material_number=material_number,
            item_type=category.item_type,
            category=category,
            material_name=material_name,
            specification="选择器专测规格",
            unit=self.unit,
            color_snapshot="选择器专测颜色",
            material="选择器专测材质",
            warehouse_number="CK008",
            warehouse_name="包材仓",
            number_value=number_value,
            archived_at=archived_at,
        )

    def test_material_lists_support_fuzzy_and_exact_filters_and_expose_number_value(self):
        packaging = self.category("MATERIAL", "包材")
        exact_name = "选择器包材分组QZ9"
        first = self.create_raw_material(
            material_number="BOM-PACK-QZ9-001",
            material_name=exact_name,
            category=packaging,
            number_value="24",
        )
        second = self.create_raw_material(
            material_number="BOM-PACK-QZ9-002",
            material_name=exact_name,
            category=packaging,
            number_value="36",
        )
        fuzzy_only = self.create_raw_material(
            material_number="BOM-PACK-QZ9-003",
            material_name=f"{exact_name}扩展",
            category=packaging,
        )
        self.create_raw_material(
            material_number="BOM-PACK-QZ9-004",
            material_name=exact_name,
            category=packaging,
            archived_at=timezone.now(),
        )

        fuzzy = self.client.get(
            "/api/v1/boms/packaging-materials/",
            {"q": exact_name, "page": 1, "page_size": 20},
        )
        self.assertEqual(fuzzy.status_code, 200, fuzzy.data)
        self.assertEqual(fuzzy.data["meta"]["total"], 3)
        self.assertEqual(
            {item["id"] for item in fuzzy.data["data"]},
            {str(first.pk), str(second.pk), str(fuzzy_only.pk)},
        )

        exact = self.client.get(
            "/api/v1/boms/packaging-materials/",
            {"q": "选择器专测规格", "material_name": exact_name, "page_size": 20},
        )
        self.assertEqual(exact.status_code, 200, exact.data)
        self.assertEqual(exact.data["meta"]["total"], 2)
        self.assertEqual({item["number_value"] for item in exact.data["data"]}, {"24", "36"})
        self.assertTrue(all(item["category_name"] == "包材" for item in exact.data["data"]))

        groups = self.client.get("/api/v1/boms/packaging-material-groups/")
        self.assertEqual(groups.status_code, 200, groups.data)
        group = next(item for item in groups.data["data"] if item["material_name"] == exact_name)
        self.assertEqual(group["count"], 2)
        self.assertIn("xzqbcfzqz9", group["pinyin_search"])

        for url in (
            "/api/v1/boms/hardware-materials/",
            "/api/v1/boms/plastic-materials/",
            "/api/v1/boms/packaging-materials/",
        ):
            response = self.client.get(url, {"page_size": 1})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertIn("number_value", response.data["data"][0])

    def test_all_group_endpoints_include_pinyin_and_semi_finished_covers_every_category(self):
        hardware_groups = self.client.get("/api/v1/boms/hardware-material-groups/")
        self.assertEqual(hardware_groups.status_code, 200, hardware_groups.data)
        snap_ring = next(item for item in hardware_groups.data["data"] if item["material_name"] == "卡簧")
        self.assertEqual(snap_ring["pinyin_search"], "kahuang ka huang kh")

        for url in (
            "/api/v1/boms/plastic-material-groups/",
            "/api/v1/boms/packaging-material-groups/",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertTrue(response.data["data"])
            self.assertEqual(
                set(response.data["data"][0]),
                {"material_name", "count", "pinyin_search"},
            )

        shared_name = "半成品全类别QX8"
        categories = [
            self.category("SEMI_FINISHED", "喷塑五金"),
            self.category("SEMI_FINISHED", "喷塑管材"),
            self.category("SEMI_FINISHED", "委外布面"),
        ]
        created = [
            self.create_raw_material(
                material_number=f"BOM-SEMI-QX8-{index}",
                material_name=shared_name,
                category=category,
            )
            for index, category in enumerate(categories, start=1)
        ]
        listed = self.client.get(
            "/api/v1/boms/semi-finished-materials/",
            {"material_name": shared_name, "page_size": 20},
        )
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(listed.data["meta"]["total"], 3)
        self.assertEqual(
            {item["category_name"] for item in listed.data["data"]},
            {"喷塑五金", "喷塑管材", "委外布面"},
        )
        self.assertEqual({item["item_type"] for item in listed.data["data"]}, {"SEMI_FINISHED"})
        self.assertEqual({item["item_type_display"] for item in listed.data["data"]}, {"半成品"})
        self.assertEqual(
            {item["id"] for item in listed.data["data"]},
            {str(item.pk) for item in created},
        )

        semi_groups = self.client.get("/api/v1/boms/semi-finished-material-groups/")
        self.assertEqual(semi_groups.status_code, 200, semi_groups.data)
        group = next(item for item in semi_groups.data["data"] if item["material_name"] == shared_name)
        self.assertEqual(group["count"], 3)
        self.assertTrue(group["pinyin_search"])

    def test_inactive_or_archived_categories_are_excluded(self):
        shared_name = "停用类别过滤QW7"
        spray_hardware = self.category("SEMI_FINISHED", "喷塑五金")
        spray_tube = self.category("SEMI_FINISHED", "喷塑管材")
        outsourced_fabric = self.category("SEMI_FINISHED", "委外布面")
        for index, category in enumerate((spray_hardware, spray_tube, outsourced_fabric), start=1):
            self.create_raw_material(
                material_number=f"BOM-SEMI-QW7-{index}",
                material_name=shared_name,
                category=category,
            )

        spray_hardware.status = ReferenceStatus.INACTIVE
        spray_hardware.save(update_fields=["status", "updated_at"])
        spray_tube.archived_at = timezone.now()
        spray_tube.save(update_fields=["archived_at", "updated_at"])

        listed = self.client.get(
            "/api/v1/boms/semi-finished-materials/",
            {"q": shared_name, "page_size": 20},
        )
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(listed.data["meta"]["total"], 1)
        self.assertEqual(listed.data["data"][0]["category_name"], "委外布面")

        groups = self.client.get("/api/v1/boms/semi-finished-material-groups/")
        group = next(item for item in groups.data["data"] if item["material_name"] == shared_name)
        self.assertEqual(group["count"], 1)

    def test_picker_endpoints_require_change_bom_permission_and_validate_search_lengths(self):
        too_long_q = self.client.get(
            "/api/v1/boms/plastic-materials/",
            {"q": "长" * 101},
        )
        too_long_name = self.client.get(
            "/api/v1/boms/packaging-materials/",
            {"material_name": "长" * 201},
        )
        self.assertEqual(too_long_q.status_code, 400, too_long_q.data)
        self.assertEqual(too_long_name.status_code, 400, too_long_name.data)

        self.user.user_permissions.clear()
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)
        urls = (
            "/api/v1/boms/hardware-materials/",
            "/api/v1/boms/hardware-material-groups/",
            "/api/v1/boms/plastic-materials/",
            "/api/v1/boms/plastic-material-groups/",
            "/api/v1/boms/packaging-materials/",
            "/api/v1/boms/packaging-material-groups/",
            "/api/v1/boms/semi-finished-materials/",
            "/api/v1/boms/semi-finished-material-groups/",
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_auxiliary_product_options_expose_pinyin_search(self):
        product = AccessoryProductName.objects.create(
            product_name="卡簧辅料QK6",
            unit_name="个",
        )
        response = self.client.get("/api/v1/boms/editor-reference-options/")
        self.assertEqual(response.status_code, 200, response.data)
        option = next(
            item
            for item in response.data["data"]["auxiliary_products"]
            if item["id"] == str(product.pk)
        )
        self.assertEqual(option["pinyin_search"], "kahuangfuliaoqk6 ka huang fu liao qk6 khflqk6")
