import json
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.db import IntegrityError, connection, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIRequestFactory, APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.workshop_config.models import Craft, Operation, Workshop

from ..models import WageScheme, WageSchemeLine, WorkItem, WorkReport, WorkReportLine
from ..schedule_stage_progress import schedule_stage_progress_statuses
from . import test_workshop_reporting_api as base_api_tests


@override_settings(
    MODULE_ACCESS_ENABLED=False, SALES_ACCESS_ENABLED=False, ACCESS_RESOURCE_SCOPES_ENABLED=False,
)
class ScheduleProgressQueryTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        base_api_tests.WorkshopReportingApiTests.setUp(self)
        self.as_of_date = timezone.localdate()
        self.crafts = {"METAL": self.craft}
        self.operations = {"METAL": self.operation}
        sewing_workshop, _ = Workshop.objects.get_or_create(name="车缝车间")
        for category in ("CUTTING", "SEWING"):
            craft = Craft.objects.create(
                craft_type="INTERNAL", workshop=sewing_workshop,
                name=f"进度查询{category}", plan_category=category,
            )
            self.crafts[category] = craft
            self.operations[category] = Operation.objects.create(
                operation_number=f"PROGRESS-{category}", product_name="工价测试产品",
                craft=craft, name=f"进度工项{category}", reporting_unit=self.unit,
            )
            ProductionScheduleProductCraft.objects.create(
                schedule_product=self.schedule_product, craft=craft,
                craft_type_snapshot="INTERNAL", craft_name_snapshot=craft.name, plan_category=category,
            )
        self.schemes = {}
        self.lines = {}
        for category in self.crafts:
            scheme = self.make_scheme(category)
            self.schemes[category] = scheme
            self.lines[category] = self.make_line(scheme)
            self.make_report(self.lines[category], quantity="20")

    def make_scheme(self, category, *, effective_from=None, effective_to=None, parent=None):
        craft = self.crafts[category]
        return WageScheme.objects.create(
            scheme_number=f"GJ-Q-{uuid4().hex}", product_line=self.product_line,
            workshop=craft.workshop, scope_craft=craft, schedule_product=self.schedule_product,
            status="APPROVED", version=parent.version + 1 if parent else 1, parent_scheme=parent,
            effective_from=effective_from or self.as_of_date - timedelta(days=10), effective_to=effective_to,
            approved_at=timezone.now(), approved_by_employee=self.employee,
            product_name_snapshot=self.product_line.product_name_snapshot,
            product_number_snapshot=self.product_line.product_number_snapshot,
            operation_product_name_snapshot="工价测试产品",
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )

    def make_line(self, scheme, *, line_number=1, work_item=None, required="100", status="ACTIVE"):
        craft = scheme.scope_craft
        operation = self.operations[craft.plan_category]
        if work_item is None:
            work_item = WorkItem.objects.create(
                product_line=self.product_line, workshop=scheme.workshop, craft=craft, operation=operation,
                unit=self.unit, identity_key=uuid4().hex, display_name=f"进度工项{line_number}",
            )
        return WageSchemeLine.objects.create(
            scheme=scheme, work_item=work_item, line_number=line_number,
            display_name_snapshot=work_item.display_name, craft_name_snapshot=craft.name,
            operation_name_snapshot=operation.name, operation_number_snapshot=operation.operation_number,
            unit_name_snapshot=self.unit.unit_name, order_quantity_snapshot=self.product_line.quantity,
            required_quantity_snapshot=Decimal(required), declared_price=Decimal("1"), status=status,
        )

    def make_report(self, line, *, quantity, production_date=None):
        quantity = Decimal(quantity)
        scheme = line.scheme
        report = WorkReport.objects.create(
            report_number=f"BG-Q-{uuid4().hex}", production_date=production_date or self.as_of_date,
            task_number_snapshot=self.task.task_number, order_number_snapshot=self.task.order_number,
            product_name_snapshot=self.product_line.product_name_snapshot,
            product_number_snapshot=self.product_line.product_number_snapshot,
            recorder_name_snapshot=self.employee.display_name, product_line=self.product_line,
            schedule_product=self.schedule_product, workshop=scheme.workshop, scheme=scheme,
            scheme_version_snapshot=scheme.version, recorder_employee=self.employee,
            updated_by_employee=self.employee, total_amount=quantity,
            client_request_id=uuid4(), request_payload_hash="d" * 64,
        )
        return WorkReportLine.objects.create(
            report=report, line_number=1, scheme_line=line, work_item=line.work_item,
            workshop_employee=self.worker, quantity=quantity,
            order_quantity_snapshot=self.product_line.quantity,
            required_quantity_snapshot=line.required_quantity_snapshot,
            unit_price_snapshot=Decimal("1"), amount=quantity, display_name_snapshot=line.display_name_snapshot,
            craft_name_snapshot=line.craft_name_snapshot, operation_name_snapshot=line.operation_name_snapshot,
            unit_name_snapshot=self.unit.unit_name, employee_name_snapshot=self.worker.display_name,
        )

    def progress(self, *, request=None, as_of_date=None):
        if request is None:
            request = APIRequestFactory().get("/api/v1/production-schedules/progress/")
            request.user = self.user
            request.employee = self.employee
        return schedule_stage_progress_statuses(
            [self.schedule.pk], request=request, as_of_date=as_of_date or self.as_of_date,
        )[str(self.schedule.pk)]

    def test_three_categories_share_one_scheme_line_and_report_query(self):
        with CaptureQueriesContext(connection) as captured:
            result = self.progress()
        tables = {
            "schemes": WageScheme._meta.db_table,
            "lines": WageSchemeLine._meta.db_table,
            "reports": WorkReportLine._meta.db_table,
        }
        counts = {
            name: sum(query["sql"].lstrip().startswith("SELECT") and f'FROM "{table}"' in query["sql"]
                      for query in captured.captured_queries)
            for name, table in tables.items()
        }
        print(json.dumps({"stage_reporting_selects": counts}, sort_keys=True))
        for category in self.crafts:
            self.assertEqual(result["stage_progress"][category]["percentage"], 20)
        for name, count in counts.items():
            with self.subTest(source=name):
                self.assertEqual(count, 1)

    def test_production_date_is_inclusive_and_future_reports_are_excluded(self):
        self.make_report(self.lines["METAL"], quantity="25", production_date=self.as_of_date - timedelta(days=1))
        self.make_report(self.lines["METAL"], quantity="80", production_date=self.as_of_date + timedelta(days=1))
        for offset, expected in ((-1, 25), (0, 45), (1, 100)):
            with self.subTest(day_offset=offset):
                result = self.progress(as_of_date=self.as_of_date + timedelta(days=offset))
                self.assertEqual(result["stage_progress"]["METAL"]["percentage"], expected)

    def test_get_endpoint_merges_stage_progress_with_existing_progress(self):
        response = self.client.get("/api/v1/workshop-reporting/schedule-progress-statuses/", {
            "schedule_ids": str(self.schedule.pk), "production_date": self.as_of_date.isoformat(),
        }, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["data"]), 1)
        row = response.data["data"][0]
        self.assertEqual(row["schedule_id"], str(self.schedule.pk))
        self.assertEqual(row["as_of_date"], self.as_of_date.isoformat())
        for category in self.crafts:
            self.assertEqual(row["stage_progress"][category]["status"], "READY")
            self.assertEqual(row["stage_progress"][category]["percentage"], 20)
        self.assertEqual(set(row["progress"]), {"MATERIAL", "METAL", "SEWING", "ASSEMBLY"})
        for category, percentage in (("MATERIAL", 100), ("METAL", 20), ("SEWING", 20), ("ASSEMBLY", 0)):
            self.assertEqual(row["progress"][category], {
                "status": "READY", "percentage": percentage, "display": f"{percentage}%",
            })

    def test_shared_work_item_is_aggregated_separately_for_each_category(self):
        shared_item = self.lines["METAL"].work_item
        # 保留数据库允许的历史同工项标识场景，不能按 work_item_id 抹掉所属方案分类。
        for category, quantity in (("METAL", 80), ("CUTTING", 30), ("SEWING", 10)):
            line = self.lines[category]
            WageSchemeLine.objects.filter(pk=line.pk).update(work_item=shared_item)
            WorkReportLine.objects.filter(scheme_line=line).update(
                work_item=shared_item, quantity=quantity, amount=quantity,
            )
        result = self.progress()
        self.assertEqual(
            {category: result["stage_progress"][category]["percentage"] for category in self.crafts},
            {"METAL": 80, "CUTTING": 30, "SEWING": 10},
        )

    def test_referenced_craft_category_change_is_rejected_by_database(self):
        with self.assertRaisesRegex(IntegrityError, "referenced craft type or plan category cannot be changed"):
            with transaction.atomic():
                Craft.objects.filter(pk=self.crafts["METAL"].pk).update(plan_category=None)
        self.assertEqual(Craft.objects.get(pk=self.crafts["METAL"].pk).plan_category, "METAL")
        self.assertEqual(self.progress()["stage_progress"]["METAL"]["percentage"], 20)

    def test_each_active_work_item_is_capped_before_stage_percentage(self):
        second = self.make_line(self.schemes["METAL"], line_number=2)
        void = self.make_line(self.schemes["METAL"], line_number=3, required="1000", status="VOID")
        self.make_report(self.lines["METAL"], quantity="200")
        self.make_report(void, quantity="1000")
        self.assertEqual(self.progress()["stage_progress"]["METAL"]["percentage"], 50)
        self.make_report(second, quantity="25")
        self.assertEqual(self.progress()["stage_progress"]["METAL"]["percentage"], 62)

    @override_settings(
        MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True,
    )
    def test_hidden_workshop_crafts_remain_unknown(self):
        self.scoped_actor()
        self.grant("production_scheduling.view_productionschedule", "WORKSHOP", [self.workshop])
        result = self.progress(request=self.scoped_request())
        self.assertEqual(result["stage_progress"]["METAL"]["percentage"], 20)
        for category in ("CUTTING", "SEWING"):
            stage = result["stage_progress"][category]
            self.assertEqual(stage["status"], "NOT_CONFIGURED")
            self.assertIsNone(stage["percentage"])
            self.assertEqual(stage["products"][0]["status"], "NOT_CONFIGURED")
            self.assertIsNone(stage["products"][0]["percentage"])

    def test_overlapping_approved_versions_are_rejected_by_database(self):
        with self.assertRaises(IntegrityError) as raised:
            with transaction.atomic():
                self.make_scheme("METAL", parent=self.schemes["METAL"])
        self.assertIn("wage_scheme_approved_scope_no_overlap", str(raised.exception))
        self.assertEqual(self.progress()["stage_progress"]["METAL"]["percentage"], 20)

    def test_expired_and_future_scheme_versions_do_not_change_current_denominator(self):
        expired = self.schemes["METAL"]
        WageScheme.objects.filter(pk=expired.pk).update(effective_to=self.as_of_date - timedelta(days=2))
        WorkReport.objects.filter(scheme=expired).update(production_date=self.as_of_date - timedelta(days=3))
        current = self.make_scheme(
            "METAL", parent=expired, effective_from=self.as_of_date - timedelta(days=1),
            effective_to=self.as_of_date + timedelta(days=1),
        )
        self.make_line(current, work_item=self.lines["METAL"].work_item)
        future = self.make_scheme("METAL", parent=current, effective_from=self.as_of_date + timedelta(days=2))
        self.make_line(future, work_item=self.lines["METAL"].work_item, required="500")
        result = self.progress()
        self.assertEqual(result["stage_progress"]["METAL"]["status"], "READY")
        self.assertEqual(result["stage_progress"]["METAL"]["percentage"], 20)
        # 日期闭区间边界仍选当前版本；下一天才采用未来版本的分母。
        self.assertEqual(self.progress(as_of_date=self.as_of_date + timedelta(days=1))
                         ["stage_progress"]["METAL"]["percentage"], 20)
        self.assertEqual(self.progress(as_of_date=self.as_of_date + timedelta(days=2))
                         ["stage_progress"]["METAL"]["percentage"], 4)

    def test_report_aggregate_does_not_read_unrelated_category_work_item_pairs(self):
        metal_item_id = self.lines["METAL"].work_item_id
        cutting_item = self.lines["CUTTING"].work_item
        expired = self.schemes["CUTTING"]
        WageScheme.objects.filter(pk=expired.pk).update(effective_to=self.as_of_date - timedelta(days=2))
        WageSchemeLine.objects.filter(pk=self.lines["CUTTING"].pk).update(work_item_id=metal_item_id)
        WorkReport.objects.filter(scheme=expired).update(production_date=self.as_of_date - timedelta(days=3))
        WorkReportLine.objects.filter(scheme_line=self.lines["CUTTING"]).update(work_item_id=metal_item_id)
        current = self.make_scheme("CUTTING", parent=expired, effective_from=self.as_of_date - timedelta(days=1))
        self.make_line(current, work_item=cutting_item)
        with CaptureQueriesContext(connection) as captured:
            self.progress()
        aggregate_queries = [
            query["sql"] for query in captured.captured_queries
            if query["sql"].lstrip().startswith("SELECT")
            and f'FROM "{WorkReportLine._meta.db_table}"' in query["sql"]
            and "SUM(" in query["sql"] and "GROUP BY" in query["sql"]
        ]
        self.assertEqual(len(aggregate_queries), 1)
        # 在隔离测试库重放已捕获的只读聚合 SQL，核对真正返回的行，不能只看最终百分比。
        with connection.cursor() as cursor:
            cursor.execute(aggregate_queries[0])
            names = [column[0] for column in cursor.description]
            item_index = names.index("work_item_id")
            category_index = names.index("report__scheme__scope_craft__plan_category")
            rows = cursor.fetchall()
        pairs = {(row[category_index], row[item_index]) for row in rows}
        self.assertNotIn(("CUTTING", metal_item_id), pairs)
        self.assertEqual(pairs, {("METAL", metal_item_id), ("SEWING", self.lines["SEWING"].work_item_id)})
        self.assertEqual(len(rows), 2)
