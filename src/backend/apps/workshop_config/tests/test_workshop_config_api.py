from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient, APITestCase

from apps.organizations.models import Employee

from ..models import Craft, CraftType, Operation, PlanCategory, RecordStatus, Workshop, WorkshopEmployee, WorkshopEmployeeStatus


class WorkshopConfigApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="workshop_config_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="WORKSHOP_CONFIG_USER",
            display_name="车间配置测试员",
        )
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label="workshop_config"))
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def fixed_workshop(self, name="装配车间"):
        return Workshop.objects.get(name=name)

    def test_external_embroidery_is_configurable_and_internal_code_is_rejected(self):
        response = self.client.post("/api/v1/workshop-config/crafts/", {
            "craft_type": CraftType.EXTERNAL, "name": "刺绣", "outsourcing_code": "EMBROIDERY",
            "status": RecordStatus.ACTIVE,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["outsourcing_code_display"], "刺绣")
        detail = self.client.get(f'/api/v1/workshop-config/crafts/{response.data["data"]["id"]}/')
        rejected = self.client.patch(f'/api/v1/workshop-config/crafts/{response.data["data"]["id"]}/', {
            "craft_type": CraftType.INTERNAL, "workshop": str(self.fixed_workshop("车缝车间").pk),
        }, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(rejected.status_code, 400, rejected.data)

    def test_workshops_are_fixed_and_read_only(self):
        response = self.client.get("/api/v1/workshop-config/workshops/", {"page_size": 100})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            [item["name"] for item in response.data["data"]],
            ["金工车间", "车缝车间", "装配车间", "敲布孔"],
        )
        create_response = self.client.post(
            "/api/v1/workshop-config/workshops/",
            {"name": "其他车间", "status": RecordStatus.ACTIVE},
            format="json",
        )
        self.assertEqual(create_response.status_code, 405, create_response.data)
        workshop = self.fixed_workshop()
        update_response = self.client.patch(
            f"/api/v1/workshop-config/workshops/{workshop.pk}/",
            {"name": "其他车间"},
            format="json",
        )
        self.assertEqual(update_response.status_code, 405, update_response.data)

    def test_complete_relationship_and_derived_operation_fields(self):
        workshop = self.fixed_workshop()
        source = Employee.objects.create(employee_code="WORKSHOP_CONFIG_SOURCE_1", display_name="测试员工")
        employee = self.client.post(
            "/api/v1/workshop-config/employees/",
            {
                "workshop": str(workshop.pk),
                "position": "装配组长",
                "employee": str(source.pk),
                "is_supervisor": True,
                "status": WorkshopEmployeeStatus.ACTIVE,
            },
            format="json",
        )
        self.assertEqual(employee.status_code, 201, employee.data)
        craft = self.client.post(
            "/api/v1/workshop-config/crafts/",
            {
                "craft_type": CraftType.INTERNAL,
                "workshop": str(workshop.pk),
                "name": "装配/包装",
                "status": RecordStatus.ACTIVE,
            },
            format="json",
        )
        self.assertEqual(craft.status_code, 201, craft.data)
        operation = self.client.post(
            "/api/v1/workshop-config/operations/",
            {
                "operation_number": "gx-test-001",
                "product_name": "测试品",
                "craft": craft.data["data"]["id"],
                "name": "装配",
                "status": RecordStatus.ACTIVE,
                "craft_type": CraftType.EXTERNAL,
                "workshop": None,
            },
            format="json",
        )
        self.assertEqual(operation.status_code, 201, operation.data)
        data = operation.data["data"]
        self.assertEqual(data["operation_number"], "GX-TEST-001")
        self.assertEqual(data["craft_type"], CraftType.INTERNAL)
        self.assertEqual(data["workshop"], str(workshop.pk))
        self.assertEqual(data["workshop_name"], "装配车间")

    def test_partial_employee_status_update_preserves_supervisor_value(self):
        workshop = self.fixed_workshop("车缝车间")
        employee = WorkshopEmployee.objects.create(
            workshop=workshop,
            position="车缝组长",
            name="测试主管",
            is_supervisor=True,
        )
        detail = self.client.get(f"/api/v1/workshop-config/employees/{employee.pk}/")
        response = self.client.patch(
            f"/api/v1/workshop-config/employees/{employee.pk}/",
            {"status": WorkshopEmployeeStatus.LEFT},
            format="json",
            HTTP_IF_MATCH=detail["ETag"],
        )
        self.assertEqual(response.status_code, 200, response.data)
        employee.refresh_from_db()
        self.assertEqual(employee.status, WorkshopEmployeeStatus.LEFT)
        self.assertTrue(employee.is_supervisor)

    def test_metal_operation_does_not_require_product_name_or_reporting_unit(self):
        workshop, _ = Workshop.objects.get_or_create(name="金工车间")
        craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL,
            workshop=workshop,
            name="管材加工",
        )

        response = self.client.post(
            "/api/v1/workshop-config/operations/",
            {
                "operation_number": "GX-METAL-001",
                "craft": str(craft.pk),
                "name": "弯管",
                "status": RecordStatus.ACTIVE,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["product_name"], "")
        self.assertIsNone(response.data["data"]["reporting_unit"])

    def test_non_metal_workshop_cannot_skip_product_name_when_category_is_misconfigured(self):
        workshop = self.fixed_workshop("装配车间")
        invalid_craft = self.client.post(
            "/api/v1/workshop-config/crafts/",
            {
                "craft_type": CraftType.INTERNAL,
                "workshop": str(workshop.pk),
                "name": "错误分类工艺",
                "plan_category": PlanCategory.METAL,
                "status": RecordStatus.ACTIVE,
            },
            format="json",
        )
        self.assertEqual(invalid_craft.status_code, 400, invalid_craft.data)
        self.assertIn("plan_category", invalid_craft.data["error"]["field_errors"])

        craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL,
            workshop=workshop,
            name="错误分类工艺",
            plan_category=PlanCategory.METAL,
        )

        response = self.client.post(
            "/api/v1/workshop-config/operations/",
            {
                "operation_number": "GX-NON-METAL-001",
                "craft": str(craft.pk),
                "name": "装配",
                "status": RecordStatus.ACTIVE,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("product_name", response.data["error"]["field_errors"])

    def test_etag_and_craft_disable_gate(self):
        workshop = self.fixed_workshop("金工车间")
        craft = Craft.objects.create(craft_type=CraftType.INTERNAL, workshop=workshop, name="管材加工")
        Operation.objects.create(operation_number="GX-LOCK-001", product_name="管件", craft=craft, name="切管")
        craft_detail = self.client.get(f"/api/v1/workshop-config/crafts/{craft.pk}/")
        craft_blocked = self.client.patch(
            f"/api/v1/workshop-config/crafts/{craft.pk}/",
            {"status": RecordStatus.INACTIVE},
            format="json",
            HTTP_IF_MATCH=craft_detail["ETag"],
        )
        self.assertEqual(craft_blocked.status_code, 409, craft_blocked.data)

    def test_validation_uniqueness_filters_and_pagination(self):
        workshop = self.fixed_workshop("敲布孔")
        source = Employee.objects.create(employee_code="WORKSHOP_CONFIG_SOURCE_2", display_name="测试员工")
        employee_payload = {
            "workshop": str(workshop.pk),
            "position": "打孔",
            "employee": str(source.pk),
            "is_supervisor": False,
            "status": WorkshopEmployeeStatus.ACTIVE,
        }
        first_employee = self.client.post(
            "/api/v1/workshop-config/employees/",
            employee_payload,
            format="json",
        )
        self.assertEqual(first_employee.status_code, 201, first_employee.data)
        duplicate = self.client.post("/api/v1/workshop-config/employees/", employee_payload, format="json")
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        invalid_external = self.client.post(
            "/api/v1/workshop-config/crafts/",
            {
                "craft_type": CraftType.EXTERNAL,
                "workshop": str(workshop.pk),
                "name": "刺绣",
                "status": RecordStatus.ACTIVE,
            },
            format="json",
        )
        self.assertEqual(invalid_external.status_code, 400, invalid_external.data)
        response = self.client.get("/api/v1/workshop-config/workshops/", {"page": 1, "page_size": 20, "q": "敲"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 1)
        self.assertEqual(response.data["data"][0]["name"], "敲布孔")

    def test_permissions_are_model_scoped(self):
        unauthorized_user = get_user_model().objects.create_user(username="workshop_no_permission")
        Employee.objects.create(
            user=unauthorized_user,
            employee_code="WORKSHOP_NO_PERMISSION",
            display_name="无权限员工",
        )
        client = APIClient()
        client.force_authenticate(unauthorized_user)
        response = client.get("/api/v1/workshop-config/employees/")
        self.assertEqual(response.status_code, 403, response.data)
