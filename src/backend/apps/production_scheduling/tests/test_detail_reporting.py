import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.workshop_config.models import Craft, CraftType, Operation, PlanCategory, Workshop
from apps.workshop_reporting.models import (
    WageSchemeCraft, WageSchemeLine, WorkCountingMode, WorkshopPlanExecution,
    WorkshopPlanStatus, WorkshopReportingScope,
)
from apps.workshop_reporting.tests import test_work_report_task_selection as reporting_fixtures

from ..detail_reporting import reporting_summary
from ..detail_summary import schedule_detail_summary
from ..models import ProductionScheduleProductCraft, ScheduleStatus


@override_settings(MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class DetailReportingTests(APITestCase):
    # 复用现有业务准备方法，不继承其测试类，避免重复运行整套报工接口测试。
    setUp = reporting_fixtures.WorkReportTaskSelectionTests.setUp
    scheme_payload = reporting_fixtures.WorkReportTaskSelectionTests.scheme_payload
    create_approved_scheme = reporting_fixtures.WorkReportTaskSelectionTests.create_approved_scheme
    create_report = reporting_fixtures.WorkReportTaskSelectionTests.create_report
    copy_values = reporting_fixtures.WorkReportTaskSelectionTests.copy_values
    copy_row = reporting_fixtures.WorkReportTaskSelectionTests.copy_row
    copy_report = reporting_fixtures.WorkReportTaskSelectionTests.copy_report

    def summary(self, *, user=None, employee=None, crafts=None):
        request = APIRequestFactory().get(f"/api/v1/production-schedules/{self.schedule.pk}/detail-summary/")
        request.user = user or self.user
        request.employee = employee or self.employee
        request.parser_context = {"view": SimpleNamespace(
            action="detail_summary", action_permission_map={
                "detail_summary": "production_scheduling.view_productionschedule",
            },
        )}
        self.schedule_product.active_crafts = list(
            crafts if crafts is not None else self.schedule_product.crafts.filter(
                removed_at__isnull=True,
            ).select_related("craft")
        )
        return reporting_summary(request, self.schedule, [self.schedule_product])[str(self.schedule_product.pk)]

    def viewer(self, *permissions):
        user = get_user_model().objects.create_user(username=f"summary-{uuid.uuid4().hex[:8]}")
        employee = Employee.objects.create(
            user=user, employee_code=f"SUMMARY-{uuid.uuid4().hex[:8].upper()}", display_name="排产汇总查看员",
        )
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="workshop_reporting", codename__in=permissions,
        ))
        WorkshopReportingScope.objects.create(
            employee=employee, workshop=self.workshop, created_by_employee=self.employee,
        )
        return user, employee

    def second_craft(self):
        workshop, _ = Workshop.objects.get_or_create(name="装配车间")
        craft = Craft.objects.create(
            craft_type=CraftType.INTERNAL, workshop=workshop, name="汇总装配工艺",
            plan_category=PlanCategory.ASSEMBLY,
        )
        link = ProductionScheduleProductCraft.objects.create(
            schedule_product=self.schedule_product, craft=craft,
            craft_type_snapshot=CraftType.INTERNAL, craft_name_snapshot=craft.name,
            plan_category=PlanCategory.ASSEMBLY,
        )
        return craft, link

    def test_current_plan_amounts_and_progress_are_independent_values(self):
        self.create_report()
        result = self.summary()
        row = result["internal_plans"][0]
        self.assertEqual(result["estimated_wage"], "469.0000")
        self.assertEqual(result["reported_amount"], "4.69")
        self.assertEqual(row["progress_percent"], 1)
        self.assertEqual(row["milestone"], "金工回货日期")
        self.assertEqual(row["planned_quantity"], "100")
        self.assertEqual(row["estimated_amount_status"], "READY")

    def test_report_amount_keeps_old_version_and_removed_work_items(self):
        report = self.create_report()
        yesterday = timezone.localdate() - timedelta(days=1)
        old = report.scheme
        old.effective_from = yesterday
        old.effective_to = yesterday
        old.save(update_fields=["effective_from", "effective_to", "updated_at"])
        current = self.copy_row(
            old, scheme_number="GJ-SUMMARY-V2", parent_scheme_id=old.pk, version=2,
            effective_from=timezone.localdate(), effective_to=None,
        )
        old_line = old.lines.get()
        new_item = self.copy_row(old_line.work_item, identity_key="summary-replacement", display_name="新工序")
        self.copy_row(old_line, scheme_id=current.pk, work_item_id=new_item.pk, declared_price=Decimal("10"))
        result = self.summary()
        self.assertEqual(result["estimated_wage"], "2000.0000")
        self.assertEqual(result["reported_amount"], "4.69")
        self.assertEqual(result["internal_plans"][0]["progress_percent"], 0)

    def test_report_amount_does_not_include_another_schedule_of_same_product(self):
        report = self.create_report()
        removed_at = timezone.now()
        with transaction.atomic():
            archived = self.copy_row(
                self.schedule, schedule_number="PC-SUMMARY-OLD", client_request_id=uuid.uuid4(),
                record_status=ScheduleStatus.VOID, void_reason="历史排产", voided_at=removed_at,
                voided_by_employee_id=self.employee.pk,
            )
            old_product = self.copy_row(
                self.schedule_product, schedule_id=archived.pk,
                removed_at=removed_at, removed_by_employee_id=self.employee.pk,
            )
            self.copy_row(
                self.schedule_product.crafts.get(craft=self.craft), schedule_product_id=old_product.pk,
                removed_at=removed_at, removed_by_employee_id=self.employee.pk,
            )
            self.copy_report(report, scheduled=old_product, quantity="50")
        result = self.summary()
        self.assertEqual(result["reported_amount"], "4.69")
        self.assertEqual(result["internal_plans"][0]["progress_percent"], 1)

    def test_different_crafts_have_separate_rows_and_applicable_generic_scheme(self):
        report = self.create_report()
        craft, _ = self.second_craft()
        operation = Operation.objects.create(
            operation_number="SUMMARY-SECOND", product_name="工价测试产品", craft=craft,
            name="第二道工序", reporting_unit=self.unit,
        )
        source_line = report.scheme.lines.get()
        scheme = self.copy_row(
            report.scheme, scheme_number="GJ-SUMMARY-SECOND", workshop_id=craft.workshop_id,
            scope_craft_id=craft.pk, schedule_product_id=None,
        )
        WageSchemeCraft.objects.create(scheme=scheme, craft=craft)
        item = self.copy_row(
            source_line.work_item, workshop_id=craft.workshop_id, craft_id=craft.pk,
            operation_id=operation.pk, identity_key="summary-second", display_name=operation.name,
            counting_mode=WorkCountingMode.ORDER, bom_component_identity=None,
        )
        self.copy_row(
            source_line, scheme_id=scheme.pk, work_item_id=item.pk, declared_price=Decimal("2"),
            display_name_snapshot=operation.name, craft_name_snapshot=craft.name,
            operation_name_snapshot=operation.name, operation_number_snapshot=operation.operation_number,
            counting_mode=WorkCountingMode.ORDER, required_quantity_snapshot=Decimal("100"),
            bom_component_identity_snapshot=None, bom_sets_per_product_snapshot=None,
            bom_pieces_per_set_snapshot=None,
        )
        result = self.summary()
        self.assertEqual(len(result["internal_plans"]), 2)
        rows = {row["craft_id"]: row for row in result["internal_plans"]}
        self.assertEqual(rows[str(craft.pk)]["estimated_wage"], "200.0000")
        self.assertEqual(rows[str(craft.pk)]["reported_amount"], "0.00")
        self.assertEqual(result["estimated_wage"], "669.0000")
        self.assertEqual(result["reported_amount"], "4.69")

    def test_missing_scheme_and_missing_line_snapshots_never_become_zero_estimate(self):
        missing = self.summary()
        self.assertIsNone(missing["estimated_wage"])
        self.assertEqual(missing["internal_plans"][0]["wage_status"], "NOT_CREATED")
        self.assertEqual(missing["reported_amount"], "0.00")
        approved = self.create_approved_scheme().data["data"]
        WageSchemeLine.objects.filter(scheme_id=approved["id"]).update(required_quantity_snapshot=None)
        self.assertEqual(self.summary()["estimated_amount_status"], "NOT_CONFIGURED")

    def test_partial_estimate_has_no_incomplete_total(self):
        self.create_approved_scheme()
        self.second_craft()
        result = self.summary()
        self.assertIsNone(result["estimated_wage"])
        self.assertEqual(result["estimated_amount_status"], "PARTIAL")

    def test_planned_quantity_mismatch_is_explicit_and_does_not_reprice_reports(self):
        self.create_report()
        self.schedule_product.planned_quantity = 50
        self.schedule_product.save(update_fields=["planned_quantity", "updated_at"])
        result = self.summary()
        self.assertIsNone(result["estimated_wage"])
        self.assertEqual(result["estimated_amount_status"], "QUANTITY_BASIS_MISMATCH")
        self.assertEqual(result["reported_amount"], "4.69")

    def test_wage_and_report_permissions_are_independent(self):
        self.create_report()
        user, employee = self.viewer("view_wagescheme")
        wages_only = self.summary(user=user, employee=employee)
        self.assertEqual(wages_only["estimated_wage"], "469.0000")
        self.assertIsNone(wages_only["reported_amount"])
        self.assertEqual(wages_only["reported_amount_status"], "FORBIDDEN")
        user, employee = self.viewer("view_workreport")
        reports_only = self.summary(user=user, employee=employee)
        self.assertIsNone(reports_only["estimated_wage"])
        self.assertEqual(reports_only["reported_amount"], "4.69")
        self.assertIsNone(reports_only["internal_plans"][0]["scheme_id"])
        self.assertEqual(reports_only["internal_plans"][0]["progress_percent"], 1)

    def test_no_reporting_permissions_do_not_disclose_scheme_or_amount(self):
        self.create_report()
        user, employee = self.viewer()
        result = self.summary(user=user, employee=employee)
        row = result["internal_plans"][0]
        self.assertIsNone(result["estimated_wage"])
        self.assertIsNone(result["reported_amount"])
        self.assertEqual(row["wage_status"], "FORBIDDEN")
        self.assertIsNone(row["scheme_id"])
        self.assertIsNone(row["progress_percent"])

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
    def test_detail_view_permission_cannot_replace_reporting_workshop_scope(self):
        with override_settings(MODULE_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False):
            self.create_report()
        user, employee = self.viewer()
        # 不保留旧版车间授权，使用两个操作各自的资源角色范围。
        WorkshopReportingScope.objects.filter(employee=employee).delete()
        workshop, _ = Workshop.objects.get_or_create(name="车缝车间")
        group = Group.objects.create(name="DETAIL-REPORTING-SCOPES")
        role = RoleProfile.objects.create(role_code="DETAIL_REPORTING_SCOPES", display_name="汇总范围", auth_group=group)
        EmployeeRoleAssignment.objects.create(employee=employee, role_profile=role, effective_from=timezone.now())
        for app, codename, resource in (
            ("production_scheduling", "view_productionschedule", self.workshop),
            ("workshop_reporting", "view_wagescheme", self.workshop),
            ("workshop_reporting", "view_workreport", workshop),
        ):
            permission = Permission.objects.get(content_type__app_label=app, codename=codename)
            group.permissions.add(permission)
            grant = RoleActionGrant.objects.create(role=role, permission=permission, scope="WORKSHOP")
            RoleGrantResource.objects.create(grant=grant, workshop=resource)
        result = self.summary(user=user, employee=employee)
        self.assertEqual(result["estimated_wage"], "469.0000")
        self.assertIsNone(result["reported_amount"])
        self.assertEqual(result["reported_amount_status"], "FORBIDDEN")

    def test_only_prefiltered_crafts_are_exposed(self):
        self.create_report()
        self.second_craft()
        allowed = self.schedule_product.crafts.filter(craft=self.craft).select_related("craft")
        result = self.summary(crafts=allowed)
        self.assertEqual([row["craft_id"] for row in result["internal_plans"]], [str(self.craft.pk)])
        self.assertEqual(result["estimated_wage"], "469.0000")

    def test_empty_internal_plans_are_not_applicable(self):
        result = self.summary(crafts=[])
        self.assertEqual(result["internal_plans"], [])
        self.assertEqual(result["estimated_amount_status"], "NOT_APPLICABLE")
        self.assertIsNone(result["reported_amount"])

    def test_removed_reported_craft_cannot_be_omitted_from_a_complete_total(self):
        self.create_report()
        with transaction.atomic():
            other, _ = self.second_craft()
            self.schedule_product.crafts.filter(craft=self.craft).update(
                removed_at=timezone.now(), removed_by_employee=self.employee,
            )
        result = self.summary()
        self.assertEqual([row["craft_id"] for row in result["internal_plans"]], [str(other.pk)])
        self.assertEqual(result["internal_plans"][0]["reported_amount"], "0.00")
        self.assertIsNone(result["reported_amount"])
        self.assertEqual(result["reported_amount_status"], "PARTIAL")
        self.assertEqual(self.schedule._detail_reported_product_ids, {self.schedule_product.pk})

    def test_only_external_craft_remains_preserves_incomplete_reported_amount(self):
        self.create_report()
        with transaction.atomic():
            external = Craft.objects.create(craft_type=CraftType.EXTERNAL, name="汇总外部工艺")
            ProductionScheduleProductCraft.objects.create(
                schedule_product=self.schedule_product, craft=external,
                craft_type_snapshot=CraftType.EXTERNAL, craft_name_snapshot=external.name,
            )
            self.schedule_product.crafts.filter(craft=self.craft).update(
                removed_at=timezone.now(), removed_by_employee=self.employee,
            )
        result = self.summary()
        self.assertEqual(result["internal_plans"], [])
        self.assertEqual(result["estimated_amount_status"], "NOT_APPLICABLE")
        self.assertIsNone(result["reported_amount"])
        self.assertEqual(result["reported_amount_status"], "PARTIAL")

    def test_removed_reported_product_prevents_complete_schedule_reported_total(self):
        self.create_report()
        with transaction.atomic():
            self.schedule_product.removed_at = timezone.now()
            self.schedule_product.removed_by_employee = self.employee
            self.schedule_product.save(update_fields=["removed_at", "removed_by_employee", "updated_at"])
            self.schedule_product.crafts.update(removed_at=timezone.now(), removed_by_employee=self.employee)
            replacement = self.copy_row(
                self.schedule_product, removed_at=None, removed_by_employee_id=None,
            )
            ProductionScheduleProductCraft.objects.create(
                schedule_product=replacement, craft=self.craft, craft_type_snapshot=CraftType.INTERNAL,
                craft_name_snapshot=self.craft.name, plan_category=PlanCategory.METAL,
            )
        replacement.active_crafts = list(replacement.crafts.select_related("craft"))
        self.schedule.active_products = [replacement]
        request = APIRequestFactory().get(f"/api/v1/production-schedules/{self.schedule.pk}/detail-summary/")
        request.user, request.employee = self.user, self.employee
        unrelated_sources = {str(replacement.pk): {
            "outsourcing": {"allowed": True, "records": [], "planned_amount": "0.00"},
            "material_issues": {"allowed": True, "records": []},
        }}
        # 仅隔离无关外发/领料来源；排产、工价、历史报工和金额汇总全部使用测试库实物。
        with patch("apps.production_scheduling.detail_summary.related_summary", return_value=unrelated_sources):
            result = schedule_detail_summary(request, self.schedule)
        self.assertTrue(result["totals"]["complete_scope"])
        self.assertEqual(result["products"][0]["reported_amount"], "0.00")
        self.assertIsNone(result["totals"]["reported_amount"])
        self.assertIn("历史报工", result["totals"]["reason"])
        self.assertEqual(self.schedule._detail_reported_product_ids, {self.schedule_product.pk})

    def test_shanghai_date_selects_effective_version_even_when_host_is_utc(self):
        approved = self.create_approved_scheme().data["data"]
        from apps.workshop_reporting.models import WageScheme

        scheme = WageScheme.objects.get(pk=approved["id"])
        scheme.effective_from = timezone.localdate()
        scheme.save(update_fields=["effective_from", "updated_at"])
        prior_utc_day = datetime.combine(
            scheme.effective_from - timedelta(days=1), datetime.min.time(), tzinfo=datetime_timezone.utc,
        ) + timedelta(hours=17)
        with timezone.override("UTC"), patch("django.utils.timezone.now", return_value=prior_utc_day):
            self.assertEqual(self.summary()["estimated_wage"], "469.0000")

    def test_metal_completion_reflects_current_plan_without_mutation(self):
        self.create_report()
        execution, _ = WorkshopPlanExecution.objects.update_or_create(
            schedule_product=self.schedule_product, craft=self.craft,
            defaults={"status": WorkshopPlanStatus.COMPLETED, "completed_at": timezone.now(),
                      "completed_by_employee": self.employee},
        )
        self.assertEqual(self.summary()["internal_plans"][0]["plan_status"], "IN_PROGRESS")
        execution.refresh_from_db()
        self.assertEqual(execution.status, WorkshopPlanStatus.COMPLETED)
