from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.organizations.models import Employee
from apps.inventory.models import FinishedGoodsReceipt, Warehouse, WarehouseLocation, WarehouseZone
from apps.inventory.assembly_receipt_models import AssemblyReceiptSource
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.reference_data.models import Currency, ProductionUnit
from apps.workshop_config.models import Craft, Operation, Workshop, WorkshopEmployee
from apps.workshop_reporting.models import (
    WageScheme, WageSchemeLine, WorkItem, WorkReport, WorkReportLine, WorkshopReportingScope,
)

from ..models import DeliveryMethod, OrderSource, ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from ..dashboard import DashboardFilters


class DashboardFixture:
    url = "/api/v1/production-dashboard/"

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="production-dashboard")
        self.employee = Employee.objects.create(
            user=self.user, employee_code="DASHBOARD", display_name="生产看板测试员工",
        )
        self.currency, _ = Currency.objects.get_or_create(
            code="CNY", defaults={"numeric_code": "156", "chinese_name": "人民币"},
        )
        self.unit, _ = ProductionUnit.objects.get_or_create(unit_code="DASH", defaults={"unit_name": "看板件"})
        self.today = timezone.localdate()
        self.grant("production_tasks.view_productiontask")
        self.client.force_authenticate(self.user)

    def grant(self, *codes):
        for code in codes:
            app, codename = code.split(".", 1)
            self.user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))
        for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            self.user.__dict__.pop(attr, None)

    def task(self, suffix, offset=0, status=ProductionTaskStatus.IN_PRODUCTION, employee=None):
        actor = employee or self.employee
        task = ProductionTask.objects.create(
            task_number=f"DASH-{suffix}", contract_number=f"DASH-{suffix}", order_source=OrderSource.NEW,
            order_number=f"DASH-{suffix}", order_date=min(self.today, self.today + timedelta(days=offset)),
            delivery_date=self.today + timedelta(days=offset),
            salesperson=actor, currency=self.currency, includes_tax=False, order_tolerance_percent=0,
            is_repeat_order=False, preproduction_sample_required=False, delivery_method=DeliveryMethod.SINGLE,
            status=status, created_by_employee=actor,
        )
        ProductionTaskProduct.objects.create(
            production_task=task, line_number=1, product_name_snapshot=f"产品 {suffix}", quantity=100,
            unit=self.unit, currency=self.currency, unit_price=1, total_amount=100, exchange_rate=1,
        )
        return task

    def schedule(self, task):
        status = task.status
        task.status = ProductionTaskStatus.READY
        task.save(update_fields=["status", "updated_at"])
        schedule = ProductionSchedule.objects.create(
            schedule_number=f"PS-{task.task_number}", production_task=task,
            source_revision_hash="test", client_request_id=uuid4(), request_payload_hash="test",
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        for product in task.products.all():
            plan = ProductionScheduleProduct.objects.create(
                schedule=schedule, product_line=product, line_number=product.line_number,
                planned_quantity=product.quantity, source_quantity_snapshot=product.quantity,
                unit=product.unit, unit_name_snapshot=product.unit.unit_name,
                material_inbound_date=self.today, metal_return_date=self.today,
                sewing_return_date=self.today, finished_inbound_date=self.today, source_revision_hash="test",
            )
            craft, _ = Craft.objects.get_or_create(craft_type="EXTERNAL", name="看板外协工艺")
            ProductionScheduleProductCraft.objects.create(
                schedule_product=plan, craft=craft, craft_type_snapshot="EXTERNAL", craft_name_snapshot=craft.name,
            )
        task.status = status
        task.save(update_fields=["status", "updated_at"])
        return schedule


@override_settings(SALES_ACCESS_ENABLED=False, MODULE_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False)
class ProductionDashboardApiTests(DashboardFixture, APITestCase):
    def payload(self, **params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["meta"]["read_only"])
        return response.data["data"]

    def test_horizon_keeps_old_overdue_and_paused_but_excludes_drafts_cancelled_and_old_completed(self):
        self.task("OLD", -40)
        self.task("PAUSE", -2, ProductionTaskStatus.PAUSED)
        self.task("SOON", 2)
        self.task("FUTURE", 3)
        self.task("DONE", 1, ProductionTaskStatus.COMPLETED)
        self.task("OLD-DONE", -2, ProductionTaskStatus.COMPLETED)
        self.task("DRAFT", 0, ProductionTaskStatus.DRAFT)
        self.task("CANCELLED", 0, ProductionTaskStatus.CANCELLED)
        result = self.payload(days=3)["sections"]["tasks"]["data"]
        self.assertEqual(result["counts"], {
            "total": 4, "overdue": 2, "due_soon": 1, "unscheduled": None, "completed": 1, "paused": 1,
        })
        self.assertEqual({row["task_number"] for row in result["items"]},
                         {"DASH-OLD", "DASH-PAUSE", "DASH-SOON", "DASH-DONE"})
        self.assertTrue(all(row["stages"]["metal"]["state"] == "FORBIDDEN" for row in result["items"]))
        self.assertEqual(len(result["due_series"]), 3)

    def test_focus_changes_rows_without_changing_counts_or_due_series(self):
        self.grant("production_scheduling.view_productionschedule")
        self.task("OVERDUE", -1)
        self.schedule(self.task("SCHEDULED", 1))
        self.task("UNSCHEDULED", 2)
        all_data = self.payload()["sections"]["tasks"]["data"]
        for focus, expected in (("OVERDUE", 1), ("DUE_SOON", 2), ("UNSCHEDULED", 2)):
            result = self.payload(focus=focus)["sections"]["tasks"]["data"]
            self.assertEqual(result["counts"], all_data["counts"])
            self.assertEqual(result["due_series"], all_data["due_series"])
            self.assertEqual(result["total"], expected)

    def test_seven_day_horizon_and_three_day_due_soon_have_exclusive_end_dates(self):
        for offset in range(8):
            self.task(f"DAY-{offset}", offset)
        data = self.payload(days=7)["sections"]["tasks"]["data"]
        self.assertEqual(data["counts"]["total"], 7)
        self.assertEqual(data["counts"]["due_soon"], 3)
        self.assertEqual(len(data["due_series"]), 7)
        self.assertEqual(self.payload(days=7, focus="DUE_SOON")["sections"]["tasks"]["data"]["total"], 3)

    def test_search_status_and_item_limit_apply_without_reducing_full_counts(self):
        for index in range(23):
            self.task(f"MATCH-{index}", status=ProductionTaskStatus.PAUSED)
        self.task("OTHER")
        data = self.payload(q="MATCH", status="PAUSED")["sections"]["tasks"]["data"]
        self.assertEqual(data["counts"]["total"], 23)
        self.assertEqual(data["total"], 23)
        self.assertEqual(len(data["items"]), 20)
        self.assertTrue(data["truncated"])

    def test_sections_require_original_source_permissions(self):
        self.task("VISIBLE")
        sections = self.payload()["sections"]
        for name in ("outsourcing", "receipts", "workshop", "reports"):
            self.assertEqual(sections[name]["state"], "FORBIDDEN")
            self.assertIsNone(sections[name]["data"])
        self.user.user_permissions.clear()
        self.grant()
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_task_scope_does_not_reveal_another_employee_records(self):
        other = Employee.objects.create(employee_code="DASH-OTHER", display_name="其他员工")
        self.task("MINE")
        self.task("HIDDEN", employee=other)
        data = self.payload()["sections"]["tasks"]["data"]
        self.assertEqual(data["counts"]["total"], 1)
        self.assertEqual(data["items"][0]["task_number"], "DASH-MINE")

    def test_schedule_global_read_scope_is_independent_of_task_read_scope(self):
        self.grant("production_scheduling.view_productionschedule", "production_scheduling.view_all_productionschedule")
        other = Employee.objects.create(employee_code="DASH-PLAN-OTHER", display_name="其他任务员工")
        plan = self.schedule(self.task("OTHER-PLAN", employee=other)).products.get()
        workshop, _ = Workshop.objects.get_or_create(name="金工车间")
        craft = Craft.objects.create(craft_type="INTERNAL", workshop=workshop, name="范围测试金工", plan_category="METAL")
        ProductionScheduleProductCraft.objects.create(
            schedule_product=plan, craft=craft, craft_type_snapshot="INTERNAL", craft_name_snapshot=craft.name, plan_category="METAL",
        )
        original = self.client.get("/api/v1/production-schedule-items/", {"category": "METAL"})
        self.assertEqual(original.status_code, 200, original.data)
        self.assertEqual(len(original.data["data"]), 1)
        sections = self.payload()["sections"]
        self.assertEqual(sections["tasks"]["data"]["counts"]["total"], 0)
        self.assertEqual(sections["workshop"]["data"]["plan_count"], 1)
        self.assertEqual(sections["workshop"]["data"]["items"][0]["task_number"], "DASH-OTHER-PLAN")

    def test_multi_product_progress_is_not_averaged_and_quantities_keep_units(self):
        self.grant("production_scheduling.view_productionschedule", "inventory.view_finishedgoodsreceipt")
        task = self.task("MIXED")
        second_unit = ProductionUnit.objects.create(unit_code="DASH-SET", unit_name="看板套")
        ProductionTaskProduct.objects.create(
            production_task=task, line_number=2, product_name_snapshot="第二产品", quantity=9,
            unit=second_unit, currency=self.currency, unit_price=1, total_amount=9, exchange_rate=1,
        )
        self.schedule(task)
        row = self.payload()["sections"]["tasks"]["data"]["items"][0]
        self.assertEqual({item["unit"] for item in row["products"]}, {"看板件", "看板套"})
        self.assertEqual(row["stages"]["assembly"]["state"], "UNKNOWN")
        self.assertIsNone(row["stages"]["assembly"]["percent"])
        self.assertNotIn("material", row["stages"])

    def test_query_validation_and_read_only_methods(self):
        for params in ({"days": 4}, {"status": "DRAFT"}, {"focus": "INVALID"}, {"workshop": "CUTTING"},
                       {"production_date": "2026-02-30"}, {"q": "x" * 121}, {"task_date": "invalid"}, {"task_page": 0}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 400)
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_date_details_paginate_all_matches_without_changing_summary(self):
        for index in range(23):
            self.task(f"DATE-{index}", 1)
        self.task("OTHER-DATE", 2)
        self.task("DONE-DATE", 1, ProductionTaskStatus.COMPLETED)
        all_data = self.payload()["sections"]["tasks"]["data"]
        day = str(self.today + timedelta(days=1))
        first = self.payload(task_date=day, task_page=1)["sections"]["tasks"]["data"]
        second = self.payload(task_date=day, task_page=2)["sections"]["tasks"]["data"]
        self.assertEqual(first["total"], 23)
        self.assertEqual((len(first["items"]), len(second["items"])), (20, 3))
        self.assertTrue(first["truncated"])
        self.assertTrue(second["truncated"])
        self.assertFalse({item["id"] for item in first["items"]} & {item["id"] for item in second["items"]})
        for data in (first, second):
            self.assertEqual(data["counts"], all_data["counts"])
            self.assertEqual(data["due_series"], all_data["due_series"])
            self.assertTrue(all(item["status"] != "COMPLETED" for item in data["items"]))

    def test_task_query_count_does_not_grow_with_rows(self):
        self.task("ONE")
        self.payload()
        with CaptureQueriesContext(connection) as single:
            self.payload()
        for index in range(19):
            self.task(f"EXTRA-{index}")
        with CaptureQueriesContext(connection) as many:
            self.payload()
        self.assertLessEqual(len(many), len(single) + 1)

    def receipt(self, product, number, quantity=25):
        warehouse, _ = Warehouse.objects.get_or_create(
            warehouse_number="DASH-WH", defaults={"warehouse_name": "看板成品仓", "warehouse_type": "FINISHED"},
        )
        zone, _ = WarehouseZone.objects.get_or_create(warehouse=warehouse, zone_name="看板区")
        location, _ = WarehouseLocation.objects.get_or_create(zone=zone, location_number="01")
        return FinishedGoodsReceipt.objects.create(
            receipt_number=number, production_task_product=product, location=location,
            task_number_snapshot=product.production_task.task_number, product_name_snapshot=product.product_name_snapshot,
            unit=product.unit, received_quantity=quantity, remaining_quantity=0, received_by_employee=self.employee,
        )

    def test_receipts_use_business_date_and_cumulative_receipts_not_stock_balance(self):
        self.grant("inventory.view_finishedgoodsreceipt", "production_scheduling.view_productionschedule")
        task = self.task("RECEIPT")
        plan = self.schedule(task).products.get()
        receipt = self.receipt(plan.product_line, "DASH-R1")
        yesterday = self.today - timedelta(days=1)
        AssemblyReceiptSource.objects.create(
            receipt=receipt, schedule_product=plan, request_id=uuid4(), payload_hash="test", receipt_date=yesterday,
        )
        payload = self.payload(production_date=str(yesterday))
        data = payload["sections"]["receipts"]["data"]
        self.assertEqual(data["today_count"], 1)
        self.assertEqual(data["today_quantities"][0]["quantity"], "25")
        self.assertEqual(data["pending_products"][0]["remaining"], "75")
        self.assertEqual(payload["sections"]["tasks"]["data"]["items"][0]["stages"]["assembly"]["percent"], 25)
        self.assertEqual(self.payload()["sections"]["receipts"]["data"]["today_count"], 0)

    def test_receipt_only_reader_does_not_get_task_gap_or_task_section(self):
        self.receipt(self.task("R-ONLY").products.get(), "DASH-R2")
        self.user.user_permissions.clear()
        self.grant("inventory.view_finishedgoodsreceipt")
        sections = self.payload()["sections"]
        self.assertEqual(sections["tasks"]["state"], "FORBIDDEN")
        self.assertEqual(sections["receipts"]["data"]["today_count"], 1)
        self.assertEqual(sections["receipts"]["data"]["pending_state"], "FORBIDDEN")
        self.assertEqual(sections["receipts"]["data"]["pending_products"], [])

    def test_receipt_unit_mismatch_is_unknown_instead_of_zero_received(self):
        self.grant("inventory.view_finishedgoodsreceipt", "production_scheduling.view_productionschedule")
        plan = self.schedule(self.task("BAD-UNIT")).products.get()
        receipt = self.receipt(plan.product_line, "DASH-R3")
        receipt.unit = ProductionUnit.objects.create(unit_code="DASH-OTHER-UNIT", unit_name="另一计量单位")
        receipt.save(update_fields=["unit", "updated_at"])
        sections = self.payload()["sections"]
        data = sections["receipts"]["data"]
        self.assertEqual(data["pending_state"], "UNKNOWN")
        self.assertIsNone(data["pending_products"][0]["received"])
        self.assertIsNone(data["pending_products"][0]["remaining"])
        self.assertEqual(sections["tasks"]["data"]["items"][0]["stages"]["assembly"]["state"], "UNKNOWN")

    def reporting_data(self):
        task = self.task("REPORT")
        plan = self.schedule(task).products.get()
        workshop, _ = Workshop.objects.get_or_create(name="金工车间")
        craft = Craft.objects.create(craft_type="INTERNAL", workshop=workshop, name="看板金工", plan_category="METAL")
        ProductionScheduleProductCraft.objects.create(
            schedule_product=plan, craft=craft, craft_type_snapshot="INTERNAL", craft_name_snapshot=craft.name, plan_category="METAL",
        )
        operation = Operation.objects.create(operation_number="DASH-OP", craft=craft, name="切管", reporting_unit=self.unit)
        worker = WorkshopEmployee.objects.create(workshop=workshop, position="操作工", name="看板工人", is_supervisor=False)
        work_item = WorkItem.objects.create(
            product_line=plan.product_line, workshop=workshop, craft=craft, operation=operation, unit=self.unit,
            identity_key="dashboard", display_name="切管",
        )
        scheme = WageScheme.objects.create(
            scheme_number="DASH-SCHEME", product_line=plan.product_line, workshop=workshop, scope_craft=craft,
            schedule_product=plan, status="APPROVED", effective_from=self.today - timedelta(days=1),
            approved_at=timezone.now(), approved_by_employee=self.employee,
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        line = WageSchemeLine.objects.create(
            scheme=scheme, work_item=work_item, line_number=1, display_name_snapshot="切管",
            craft_name_snapshot=craft.name, operation_name_snapshot="切管", operation_number_snapshot="DASH-OP",
            unit_name_snapshot=self.unit.unit_name, required_quantity_snapshot=100, declared_price=1,
        )
        for index, day, quantity in ((1, self.today - timedelta(days=1), 10), (2, self.today, 15)):
            report = WorkReport.objects.create(
                report_number=f"DASH-WR{index}", production_date=day, product_line=plan.product_line,
                schedule_product=plan, workshop=workshop, scheme=scheme, scheme_version_snapshot=1,
                recorder_employee=self.employee, updated_by_employee=self.employee, total_amount=quantity,
                client_request_id=uuid4(), request_payload_hash="test", task_number_snapshot=task.task_number,
            )
            WorkReportLine.objects.create(
                report=report, line_number=1, scheme_line=line, work_item=work_item, workshop_employee=worker,
                quantity=quantity, order_quantity_snapshot=100, unit_price_snapshot=1, amount=quantity,
                display_name_snapshot="切管", operation_name_snapshot="切管", unit_name_snapshot=self.unit.unit_name,
            )
        return workshop

    def test_workshop_reports_keep_daily_and_cumulative_separate_and_obey_workshop_scope(self):
        self.grant("production_scheduling.view_productionschedule", "workshop_reporting.view_workreport")
        workshop = self.reporting_data()
        sections = self.payload()["sections"]
        self.assertEqual(sections["reports"]["data"]["report_count"], 0)
        self.assertEqual(sections["workshop"]["data"]["items"][0]["progress"]["state"], "FORBIDDEN")
        WorkshopReportingScope.objects.create(employee=self.employee, workshop=workshop, created_by_employee=self.employee)
        sections = self.payload()["sections"]
        self.assertEqual(sections["reports"]["data"]["report_count"], 1)
        self.assertEqual(sections["reports"]["data"]["employee_count"], 1)
        job = sections["workshop"]["data"]["items"][0]
        self.assertEqual((job["today"], job["cumulative"], job["remaining"]), ("15", "25", "75"))
        self.assertEqual(job["progress"]["percent"], 25)
        self.assertEqual(job["status"], "UNKNOWN")
        self.assertEqual(sections["tasks"]["data"]["items"][0]["stages"]["metal"]["percent"], 25)
        self.assertEqual(sections["receipts"]["state"], "FORBIDDEN")

    def test_distinct_operations_do_not_become_one_quantity_even_when_unit_matches(self):
        self.grant("production_scheduling.view_productionschedule", "workshop_reporting.view_workreport")
        workshop = self.reporting_data()
        WorkshopReportingScope.objects.create(employee=self.employee, workshop=workshop, created_by_employee=self.employee)
        first = WageSchemeLine.objects.get(scheme__scheme_number="DASH-SCHEME")
        operation = Operation.objects.create(operation_number="DASH-OP2", craft=first.work_item.craft, name="弯管", reporting_unit=self.unit)
        work_item = WorkItem.objects.create(
            product_line=first.work_item.product_line, workshop=workshop, craft=first.work_item.craft,
            operation=operation, unit=self.unit, identity_key="dashboard-second", display_name="弯管",
        )
        WageSchemeLine.objects.create(
            scheme=first.scheme, work_item=work_item, line_number=2, display_name_snapshot="弯管",
            craft_name_snapshot="看板金工", operation_name_snapshot="弯管", operation_number_snapshot="DASH-OP2",
            unit_name_snapshot=self.unit.unit_name, required_quantity_snapshot=100, declared_price=1,
        )
        job = self.payload()["sections"]["workshop"]["data"]["items"][0]
        self.assertEqual(job["progress"]["state"], "UNKNOWN")
        self.assertIsNone(job["cumulative"])
        self.assertIsNone(job["required"])


class ProductionDashboardFiltersTests(SimpleTestCase):
    def test_task_page_bounds_and_valid_maximum(self):
        for page, error in ((0, "min_value"), (-1, "min_value"), (2147483648, "max_value")):
            with self.subTest(page=page):
                serializer = DashboardFilters(data={"task_page": page})
                self.assertFalse(serializer.is_valid())
                self.assertEqual(serializer.errors["task_page"][0].code, error)
        serializer = DashboardFilters(data={"task_page": 2147483647})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["task_page"], 2147483647)
