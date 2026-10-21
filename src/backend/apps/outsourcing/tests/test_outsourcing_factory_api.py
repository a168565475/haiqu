from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient, APITestCase

from apps.organizations.models import Employee
from apps.workshop_config.models import Craft, CraftType, OutsourcingCode, RecordStatus

from ..models import FactoryStatus, OutsourcingFactory


class OutsourcingFactoryApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="outsourcing_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="OUTSOURCING_USER",
            display_name="委外测试员",
        )
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label="outsourcing"))
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.sewing = Craft.objects.create(
            craft_type=CraftType.EXTERNAL,
            name="车缝",
            outsourcing_code=OutsourcingCode.SEWING,
            status=RecordStatus.ACTIVE,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        self.cutting = Craft.objects.create(
            craft_type=CraftType.EXTERNAL,
            name="裁剪",
            outsourcing_code=OutsourcingCode.CUTTING,
            status=RecordStatus.ACTIVE,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )

    def payload(self, **overrides):
        data = {
            "craft_ids": [str(self.sewing.pk)],
            "name": "锦程加工厂",
            "processing_type": "椅面、扶手",
            "estimated_output": "1000",
            "estimated_output_unit": "",
            "estimated_output_period": "",
            "contact_name": "张师傅",
            "contact_phone": "13800000186",
            "address": "城南工业区",
            "remark": "擅长椅面与扶手",
            "payment_cycle": "MONTHLY",
        }
        data.update(overrides)
        return data

    def test_create_list_filter_update_and_disable(self):
        created = self.client.post("/api/v1/outsourcing-factories/", self.payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        factory_id = created.data["data"]["id"]
        self.assertEqual(created.data["data"]["crafts"][0]["name"], "车缝")
        self.assertTrue(created["ETag"])

        listed = self.client.get("/api/v1/outsourcing-factories/", {"search": "锦程", "craft_id": self.sewing.pk})
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(listed.data["meta"]["total"], 1)

        missing_etag = self.client.patch(
            f"/api/v1/outsourcing-factories/{factory_id}/",
            self.payload(craft_ids=[str(self.cutting.pk)]),
            format="json",
        )
        self.assertEqual(missing_etag.status_code, 428, missing_etag.data)

        multi_craft = self.client.patch(
            f"/api/v1/outsourcing-factories/{factory_id}/",
            self.payload(craft_ids=[str(self.sewing.pk), str(self.cutting.pk)]),
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(multi_craft.status_code, 400, multi_craft.data)

        updated = self.client.patch(
            f"/api/v1/outsourcing-factories/{factory_id}/",
            self.payload(craft_ids=[str(self.cutting.pk)], name="锦程二厂"),
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual([item["name"] for item in updated.data["data"]["crafts"]], ["裁剪"])

        stale = self.client.patch(
            f"/api/v1/outsourcing-factories/{factory_id}/",
            self.payload(name="过期写入"),
            format="json",
            HTTP_IF_MATCH=created["ETag"],
        )
        self.assertEqual(stale.status_code, 412, stale.data)

        related = self.client.get(f"/api/v1/outsourcing-factories/{factory_id}/related-orders/")
        self.assertEqual(related.status_code, 200, related.data)
        self.assertEqual(related.data["meta"]["total"], 0)

        disabled = self.client.post(
            f"/api/v1/outsourcing-factories/{factory_id}/disable/",
            {},
            format="json",
            HTTP_IF_MATCH=updated["ETag"],
        )
        self.assertEqual(disabled.status_code, 200, disabled.data)
        self.assertEqual(disabled.data["data"]["status"], FactoryStatus.DISABLED)
        self.assertEqual(OutsourcingFactory.objects.get(pk=factory_id).version, 3)

    def test_invalid_craft_and_embroidery_are_rejected(self):
        inactive = Craft.objects.create(
            craft_type=CraftType.EXTERNAL,
            name="停用丝印",
            status=RecordStatus.INACTIVE,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        response = self.client.post(
            "/api/v1/outsourcing-factories/", self.payload(craft_ids=[str(inactive.pk)]), format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

        options = self.client.get("/api/v1/outsourcing-factories/options/")
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual({item["name"] for item in options.data["data"]["crafts"]}, {"车缝", "裁剪"})

        unsupported = Craft.objects.create(
            craft_type=CraftType.EXTERNAL,
            name="热转印",
            status=RecordStatus.ACTIVE,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        response = self.client.post(
            "/api/v1/outsourcing-factories/", self.payload(craft_ids=[str(unsupported.pk)]), format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

        embroidery = Craft.objects.create(
            craft_type=CraftType.EXTERNAL,
            name="刺绣",
            status=RecordStatus.ACTIVE,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        response = self.client.post(
            "/api/v1/outsourcing-factories/", self.payload(craft_ids=[str(embroidery.pk)]), format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_embroidery_factory_is_supported_but_not_legacy_raw_fabric_order(self):
        embroidery = Craft.objects.create(craft_type=CraftType.EXTERNAL, name="刺绣",
            outsourcing_code=OutsourcingCode.EMBROIDERY, status=RecordStatus.ACTIVE,
            created_by_employee=self.employee, updated_by_employee=self.employee)
        options = self.client.get("/api/v1/outsourcing-factories/options/")
        self.assertEqual(options.status_code, 200, options.data)
        self.assertIn(str(embroidery.pk), {str(row["id"]) for row in options.data["data"]["crafts"]})
        created = self.client.post("/api/v1/outsourcing-factories/",
            self.payload(craft_ids=[str(embroidery.pk)]), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["crafts"][0]["name"], "刺绣")
        legacy = self.client.get("/api/v1/outsourcing-orders/options/")
        self.assertEqual(legacy.status_code, 200, legacy.data)
        self.assertNotIn(str(embroidery.pk), {str(row["id"]) for row in legacy.data["data"]["crafts"]})

    def test_factory_permissions_are_model_scoped(self):
        user = get_user_model().objects.create_user(username="outsourcing_no_permission")
        Employee.objects.create(user=user, employee_code="OUTSOURCING_NONE", display_name="无权限员工")
        client = APIClient()
        client.force_authenticate(user)
        response = client.get("/api/v1/outsourcing-factories/")
        self.assertEqual(response.status_code, 403, response.data)

    def test_factory_and_order_read_permissions_remain_separate(self):
        created = self.client.post("/api/v1/outsourcing-factories/", self.payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        factory_id = created.data["data"]["id"]

        factory_user = get_user_model().objects.create_user(username="factory_reader")
        Employee.objects.create(user=factory_user, employee_code="FACTORY_READER", display_name="工厂资料查看员")
        factory_user.user_permissions.add(Permission.objects.get(
            codename="view_outsourcingfactory", content_type__app_label="outsourcing"
        ))
        factory_client = APIClient()
        factory_client.force_authenticate(factory_user)
        self.assertEqual(factory_client.get(f"/api/v1/outsourcing-factories/{factory_id}/").status_code, 200)
        self.assertEqual(
            factory_client.get(f"/api/v1/outsourcing-factories/{factory_id}/related-orders/").status_code,
            403,
        )

        order_user = get_user_model().objects.create_user(username="order_reader")
        Employee.objects.create(user=order_user, employee_code="ORDER_READER", display_name="外发单查看员")
        order_user.user_permissions.add(Permission.objects.get(
            codename="view_outsourcingorder", content_type__app_label="outsourcing"
        ))
        order_client = APIClient()
        order_client.force_authenticate(order_user)
        options = order_client.get("/api/v1/outsourcing-orders/options/")
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual(set(options.data["data"]["factories"][0]), {"id", "name", "crafts"})
