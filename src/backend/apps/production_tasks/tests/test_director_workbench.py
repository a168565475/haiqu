from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.inventory.tests import test_assembly_receipts as assembly_tests
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft, Workshop
from apps.workshop_reporting.models import WorkshopPlanExecution
from apps.workshop_reporting.tests import test_work_report_task_selection as reporting_tests


URL = "/api/v1/workshop-director-workbench/"
SCHEDULE = "production_scheduling.view_productionschedule"
REPORT = "workshop_reporting.view_workreport"
SCHEME = "workshop_reporting.view_wagescheme"
RECEIPT = "inventory.view_finishedgoodsreceipt"


def assign_role(employee, role_code, permissions, workshop=None):
    group, _ = Group.objects.get_or_create(name="DirectorTest-" + role_code)
    role, _ = RoleProfile.objects.get_or_create(role_code=role_code, defaults={"auth_group": group, "display_name": role_code})
    EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
    for code in permissions:
        app, codename = code.split(".")
        permission = Permission.objects.get(content_type__app_label=app, codename=codename)
        grant, _ = RoleActionGrant.objects.get_or_create(role=role, permission=permission, scope="WORKSHOP" if workshop else "MODULE")
        if workshop:
            RoleGrantResource.objects.get_or_create(grant=grant, workshop=workshop)
    return role


def director(code, workshop, permissions):
    user = get_user_model().objects.create_user(username="test-" + code)
    employee = Employee.objects.create(user=user, employee_code=code, display_name=code)
    role = assign_role(employee, code, permissions, workshop)
    client = APIClient()
    client.force_authenticate(user)
    return client, employee, role


@override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class DirectorWorkbenchTests(APITestCase):
    fixture = reporting_tests.WorkReportTaskSelectionTests
    setUp = fixture.setUp
    scheme_payload = fixture.scheme_payload
    create_approved_scheme = fixture.create_approved_scheme
    create_report = fixture.create_report
    copy_row = fixture.copy_row
    copy_values = fixture.copy_values
    copy_report = fixture.copy_report
    add_product = fixture.add_product

    def link(self, category, workshop):
        craft = Craft.objects.create(craft_type="INTERNAL", workshop=workshop, name="测试" + category + workshop.name,
                                     plan_category=category)
        return ProductionScheduleProductCraft.objects.create(schedule_product=self.schedule_product, craft=craft,
            craft_type_snapshot="INTERNAL", craft_name_snapshot=craft.name, plan_category=category)

    def test_craft_scope_and_explicit_role_gate_on_all_endpoints(self):
        sewing, _ = Workshop.objects.get_or_create(name="车缝车间")
        cutting = self.link("CUTTING", sewing)
        self.link("SEWING", self.workshop)
        metal = self.schedule_product.crafts.get(craft=self.craft)
        viewer, employee, role = director("METAL_DIRECTOR", self.workshop, [SCHEDULE, REPORT])
        assign_role(employee, "DIRECTOR_TEST_PMC", [SCHEDULE, REPORT])
        overview = viewer.get(URL)
        self.assertEqual(overview.status_code, 200, overview.data)
        self.assertEqual(overview.data["data"]["workshops"], ["METAL"])
        self.assertEqual(overview.data["data"]["counts"]["planned"], 1)
        self.assertEqual(viewer.get(URL + "detail/", {"id": cutting.pk}).status_code, 404)
        for endpoint, extra in (("", {}), ("items/", {"category": "planned"}), ("detail/", {"id": cutting.pk}),
                                ("activity/", {"period": "year"})):
            self.assertEqual(viewer.get(URL + endpoint, {"workshop": "SEWING", **extra}).status_code, 403)
        self.assertEqual(viewer.get(URL, {"workshop": "OTHER"}).status_code, 400)
        self.assertEqual(viewer.get(URL + "items/", {"category": "day"}).status_code, 400)
        self.assertEqual(viewer.get(URL + "items/", {"category": "week", "date": timezone.localdate()}).status_code, 400)
        self.assertEqual(viewer.get(URL + "items/", {"category": "planned", "page_size": 0}).status_code, 400)
        self.assertEqual(viewer.get(URL + "detail/", {"id": metal.pk}).status_code, 200)
        assign_role(employee, "SEWING_DIRECTOR", [SCHEDULE, REPORT], sewing)
        self.assertEqual(viewer.get(URL).data["data"]["workshops"], ["METAL", "SEWING"])
        self.assertEqual(viewer.get(URL, {"workshop": "SEWING"}).data["data"]["counts"]["planned"], 1)
        EmployeeRoleAssignment.objects.filter(employee=employee, role_profile=role).update(effective_to=timezone.now())
        self.assertEqual(viewer.get(URL, {"workshop": "METAL"}).status_code, 403)
        other, _, _ = director("DIRECTOR_TEST_OTHER", self.workshop, [SCHEDULE, REPORT])
        self.assertEqual(other.get(URL).status_code, 403)
        self.assertEqual(APIClient().get(URL).status_code, 401)
        self.assertEqual(self.client.get(URL).data["data"]["workshops"], ["ASSEMBLY", "METAL", "SEWING"])
        assign_role(self.employee, "METAL_DIRECTOR", [SCHEDULE], self.workshop)
        self.assertEqual(self.client.get(URL).data["data"]["workshops"], ["METAL"])

    def test_reports_must_belong_to_this_plan_craft_dates_units_and_period(self):
        report = self.create_report()
        _, planned_product = self.add_product(self.task, self.schedule, 2)
        viewer, _, _ = director("METAL_DIRECTOR", self.workshop, [SCHEDULE, REPORT, SCHEME])
        today = timezone.localdate()
        self.copy_report(report, day=today.replace(month=1, day=1)-timedelta(days=1), quantity="4")
        self.copy_report(report, day=today+timedelta(days=1), quantity="9")
        self.schedule_product.metal_return_date = today - timedelta(days=1)
        self.schedule_product.save(update_fields=["metal_return_date"])
        overview = viewer.get(URL)
        self.assertEqual(overview.status_code, 200, overview.data)
        data = overview.data["data"]
        self.assertEqual(data["counts"], {"working": 1, "late": 1, "today": 0, "planned": 1})
        card = data["jobs"][0]
        self.assertEqual((card["task_number"], card["days_remaining"], card["latest_operation"]),
                         (self.task.task_number, -1, self.operation.name))
        self.assertEqual(card["quantity"]["done"], "6")
        self.assertEqual(card["quantity"]["target"], "200")
        self.assertEqual(card["quantity"]["remaining"], "194")
        detail = viewer.get(URL + "detail/", {"id": card["id"]}).data["data"]
        self.assertEqual(len(detail["reports"]), 2)
        self.assertEqual(detail["operations"][0]["done"], "6")
        self.assertEqual(viewer.get(URL+"items/", {"category":"late"}).data["meta"]["total"], 1)
        self.schedule_product.metal_return_date = today
        self.schedule_product.save(update_fields=["metal_return_date"])
        planned_product.metal_return_date = today
        planned_product.save(update_fields=["metal_return_date"])
        self.assertEqual(viewer.get(URL).data["data"]["counts"]["today"], 1)
        self.assertEqual(viewer.get(URL+"items/", {"category":"day","date":today}).data["meta"]["total"], 2)
        for period in ("month", "quarter", "year"):
            summary = viewer.get(URL + "activity/", {"period": period}).data["data"]
            self.assertEqual((summary["task_count"], summary["record_count"], summary["day_count"]), (1, 1, 1))
            self.assertEqual(summary["records"][0]["job_id"], card["id"])
            self.assertEqual(summary["quantities"], [])
            self.assertEqual(summary["records"][0]["quantity"], "2")
        WorkshopPlanExecution.objects.update_or_create(schedule_product=self.schedule_product, craft=self.craft,
                                                      defaults={"status": "COMPLETED"})
        self.assertEqual(viewer.get(URL).data["data"]["counts"]["working"], 0)
        self.task.status = "PAUSED"
        self.task.save(update_fields=["status"])
        self.assertEqual(viewer.get(URL+"items/", {"category":"week"}).data["meta"]["total"], 0)
        self.assertIsNone(viewer.get(URL+"activity/").data["data"]["records"][0]["job_id"])

    def test_sewing_due_date_and_revoked_report_scope(self):
        sewing, _ = Workshop.objects.get_or_create(name="车缝车间")
        self.link("CUTTING", sewing)
        self.link("SEWING", sewing)
        viewer, _, role = director("SEWING_DIRECTOR", sewing, [SCHEDULE, REPORT])
        data = viewer.get(URL).data["data"]
        self.assertEqual(data["workshops"], ["SEWING"])
        self.assertEqual(data["upcoming"][2]["count"], 2)
        details = viewer.get(URL+"items/", {"category":"planned","page_size":1,"page":2}).data
        self.assertEqual(details["meta"], {"page":2,"page_size":1,"total":2,"total_pages":2})
        self.assertEqual(details["data"][0]["days_remaining"], 2)
        RoleGrantResource.objects.filter(grant__role=role, grant__permission__codename="view_workreport").delete()
        data = viewer.get(URL).data["data"]
        self.assertIsNone(data["counts"]["working"])
        self.assertEqual(data["upcoming"][2]["count"], 2)
        self.assertEqual(viewer.get(URL+"items/", {"category":"working"}).status_code, 403)
        self.assertFalse(viewer.get(URL+"activity/").data["data"]["available"])
        detail = viewer.get(URL+"detail/", {"id":details["data"][0]["id"]}).data["data"]
        self.assertIsNone(detail["reports"])
        self.assertEqual(detail["job"]["stage"], "unknown")

    def test_two_reported_operations_keep_their_own_requirements_and_units(self):
        report = self.create_report()
        first = report.lines.get()
        unit = ProductionUnit.objects.get(unit_name="套")
        operation = self.copy_row(self.operation, name="配套", operation_number="DIR-OP-02", reporting_unit_id=unit.pk)
        work_item = self.copy_row(first.work_item, identity_key="director-set", operation_id=operation.pk, unit_id=unit.pk)
        scheme_line = self.copy_row(first.scheme_line, line_number=2, work_item_id=work_item.pk,
                                    unit_name_snapshot="套", required_quantity_snapshot=8, operation_name_snapshot="配套")
        self.copy_row(first, line_number=2, scheme_line_id=scheme_line.pk, work_item_id=work_item.pk,
                      unit_name_snapshot="套", required_quantity_snapshot=8, quantity=3, operation_name_snapshot="配套")
        viewer, _, _ = director("METAL_DIRECTOR", self.workshop, [SCHEDULE, REPORT, SCHEME])
        data = viewer.get(URL).data["data"]["jobs"][0]
        self.assertEqual((data["latest_operation"], data["quantity"]["done"]), (self.operation.name, "2"))
        ops = viewer.get(URL+"detail/", {"id":data["id"]}).data["data"]["operations"]
        self.assertEqual([(op["name"], op["target"], op["done"]) for op in ops], [(self.operation.name,"200","2"),("配套","8","3")])
        period = viewer.get(URL+"activity/").data
        self.assertEqual((period["data"]["record_count"], period["meta"]["total"]), (2,2))
        self.assertEqual({row["unit"] for row in period["data"]["records"]}, {first.unit_name_snapshot,"套"})


@override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class DirectorAssemblyTests(assembly_tests.AssemblyFixture, APITestCase):
    def test_partial_confirmed_receipt_separate_from_work_report(self):
        self.prepare()
        viewer, _, _ = director("ASSEMBLY_DIRECTOR", self.craft.workshop, [SCHEDULE, REPORT, RECEIPT])
        board = viewer.get(URL)
        self.assertEqual(board.status_code, 200, board.data)
        job = board.data["data"]["jobs"][0]
        self.assertEqual((job["task_number"], job["days_remaining"], job["quantity"]["done"]), (self.task.task_number, 0, "0"))
        pending = self.post(self.payload(received_quantity=4, receipt_date=str(timezone.localdate())))
        self.assertEqual(pending.status_code, 201, pending.data)
        self.assertEqual(viewer.get(URL+"activity/").data["data"]["record_count"], 0)
        self.confirm(pending)
        confirmed = viewer.get(URL+"detail/", {"id":job["id"]}).data["data"]
        self.assertEqual(len(confirmed["reports"]), 1)
        self.assertEqual(confirmed["reports"][0]["task_number"], self.task.task_number)
        self.assertEqual(len(confirmed["receipts"]), 1)
        self.assertEqual(confirmed["job"]["quantity"]["remaining"], "6")
        summary = viewer.get(URL+"activity/").data["data"]
        self.assertEqual((summary["task_count"], summary["record_count"], summary["day_count"]), (1,1,1))
        self.assertEqual(summary["quantities"][0]["quantity"], "4")
        self.confirm(self.post(self.payload(received_quantity=6, receipt_date=str(timezone.localdate()))))
        self.assertEqual(viewer.get(URL).data["data"]["counts"]["working"], 0)
        self.assertEqual(viewer.get(URL+"detail/", {"id":job["id"]}).data["data"]["job"]["stage"], "completed")
