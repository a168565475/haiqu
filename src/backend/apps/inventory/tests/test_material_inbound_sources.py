"""一般入库选料权限与目录维护权限相互独立。"""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.material_catalog.models import MaterialCatalog
from apps.reference_data.models import MaterialAttributePublicValue

from ..models import MaterialInbound, PublicStockBalance
from .test_general_manual_receipts import GeneralManualReceiptTests


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=False, PUBLIC_STOCK_FLOW_ENABLED=True)
class MaterialInboundSourceTests(APITestCase):
    item = GeneralManualReceiptTests.item
    payload = GeneralManualReceiptTests.payload
    post = GeneralManualReceiptTests.post
    assert_no_inventory_written = GeneralManualReceiptTests.assert_no_inventory_written

    def setUp(self):
        GeneralManualReceiptTests.setUp(self)
        self.permission = Permission.objects.get(content_type__app_label="inventory", codename="receive_material")
        self.user.user_permissions.set([self.permission])
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)
        self.public_value = MaterialAttributePublicValue.objects.create(
            category_key="HARDWARE", template_key="HARDWARE", scope="BASE", field_key="specification", value="M8",
        )
        self.root = "/api/v1/material-inbound-sources/"
        self.reads = [
            ("", {}), ("options/", {}), (f"{self.catalog.pk}/", {}),
            ("public-options/", {"category_key": "HARDWARE", "template_key": "HARDWARE"}),
        ]

    def test_receiver_can_read_selection_sources_without_catalog_access(self):
        self.assertFalse(self.user.has_perm("material_catalog.view_materialcatalog"))
        for suffix, query in self.reads:
            with self.subTest(suffix=suffix):
                response = self.client.get(self.root + suffix, query)
                self.assertEqual(response.status_code, 200, getattr(response, "data", response.status_code))
        options = self.client.get(self.root + "options/").data["data"]
        self.assertEqual({row["key"] for row in options["categories"]}, {
            "TUBE", "FABRIC", "HARDWARE", "PLASTIC", "PACKAGING", "AUXILIARY",
        })
        self.assertEqual(options["warehouses"], [])
        self.assertEqual(options["spray_fields"], [])
        for suffix, query in self.reads:
            with self.subTest(catalog=suffix):
                self.assertEqual(self.client.get("/api/v1/material-catalog/" + suffix, query).status_code, 403)

    def test_receiver_can_submit_existing_public_values_without_catalog_permission(self):
        response = self.post(self.payload(self.item(), self.item(quantity="3.0000")))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(MaterialInbound.objects.get().lines.count(), 2)
        self.assertEqual(str(PublicStockBalance.objects.get().quantity), "5.5000")
        self.assertEqual(MaterialAttributePublicValue.objects.filter(category_key="HARDWARE").count(), 1)

    def test_receiver_cannot_create_public_values_through_receipt(self):
        response = self.post(self.payload(self.item(), self.item(specification="未维护规格-入库拒绝")))
        # 目录维护闸在选料校验阶段以字段校验错误拒绝未维护公共值；不创建主档属性。
        self.assertEqual(response.status_code, 400, response.data)
        self.assert_no_inventory_written()
        self.assertFalse(self.catalog.attribute_values.exists())
        self.assertFalse(MaterialAttributePublicValue.objects.filter(value="未维护规格-入库拒绝").exists())

    def test_sources_limit_raw_categories_scope_and_validate_input(self):
        cutting = MaterialCatalog.objects.create(category_key="FABRIC_SEMI", template_key="FABRIC_SEMI", name="不可手工入库裁片")
        rows = self.client.get(self.root).data["data"]
        self.assertNotIn(str(cutting.pk), {row["id"] for row in rows})
        self.assertEqual(self.client.get(self.root + f"{cutting.pk}/").status_code, 404)
        # 路由 UUID 转换器在进入 ViewSet 前返回 404。
        self.assertEqual(self.client.get(self.root + "not-a-uuid/").status_code, 404)
        for category in ("FABRIC_SEMI", "INVALID"):
            self.assertEqual(self.client.get(self.root, {"category": category}).status_code, 400)
            self.assertEqual(self.client.get(self.root + "public-options/", {
                "category_key": category, "template_key": category,
            }).status_code, 400)
        for query in ({"category_key": "HARDWARE"}, {
            "category_key": "HARDWARE", "template_key": "TUBE",
        }, {"category_key": "HARDWARE", "template_key": "HARDWARE", "scope": "SPRAY"}):
            self.assertEqual(self.client.get(self.root + "public-options/", query).status_code, 400)
        self.catalog.archived_at = timezone.now()
        self.catalog.save(update_fields=["archived_at"])
        self.assertEqual(self.client.get(self.root + f"{self.catalog.pk}/").status_code, 404)

    def test_receiver_cannot_write_sources_or_catalog(self):
        for method, suffix in (("post", ""), ("put", f"{self.catalog.pk}/"),
                               ("patch", f"{self.catalog.pk}/"), ("delete", f"{self.catalog.pk}/")):
            with self.subTest(source_method=method):
                self.assertIn(getattr(self.client, method)(self.root + suffix, {}, format="json").status_code, (403, 405))
        detail = f"{self.catalog.pk}/"
        writes = [("post", ""), ("put", detail), ("patch", detail), ("delete", detail)]
        for child in ("values", "units"):
            writes.extend([("post", f"{detail}{child}/"), ("patch", f"{detail}{child}/{uuid4()}/"),
                           ("delete", f"{detail}{child}/{uuid4()}/")])
        for method, suffix in writes:
            with self.subTest(catalog_method=method, suffix=suffix):
                response = getattr(self.client, method)("/api/v1/material-catalog/" + suffix, {}, format="json")
                self.assertEqual(response.status_code, 403)
        self.assert_no_inventory_written()

    def test_missing_receive_permission_and_inactive_employee_are_denied(self):
        for state in ("no_permission", "inactive_employee", "anonymous"):
            if state == "no_permission":
                self.user.user_permissions.clear()
            elif state == "inactive_employee":
                self.user.user_permissions.add(self.permission)
                self.employee.status = "INACTIVE"
                self.employee.save(update_fields=["status"])
            self.client.force_authenticate(None if state == "anonymous" else get_user_model().objects.get(pk=self.user.pk))
            for suffix, query in self.reads:
                with self.subTest(state=state, suffix=suffix):
                    self.assertIn(self.client.get(self.root + suffix, query).status_code, (401, 403))
            self.assertIn(self.post(self.payload(self.item())).status_code, (401, 403))
        self.assert_no_inventory_written()
