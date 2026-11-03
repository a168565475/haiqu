import uuid
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.files.models import BusinessFile, FileScanStatus
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.production_scheduling.models import ProductionScheduleProductCraft, ScheduleStatus
from apps.production_tasks.models import ProductionTaskStatus
from apps.workshop_config.constants import FIXED_WORKSHOP_NAMES
from apps.workshop_config.models import Craft, CraftType, PlanCategory, RecordStatus, Workshop
from apps.workshop_config.tests.factories import production_employee
from apps.workshop_reporting.models import WorkshopReportingScope
from apps.workshop_reporting.tests import test_work_report_task_selection as fixtures

from ..selectors import ISSUE_ADD, ISSUE_SUBMIT, ISSUE_VIEW, REPORT_ADD, REPORT_VIEW, plan_links


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class MobilePlanApiTests(APITestCase):
    setUp = fixtures.WorkReportTaskSelectionTests.setUp
    scheme_payload = fixtures.WorkReportTaskSelectionTests.scheme_payload
    create_approved_scheme = fixtures.WorkReportTaskSelectionTests.create_approved_scheme
    create_report = fixtures.WorkReportTaskSelectionTests.create_report
    copy_values = fixtures.WorkReportTaskSelectionTests.copy_values
    copy_row = fixtures.WorkReportTaskSelectionTests.copy_row
    add_product = fixtures.WorkReportTaskSelectionTests.add_product
    add_task = fixtures.WorkReportTaskSelectionTests.add_task
    copy_report = fixtures.WorkReportTaskSelectionTests.copy_report
    url = "/api/v1/workshop-mobile/plans/"
    context_url = "/api/v1/workshop-mobile/context/"

    def detail_url(self, scheduled=None):
        return f"{self.url}{(scheduled or self.schedule_product).pk}/"

    def detail_params(self, workshop=None, category="METAL"):
        return {"plan_category": category, "workshop_id": str((workshop or self.workshop).pk)}

    def scoped_client(self, grants, scope="WORKSHOP"):
        suffix = uuid.uuid4().hex[:10].upper()
        user = get_user_model().objects.create_user(username=f"mobile-{suffix}", password="test")
        employee = Employee.objects.create(user=user, employee_code=f"MOBILE-{suffix}", display_name="手机测试班组长")
        group = Group.objects.create(name=f"MOBILE-{suffix}")
        role = RoleProfile.objects.create(role_code=f"MOBILE_{suffix}", display_name="手机测试班组长", auth_group=group)
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
        for code, workshops in grants.items():
            app, codename = code.split(".")
            permission = Permission.objects.get(content_type__app_label=app, codename=codename)
            group.permissions.add(permission)
            grant = RoleActionGrant.objects.create(role=role, permission=permission, scope=scope)
            for workshop in workshops:
                RoleGrantResource.objects.create(grant=grant, workshop=workshop)
        client = APIClient()
        client.force_authenticate(user)
        return client, user

    def legacy_client(self, codes):
        client, user = self.scoped_client({})
        for code in codes:
            app, codename = code.split(".")
            user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))
        return client, user

    def add_workshop(self):
        workshop, _ = Workshop.objects.get_or_create(name="装配车间")
        craft = Craft.objects.create(craft_type=CraftType.INTERNAL, workshop=workshop, name="手机装配工艺", plan_category=PlanCategory.ASSEMBLY)
        ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product, craft=craft,
            craft_type_snapshot=CraftType.INTERNAL, craft_name_snapshot=craft.name, plan_category=PlanCategory.ASSEMBLY)
        return workshop, craft

    def test_card_keeps_real_plan_identity_and_quantity_without_amounts(self):
        self.create_report()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 1)
        row = response.data["data"][0]
        self.assertEqual(row["schedule_product_id"], str(self.schedule_product.pk))
        self.assertEqual(row["product_line_id"], str(self.product_line.pk))
        self.assertEqual(row["task_number"], self.task.task_number)
        self.assertEqual(Decimal(row["product"]["quantity"]), Decimal("100"))
        self.assertEqual(row["progress"]["percentage"], 1)
        self.assertEqual(Decimal(row["progress"]["reported_quantity"]), Decimal("2"))
        self.assertTrue(row["can_issue"])
        self.assertTrue(row["can_report"])
        self.assertNotIn("amount", str(response.data))
        self.assertNotIn("declared_price", str(response.data))

    def test_issue_only_grant_does_not_reveal_reports_or_cross_workshop(self):
        self.create_report()
        image = BusinessFile.objects.create(original_name="mobile-plan.png", storage_key="mobile-plan.png", content_type="image/png",
            size_bytes=1, uploaded_by_employee=self.employee, scan_status=FileScanStatus.CLEAN)
        self.product_line.image_file = image
        self.product_line.save(update_fields=["image_file"])
        other_workshop, _ = self.add_workshop()
        client, user = self.scoped_client({code: [self.workshop] for code in (ISSUE_VIEW, ISSUE_ADD, ISSUE_SUBMIT)})
        response = client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 1)
        row = response.data["data"][0]
        self.assertTrue(row["can_issue"])
        self.assertFalse(row["can_report"])
        self.assertFalse(row["can_open_report"])
        self.assertFalse(row["can_view_reports"])
        self.assertIsNone(row["progress"])
        self.assertEqual(row["reporting_crafts"], [])
        self.assertIn("/material-issues/product-images/", row["product"]["image_url"])
        report_image = self.client.get(self.url).data["data"][0]["product"]["image_url"]
        self.assertIn("/work-report-tasks/", report_image)
        self.assertFalse(user.has_perm("production_scheduling.view_productionschedule"))
        detail = client.get(self.detail_url(), self.detail_params())
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertIn(str(self.worker.pk), [item["id"] for item in detail.data["data"]["recipients"]])
        self.assertEqual(detail.data["data"]["reporting_employees"], [])
        self.assertEqual(client.get(self.detail_url(), self.detail_params(other_workshop, "ASSEMBLY")).status_code, 404)
        image.scan_status = FileScanStatus.INFECTED
        image.save(update_fields=["scan_status"])
        self.assertIsNone(client.get(self.url).data["data"][0]["product"]["image_url"])

    def test_read_scope_cannot_borrow_write_scope_or_other_module_scope(self):
        other_workshop, _ = self.add_workshop()
        client, _ = self.scoped_client({ISSUE_VIEW: [self.workshop], ISSUE_ADD: [other_workshop], ISSUE_SUBMIT: [other_workshop], REPORT_VIEW: [other_workshop]})
        response = client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        metal = next(row for row in response.data["data"] if row["plan_category"] == "METAL")
        assembly = next(row for row in response.data["data"] if row["plan_category"] == "ASSEMBLY")
        self.assertFalse(metal["can_issue"])
        self.assertIsNone(metal["progress"])
        self.assertFalse(assembly["can_view_issues"])
        self.assertFalse(assembly["can_issue"])

    def test_empty_resources_cannot_select_any_plan(self):
        client, _ = self.scoped_client({ISSUE_VIEW: [], REPORT_VIEW: []})
        response = client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"], [])
        self.assertEqual(client.get(self.detail_url(), self.detail_params()).status_code, 404)

    def test_report_view_and_add_are_separate_and_people_are_workshop_scoped(self):
        self.create_approved_scheme()
        other_workshop, _ = self.add_workshop()
        other_worker = production_employee(workshop=other_workshop, position="操作工", name="其他车间员工", is_supervisor=False)
        client, user = self.scoped_client({REPORT_VIEW: [self.workshop], REPORT_ADD: [other_workshop]})
        response = client.get(self.detail_url(), self.detail_params())
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertFalse(data["can_report"])
        self.assertFalse(data["can_open_report"])
        self.assertIsNotNone(data["progress"])
        self.assertEqual(data["recipients"], [])
        self.assertIn(str(self.worker.pk), [item["id"] for item in data["reporting_employees"]])
        self.assertNotIn(str(other_worker.pk), [item["id"] for item in data["reporting_employees"]])
        self.assertFalse(user.has_perm("production_tasks.view_productiontask"))

    def test_missing_scheme_completion_and_task_state_are_explicit(self):
        missing = self.client.get(self.url).data["data"][0]
        self.assertFalse(missing["can_report"])
        self.assertTrue(missing["can_open_report"])
        self.assertIsNone(missing["progress"]["percentage"])
        self.assertIn("已批准", missing["report_reason"])
        self.create_approved_scheme()
        self.task.status = ProductionTaskStatus.PAUSED
        self.task.save(update_fields=["status", "updated_at"])
        paused = self.client.get(self.url).data["data"][0]
        self.assertFalse(paused["can_issue"])
        # 既有报工服务允许暂停任务补报，手机读取不能暗加新业务限制。
        self.assertTrue(paused["can_report"])
        scheme = self.client.get("/api/v1/workshop-reporting/work-reports/price-context/", {
            "product_line_id": str(self.product_line.pk), "schedule_product_id": str(self.schedule_product.pk),
            "workshop_id": str(self.workshop.pk), "craft_id": str(self.craft.pk), "production_date": timezone.localdate().isoformat(),
        }).data["data"]
        saved = self.client.post("/api/v1/workshop-reporting/work-reports/", {
            "client_request_id": str(uuid.uuid4()), "production_date": timezone.localdate().isoformat(),
            "schedule_product_id": str(self.schedule_product.pk), "scheme_id": scheme["id"], "scheme_revision": scheme["revision"],
            "confirm_plan_completion": True,
            "lines": [{"scheme_line_id": scheme["lines"][0]["id"], "workshop_employee_id": str(self.worker.pk), "quantity": "200"}],
        }, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        completed = self.client.get(self.url).data["data"][0]
        self.assertFalse(completed["can_report"])
        self.assertFalse(completed["can_open_report"])
        self.assertIn("完成", completed["report_reason"])

    def test_search_filters_pagination_and_removed_sources(self):
        task, _, _, _ = self.add_task()
        first = self.client.get(self.url, {"page_size": 1})
        second = self.client.get(self.url, {"page_size": 1, "page": 2})
        self.assertEqual(first.data["meta"]["total"], 2)
        self.assertNotEqual(first.data["data"][0]["key"], second.data["data"][0]["key"])
        searched = self.client.get(self.url, {"search": task.task_number})
        self.assertEqual([row["production_task_id"] for row in searched.data["data"]], [str(task.pk)])
        self.assertEqual(self.client.get(self.url, {"status": "IN_PRODUCTION"}).data["meta"]["total"], 1)
        self.schedule.record_status = ScheduleStatus.VOID
        self.schedule.version += 1
        self.schedule.void_reason = "手机定向测试"
        self.schedule.voided_at = timezone.now()
        self.schedule.voided_by_employee = self.employee
        self.schedule.save()
        self.assertEqual(self.client.get(self.detail_url(), self.detail_params()).status_code, 404)

    def test_input_and_authentication_boundaries(self):
        anonymous = APIClient()
        self.assertEqual(anonymous.get(self.url).status_code, 401)
        client, _ = self.scoped_client({})
        self.assertEqual(client.get(self.url).status_code, 403)
        for params in ({"page_size": 101}, {"page": 0}, {"workshop_id": "invalid"}, {"plan_category": "INVALID"},
                       {"status": "INVALID"}, {"production_date": "not-a-date"}, {"search": "x" * 201}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 400)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 400)
        self.assertEqual(self.client.get(f"{self.url}{uuid.uuid4()}/", self.detail_params()).status_code, 404)

    def test_cards_do_not_add_queries_per_product(self):
        self.client.get(self.url)
        with CaptureQueriesContext(connection) as baseline:
            self.client.get(self.url)
        for number in range(2, 12):
            self.add_product(self.task, self.schedule, number)
        with CaptureQueriesContext(connection) as expanded:
            response = self.client.get(self.url)
        self.assertEqual(response.data["meta"]["total"], 11)
        self.assertLessEqual(len(expanded), len(baseline) + 2)

    def test_disappearing_scope_between_pagination_and_read_is_safe(self):
        for detail in (False, True):
            with self.subTest(detail=detail), patch("apps.workshop_mobile.selectors.visible_plan_links", side_effect=[plan_links(), plan_links().none()]):
                response = self.client.get(self.detail_url() if detail else self.url, self.detail_params() if detail else {})
                if detail:
                    self.assertEqual(response.status_code, 404, response.data)
                else:
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.data["data"], [])

    def test_price_context_isolates_selected_schedule_but_preserves_legacy_total(self):
        original_report = self.create_report()
        self.schedule.record_status = ScheduleStatus.VOID
        self.schedule.version += 1
        self.schedule.void_reason = "手机累计隔离测试"
        self.schedule.voided_at = timezone.now()
        self.schedule.voided_by_employee = self.employee
        self.schedule.save()
        self.task.status = ProductionTaskStatus.READY
        self.task.save(update_fields=["status", "updated_at"])
        new_schedule = self.copy_row(self.schedule, schedule_number="PC-MOBILE-NEW", record_status=ScheduleStatus.ACTIVE,
            client_request_id=uuid.uuid4(), void_reason="", voided_at=None, voided_by_employee_id=None)
        new_product = self.copy_row(self.schedule_product, schedule_id=new_schedule.pk)
        ProductionScheduleProductCraft.objects.create(schedule_product=new_product, craft=self.craft,
            craft_type_snapshot=CraftType.INTERNAL, craft_name_snapshot=self.craft.name, plan_category=PlanCategory.METAL)
        self.copy_report(original_report, scheduled=new_product, quantity="3")
        self.task.status = ProductionTaskStatus.IN_PRODUCTION
        self.task.save(update_fields=["status", "updated_at"])
        url = "/api/v1/workshop-reporting/work-reports/price-context/"
        params = {"product_line_id": str(self.product_line.pk), "workshop_id": str(self.workshop.pk),
                  "craft_id": str(self.craft.pk), "production_date": timezone.localdate().isoformat()}
        legacy = self.client.get(url, params)
        self.assertEqual(legacy.status_code, 200, legacy.data)
        self.assertEqual(Decimal(legacy.data["data"]["lines"][0]["cumulative_quantity"]), Decimal("5"))
        selected = self.client.get(url, {**params, "schedule_product_id": str(new_product.pk)})
        self.assertEqual(selected.status_code, 200, selected.data)
        self.assertEqual(Decimal(selected.data["data"]["lines"][0]["cumulative_quantity"]), Decimal("3"))
        self.assertEqual(Decimal(selected.data["data"]["lines"][0]["production_date_quantity"]), Decimal("3"))
        self.assertEqual(self.client.get(url, {**params, "schedule_product_id": str(uuid.uuid4())}).status_code, 404)

    def test_report_history_category_uses_schedule_snapshot_and_preserves_old_contract(self):
        report = self.create_report()
        url = "/api/v1/workshop-reporting/work-reports/"
        params = {"schedule_product_id": str(self.schedule_product.pk), "workshop_id": str(self.workshop.pk)}
        for category in (None, "METAL"):
            query = params if category is None else {**params, "plan_category": category}
            response = self.client.get(url, query)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual([row["id"] for row in response.data["data"]], [str(report.pk)])
        self.assertEqual(self.client.get(url, {**params, "plan_category": "CUTTING"}).data["data"], [])
        self.assertEqual(self.client.get(url, {**params, "plan_category": "INVALID"}).status_code, 400)
        self.add_workshop()
        self.schedule_product.crafts.filter(craft=self.craft).update(
            removed_at=timezone.now(), removed_by_employee=self.employee,
        )
        response = self.client.get(url, {**params, "plan_category": "METAL"})
        self.assertEqual([row["id"] for row in response.data["data"]], [str(report.pk)])

    def test_superuser_context_includes_active_workshops_without_plans_and_keeps_list_contract(self):
        empty_workshop, _ = Workshop.objects.get_or_create(name="车缝车间")
        Workshop.objects.get_or_create(name="敲布孔")
        response = self.client.get(self.context_url)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]["workshop_filter"]
        self.assertTrue(data["enabled"])
        names = [item["name"] for item in data["options"]]
        expected = [name for name in FIXED_WORKSHOP_NAMES if Workshop.objects.filter(name=name, status=RecordStatus.ACTIVE).exists()]
        self.assertEqual(names, expected)
        self.assertIn(str(empty_workshop.pk), [item["id"] for item in data["options"]])
        self.assertEqual(data["default_id"], str(self.workshop.pk))
        self.assertEqual(self.client.get(self.url, {"workshop_id": str(empty_workshop.pk)}).data["data"], [])
        self.add_workshop()
        self.assertEqual(self.client.get(self.url).data["meta"]["total"], 2)

    def test_module_read_scope_enables_switch_without_granting_write_actions(self):
        for permission in (ISSUE_VIEW, REPORT_VIEW):
            with self.subTest(permission=permission):
                client, _ = self.scoped_client({permission: []}, scope="MODULE")
                response = client.get(self.context_url)
                self.assertEqual(response.status_code, 200, response.data)
                data = response.data["data"]["workshop_filter"]
                self.assertTrue(data["enabled"])
                self.assertEqual(len(data["options"]), Workshop.objects.filter(status=RecordStatus.ACTIVE).count())
                row = client.get(self.url).data["data"][0]
                self.assertFalse(row["can_issue"])
                self.assertFalse(row["can_open_report"])

    def test_workshop_only_single_multiple_and_empty_scopes_hide_switch(self):
        other_workshop, _ = self.add_workshop()
        for workshops in ([], [self.workshop], [self.workshop, other_workshop]):
            with self.subTest(count=len(workshops)):
                client, _ = self.scoped_client({ISSUE_VIEW: workshops, REPORT_VIEW: workshops})
                response = client.get(self.context_url)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["data"]["workshop_filter"], {"enabled": False, "options": [], "default_id": None})
                self.assertEqual(client.get(self.url).data["meta"]["total"], len(workshops))

    def test_context_rejects_missing_view_permission_and_inactive_identity(self):
        self.assertEqual(APIClient().get(self.context_url).status_code, 401)
        for grants in ({}, {ISSUE_ADD: []}, {REPORT_ADD: []}):
            client, _ = self.scoped_client(grants, scope="MODULE")
            self.assertEqual(client.get(self.context_url).status_code, 403)
        client, user = self.scoped_client({ISSUE_VIEW: []}, scope="MODULE")
        user.is_active = False
        user.save(update_fields=["is_active"])
        self.assertEqual(client.get(self.context_url).status_code, 403)
        for inactive_field in ("status", "archived_at"):
            client, user = self.scoped_client({ISSUE_VIEW: []}, scope="MODULE")
            employee = user.employee_profile
            setattr(employee, inactive_field, "INACTIVE" if inactive_field == "status" else timezone.now())
            employee.save(update_fields=[inactive_field])
            self.assertEqual(client.get(self.context_url).status_code, 403)

    def test_wide_write_scope_does_not_enable_read_switch(self):
        client, user = self.scoped_client({ISSUE_VIEW: [self.workshop], REPORT_ADD: []})
        RoleActionGrant.objects.filter(role__employee_assignments__employee__user=user,
            permission__codename="add_workreport").update(scope="MODULE")
        self.assertFalse(client.get(self.context_url).data["data"]["workshop_filter"]["enabled"])

    def test_legacy_reporting_global_scope_differs_from_assigned_workshops(self):
        client, user = self.legacy_client([REPORT_VIEW])
        WorkshopReportingScope.objects.create(employee=user.employee_profile, workshop=self.workshop,
            created_by_employee=self.employee)
        self.assertFalse(client.get(self.context_url).data["data"]["workshop_filter"]["enabled"])
        global_client, _ = self.legacy_client([REPORT_VIEW, "workshop_reporting.view_all_workreport"])
        response = global_client.get(self.context_url)
        self.assertTrue(response.data["data"]["workshop_filter"]["enabled"])
        self.assertEqual(len(response.data["data"]["workshop_filter"]["options"]), Workshop.objects.filter(status=RecordStatus.ACTIVE).count())

    def test_legacy_issue_switch_follows_task_scope_not_issue_view_all_name(self):
        client, _ = self.legacy_client([ISSUE_VIEW, "material_issues.view_all_materialissue"])
        self.assertFalse(client.get(self.context_url).data["data"]["workshop_filter"]["enabled"])
        self.assertEqual(client.get(self.url).data["data"], [])
        global_client, _ = self.legacy_client([ISSUE_VIEW, "production_tasks.view_all_productiontask"])
        self.assertTrue(global_client.get(self.context_url).data["data"]["workshop_filter"]["enabled"])
        self.assertEqual(global_client.get(self.url).data["meta"]["total"], 1)

    @override_settings(MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
    def test_legacy_context_when_resource_switches_are_disabled(self):
        client, _ = self.legacy_client([ISSUE_VIEW])
        self.assertFalse(client.get(self.context_url).data["data"]["workshop_filter"]["enabled"])
        for codes in ([ISSUE_VIEW, "production_tasks.view_all_productiontask"],
                      [REPORT_VIEW, "workshop_reporting.view_all_workreport"]):
            client, _ = self.legacy_client(codes)
            self.assertTrue(client.get(self.context_url).data["data"]["workshop_filter"]["enabled"])

    def test_manual_workshop_filter_cannot_expand_scoped_list_or_context(self):
        other_workshop, _ = self.add_workshop()
        client, _ = self.scoped_client({ISSUE_VIEW: [self.workshop], REPORT_VIEW: [self.workshop]})
        response = client.get(self.context_url, {"workshop_id": str(other_workshop.pk)})
        self.assertEqual(response.data["data"]["workshop_filter"], {"enabled": False, "options": [], "default_id": None})
        self.assertEqual(client.get(self.url, {"workshop_id": str(other_workshop.pk)}).data["data"], [])
        self.assertEqual(client.get(self.url, {"workshop_id": "invalid"}).status_code, 400)
        self.assertEqual(client.get(self.detail_url(), self.detail_params(other_workshop, "ASSEMBLY")).status_code, 404)
