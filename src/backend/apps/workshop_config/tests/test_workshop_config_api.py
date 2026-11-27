from apps.workshop_config.tests.factories import production_employee
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.reference_data.models import ProductionUnit

from ..models import Craft, CraftType, Operation, PlanCategory, RecordStatus, Workshop, WorkshopEmployeeStatus


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
                   ACCESS_RESOURCE_SCOPES_ENABLED=True)
class WorkshopOperationScopeTests(ScopedActorMixin, APITestCase):
    base = '/api/v1/workshop-config/'

    def test_operation_access_and_craft_choices_are_limited_to_the_granted_workshop(self):
        self.scoped_actor()
        metal = Workshop.objects.get(name='金工车间')
        assembly = Workshop.objects.get(name='装配车间')
        own_craft = Craft.objects.create(name='本车间工艺', craft_type=CraftType.INTERNAL, workshop=metal,
                                         plan_category=PlanCategory.METAL)
        other_craft = Craft.objects.create(name='其他车间工艺', craft_type=CraftType.INTERNAL, workshop=assembly,
                                           plan_category=PlanCategory.ASSEMBLY)
        own = Operation.objects.create(operation_number='GX-SCOPE-OWN', name='本车间工序', craft=own_craft)
        other = Operation.objects.create(operation_number='GX-SCOPE-OTHER', name='其他车间工序',
                                         craft=other_craft, product_name='测试品名')
        for action in ('view_craft', 'view_operation', 'add_operation', 'change_operation'):
            self.grant(f'workshop_config.{action}', 'WORKSHOP', [metal])

        operations = self.client.get(self.base + 'operations/')
        self.assertEqual(operations.status_code, 200, operations.data)
        self.assertEqual([row['id'] for row in operations.data['data']], [str(own.pk)])
        crafts = self.client.get(self.base + 'crafts/')
        self.assertEqual([row['id'] for row in crafts.data['data']], [str(own_craft.pk)])
        self.assertEqual(self.client.get(self.base + 'operations/summary/').data['data']['total'], 1)
        self.assertEqual(self.client.get(self.base + 'crafts/summary/').data['data']['total'], 1)
        self.assertEqual(self.client.get(self.base + f'operations/{other.pk}/').status_code, 404)

        created = self.client.post(self.base + 'operations/', {'name': '本车间新增', 'craft': own_craft.pk})
        self.assertEqual(created.status_code, 201, created.data)
        blocked = self.client.post(self.base + 'operations/', {
            'name': '其他车间新增', 'craft': other_craft.pk, 'product_name': '测试品名',
        })
        self.assertEqual(blocked.status_code, 403, blocked.data)

        own_url = self.base + f'operations/{own.pk}/'
        current = self.client.get(own_url)
        blocked = self.client.patch(own_url, {'craft': other_craft.pk, 'product_name': '测试品名'}, HTTP_IF_MATCH=current['ETag'])
        self.assertEqual(blocked.status_code, 403, blocked.data)
        edited = self.client.patch(own_url, {'name': '本车间编辑'}, HTTP_IF_MATCH=current['ETag'])
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(self.client.patch(self.base + f'operations/{other.pk}/', {'name': '不能修改'}).status_code, 404)
        self.assertEqual(self.client.patch(self.base + f'crafts/{own_craft.pk}/', {'name': '不能维护工艺'}).status_code, 403)

    def test_copy_scheme_requires_view_and_add_scope_for_its_workshop(self):
        self.scoped_actor()
        assembly = Workshop.objects.get(name='装配车间')
        sewing = Workshop.objects.get(name='车缝车间')
        self.grant('workshop_config.view_operation', 'WORKSHOP', [assembly])
        self.grant('workshop_config.add_operation', 'WORKSHOP', [sewing])

        for workshop in (assembly, sewing):
            craft = Craft.objects.create(name=f'{workshop.name}测试工艺', craft_type=CraftType.INTERNAL, workshop=workshop)
            Operation.objects.create(operation_number=f'OP-COPY-{craft.pk.hex[:8]}', name='定位', craft=craft, product_name='原方案')
            response = self.client.post(self.base + 'operations/copy-scheme/', {
                'craft': str(craft.pk), 'source_name': '原方案', 'target_name': '新方案',
            }, format='json')
            self.assertEqual(response.status_code, 403, response.data)
            self.assertFalse(Operation.objects.filter(craft=craft, product_name='新方案').exists())


class WorkshopConfigApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="workshop_config_user")
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
        employee = production_employee(
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
        self.assertEqual(employee.workshop_status, WorkshopEmployeeStatus.LEFT)
        self.assertTrue(employee.workshop_is_supervisor)

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

    def test_operation_number_is_generated_when_omitted(self):
        workshop = self.fixed_workshop("金工车间")
        craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL,
            workshop=workshop,
            name="自动编号工艺",
        )

        response = self.client.post(
            "/api/v1/workshop-config/operations/",
            {
                "craft": str(craft.pk),
                "name": "自动编号工序",
                "status": RecordStatus.ACTIVE,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        operation_number = response.data["data"]["operation_number"]
        self.assertTrue(operation_number.startswith("OP-"))
        self.assertEqual(Operation.objects.filter(operation_number=operation_number).count(), 1)

    def test_copy_scheme_keeps_all_operations_units_and_statuses_with_new_ids(self):
        craft = Craft.objects.create(craft_type=CraftType.INTERNAL, workshop=self.fixed_workshop(), name="装配复制配置")
        unit = ProductionUnit.objects.create(unit_code="SCHEME-COPY", unit_name="方案复制测试件")
        first = Operation.objects.create(
            craft=craft, product_name="原方案", name="定位", operation_number="OP-COPY-01", reporting_unit=unit,
        )
        second = Operation.objects.create(
            craft=craft, product_name="原方案", name="复检", operation_number="OP-COPY-02", status=RecordStatus.INACTIVE,
        )
        response = self.client.post("/api/v1/workshop-config/operations/copy-scheme/", {
            "craft": str(craft.pk), "source_name": "原方案", "target_name": "新方案",
        }, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["copied_count"], 2)
        copied = Operation.objects.filter(craft=craft, product_name="新方案")
        self.assertCountEqual(copied.values_list("name", "status", "reporting_unit_id"), [
            (first.name, first.status, unit.pk), (second.name, second.status, None),
        ])
        self.assertFalse(copied.filter(operation_number__in=[first.operation_number, second.operation_number]).exists())
        self.assertEqual(Operation.objects.filter(craft=craft, product_name="原方案").count(), 2)
        self.assertEqual(AuditLog.objects.filter(object_type="WORKSHOP_OPERATION", object_id__in=copied.values("pk"), action="CREATED").count(), 2)

    def test_copy_scheme_rejects_same_name_and_existing_target(self):
        craft = Craft.objects.create(craft_type=CraftType.INTERNAL, workshop=self.fixed_workshop(), name="装配复制验重")
        Operation.objects.create(craft=craft, product_name="原方案", name="定位", operation_number="OP-ORIGINAL")
        Operation.objects.create(craft=craft, product_name="目标方案", name="复检", operation_number="OP-EXISTING")
        url = "/api/v1/workshop-config/operations/copy-scheme/"
        for name, code in [("原方案", 400), ("目标方案", 409)]:
            response = self.client.post(url, {"craft": str(craft.pk), "source_name": "原方案", "target_name": name}, format="json")
            self.assertEqual(response.status_code, code, response.data)
        self.assertEqual(Operation.objects.filter(craft=craft).count(), 2)

    def test_copy_scheme_rolls_back_when_a_legacy_operation_cannot_be_copied(self):
        craft = Craft.objects.create(craft_type=CraftType.INTERNAL, workshop=self.fixed_workshop(), name="装配复制回滚")
        Operation.objects.create(craft=craft, product_name="原方案", name="定位", operation_number="OP-ROLLBACK-01")
        Operation.objects.create(craft=craft, product_name="原方案", name="", operation_number="OP-ROLLBACK-02")

        response = self.client.post("/api/v1/workshop-config/operations/copy-scheme/", {
            "craft": str(craft.pk), "source_name": "原方案", "target_name": "新方案",
        }, format="json")

        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Operation.objects.filter(craft=craft, product_name="新方案").exists())
        self.assertFalse(AuditLog.objects.filter(object_type="WORKSHOP_OPERATION", after_data__product_name="新方案").exists())

    def test_operation_update_keeps_internal_number(self):
        workshop = self.fixed_workshop("金工车间")
        craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL,
            workshop=workshop,
            name="编号保持工艺",
        )
        operation = Operation.objects.create(
            operation_number="OP-KEEP-001",
            craft=craft,
            name="原工序",
        )
        detail = self.client.get(f"/api/v1/workshop-config/operations/{operation.pk}/")

        response = self.client.patch(
            f"/api/v1/workshop-config/operations/{operation.pk}/",
            {"name": "更新工序"},
            format="json",
            HTTP_IF_MATCH=detail["ETag"],
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["operation_number"], "OP-KEEP-001")

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
