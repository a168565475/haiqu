"""排产完结只依据四项真实进度，并保留生产数量及批次事实。"""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.access_control.tests import test_resource_scopes as scoped_fixtures
from apps.core.api.concurrency import etag_for_instance
from apps.customers.models import CustomerAssignment
from apps.inventory.models import FinishedGoodsReceipt, Warehouse, WarehouseLocation, WarehouseZone
from apps.organizations.models import Employee
from apps.products.models import ProductInformation
from apps.production_tasks.models import ProductionRunBatch, ProductionTaskProduct, ProductionTaskStatus
from apps.reference_data.models import ProductionUnit
from apps.sales_orders.models import (
    CollaborationEventStatus, CollaborationEventType, SalesOrder, SalesOrderCollaborationEvent,
    SalesOrderDeliveryBatch, SalesOrderDeliveryBatchLine, SalesOrderLine, SalesOrderStatus,
)
from apps.workshop_config.models import Craft, Operation, Workshop, WorkshopEmployee
from apps.workshop_reporting.models import (
    WageScheme, WageSchemeCraft, WageSchemeLine, WorkItem, WorkReport, WorkReportLine,
)

from ..models import ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft
from . import test_production_scheduling_api as schedule_fixtures


class ScheduleCompleteApiTests(APITestCase):
    def setUp(self):
        # 只复用初始化；继承旧测试类会重复执行其全部历史用例。
        schedule_fixtures.ProductionSchedulingApiTests.setUp(self)
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="production_tasks", codename="change_productiontask",
        ))
        self.schedule = ProductionSchedule.objects.create(
            schedule_number="PC-COMPLETE-TEST", production_task=self.task,
            source_revision_hash="complete-test", client_request_id=uuid.uuid4(),
            request_payload_hash="complete-test", created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        today = timezone.localdate()
        self.plan = ProductionScheduleProduct.objects.create(
            schedule=self.schedule, product_line=self.line, line_number=1,
            planned_quantity=self.line.quantity, source_quantity_snapshot=self.line.quantity,
            unit=self.line.unit, unit_name_snapshot=self.line.unit.unit_name,
            material_inbound_date=today, metal_return_date=today,
            sewing_return_date=today, finished_inbound_date=today,
            product_snapshot={"product_name": self.line.product_name_snapshot},
            source_revision_hash="complete-test",
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=self.plan, craft=self.internal_craft, craft_type_snapshot="INTERNAL",
            craft_name_snapshot=self.internal_craft.name, plan_category="METAL",
        )
        self.task.status = ProductionTaskStatus.IN_PRODUCTION
        self.task.save(update_fields=["status", "updated_at"])
        self.authenticate()

    def authenticate(self, user=None):
        self.client.force_authenticate(get_user_model().objects.get(pk=(user or self.user).pk))

    def complete(self, *, changes=None, schedule_etag=None, omit_schedule_etag=False):
        self.schedule.refresh_from_db()
        self.task.refresh_from_db()
        payload = {"reason": "四项进度达到100%，按排产完结", "task_etag": etag_for_instance(self.task)}
        payload.update(changes or {})
        headers = {} if omit_schedule_etag else {
            "HTTP_IF_MATCH": schedule_etag or etag_for_instance(self.schedule),
        }
        return self.client.post(
            f"/api/v1/production-schedules/{self.schedule.pk}/complete/", payload,
            format="json", **headers,
        )

    def preview(self):
        return self.client.get(f"/api/v1/production-schedules/{self.schedule.pk}/completion-preview/")

    def progress_rows(self, **changes):
        progress = {
            key: {"status": "READY", "percentage": 100, "display": "100%"}
            for key in ("MATERIAL", "METAL", "SEWING", "ASSEMBLY")
        }
        progress.update(changes)
        return [{"schedule_id": str(self.schedule.pk), "progress": progress}]

    def assert_task_unchanged(self):
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, ProductionTaskStatus.IN_PRODUCTION)
        self.assertIsNone(self.task.completed_at)
        self.assertFalse(AuditLog.objects.filter(object_id=self.task.pk, action="COMPLETED").exists())
        self.assertFalse(AuditLog.objects.filter(object_id=self.schedule.pk, action="COMPLETED").exists())

    def link_sales_order(self, *, ready=False, status=SalesOrderStatus.CONFIRMED):
        order = SalesOrder.objects.create(
            order_number="COMPLETE-SALES-001", source_type="DIRECT", customer_account=self.customer,
            salesperson=self.employee, order_date=self.task.order_date, currency_code="CNY", status=status,
        )
        sales_line = SalesOrderLine.objects.create(
            sales_order=order, line_number=1, product=self.product,
            product_number_snapshot=self.product.product_number,
            product_name_snapshot=self.product.product_name, unit_code_snapshot=self.product.unit.unit_code,
            quantity=100, unit_price=10, line_total=1000,
        )
        batch = SalesOrderDeliveryBatch.objects.create(
            sales_order=order, line_number=1, batch_number="B1", planned_delivery_date=self.task.delivery_date,
        )
        batch_line = SalesOrderDeliveryBatchLine.objects.create(
            delivery_batch=batch, sales_order_line=sales_line, quantity=100,
        )
        self.task.sales_order = order
        self.task.sales_order_delivery_batch = batch
        self.task.sales_order_line = sales_line
        self.task.save(update_fields=["sales_order", "sales_order_delivery_batch", "sales_order_line", "updated_at"])
        self.line.sales_order_delivery_batch_line = batch_line
        self.line.save(update_fields=["sales_order_delivery_batch_line", "updated_at"])
        if ready:
            for event_type, quantity in ((CollaborationEventType.SHIPMENT, 100), (CollaborationEventType.BALANCE, None)):
                SalesOrderCollaborationEvent.objects.create(
                    sales_order=order, event_type=event_type, status=CollaborationEventStatus.COMPLETED,
                    title="销售完结条件测试", quantity=quantity, occurred_at=timezone.now(),
                    recorded_by_employee=self.employee,
                )
        return order

    def grant_sales_completion(self):
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="access_control", codename="complete_salesorder",
        ))
        self.authenticate()

    def grant_sales_read(self):
        self.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="sales_orders", codename="view_salesorder",
        ))
        self.authenticate()

    def seed_completed_craft(self, craft):
        ProductionScheduleProductCraft.objects.get_or_create(
            schedule_product=self.plan, craft=craft,
            defaults={"craft_type_snapshot": "INTERNAL", "craft_name_snapshot": craft.name,
                      "plan_category": craft.plan_category},
        )
        token = craft.plan_category
        scheme = WageScheme.objects.create(
            scheme_number=f"COMPLETE-GJ-{token}", product_line=self.line, schedule_product=self.plan,
            workshop=craft.workshop, scope_craft=craft, status="APPROVED", effective_from=timezone.localdate(),
            product_name_snapshot=self.product.product_name, product_number_snapshot=self.product.product_number,
            operation_product_name_snapshot=self.product.product_name, created_by_employee=self.employee,
            updated_by_employee=self.employee, approved_by_employee=self.employee, approved_at=timezone.now(),
        )
        WageSchemeCraft.objects.create(scheme=scheme, craft=craft)
        operation = Operation.objects.create(
            operation_number=f"COMPLETE-OP-{token}", product_name=self.product.product_name,
            craft=craft, name="完结测试工序", reporting_unit=self.line.unit,
        )
        item = WorkItem.objects.create(
            product_line=self.line, workshop=craft.workshop, craft=craft, operation=operation,
            unit=self.line.unit, identity_key=f"complete-{token}", display_name="完结测试工序", counting_mode="ORDER",
        )
        scheme_line = WageSchemeLine.objects.create(
            scheme=scheme, work_item=item, line_number=1, counting_mode="ORDER",
            display_name_snapshot=item.display_name, craft_name_snapshot=craft.name,
            operation_name_snapshot=operation.name, operation_number_snapshot=operation.operation_number,
            unit_name_snapshot=self.line.unit.unit_name, declared_price=1,
            order_quantity_snapshot=self.line.quantity, required_quantity_snapshot=self.line.quantity,
        )
        worker = WorkshopEmployee.objects.create(
            workshop=craft.workshop, position="测试", name=f"完结测试员{token}", is_supervisor=False,
        )
        report = WorkReport.objects.create(
            report_number=f"COMPLETE-BG-{token}", production_date=timezone.localdate(), product_line=self.line,
            schedule_product=self.plan, workshop=craft.workshop, scheme=scheme, scheme_version_snapshot=1,
            recorder_employee=self.employee, updated_by_employee=self.employee, total_amount=self.line.quantity,
            client_request_id=uuid.uuid4(), request_payload_hash=f"complete-{token}",
        )
        WorkReportLine.objects.create(
            report=report, line_number=1, scheme_line=scheme_line, work_item=item, workshop_employee=worker,
            production_line=1, quantity=self.line.quantity, order_quantity_snapshot=self.line.quantity,
            required_quantity_snapshot=self.line.quantity, unit_price_snapshot=1, amount=self.line.quantity,
            display_name_snapshot=item.display_name, craft_name_snapshot=craft.name,
            operation_name_snapshot=operation.name, unit_name_snapshot=self.line.unit.unit_name,
            employee_name_snapshot=worker.name,
        )

    def seed_completed_progress(self):
        workshop, _ = Workshop.objects.get_or_create(name="车缝车间")
        sewing_craft = Craft.objects.create(
            craft_type="INTERNAL", workshop=workshop, name="完结测试车缝", plan_category="SEWING",
        )
        self.seed_completed_craft(self.internal_craft)
        self.seed_completed_craft(sewing_craft)
        warehouse = Warehouse.objects.create(
            warehouse_number="COMPLETE-WH", warehouse_name="完结测试成品仓", warehouse_type="FINISHED",
        )
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name="完结测试区")
        location = WarehouseLocation.objects.create(zone=zone, location_number="01")
        FinishedGoodsReceipt.objects.create(
            receipt_number="COMPLETE-RK-001", production_task_product=self.line, location=location,
            task_number_snapshot=self.task.task_number, order_number_snapshot=self.task.order_number,
            product_number_snapshot=self.product.product_number, product_name_snapshot=self.product.product_name,
            item_number_snapshot=self.product.product_item.item_number, actual_color=self.color.color_name,
            unit=self.line.unit, received_quantity=self.line.quantity, remaining_quantity=0,
            received_by_employee=self.employee,
        )

    def test_real_report_and_receipt_progress_can_complete_without_fabricating_quantities(self):
        self.seed_completed_progress()
        progress_response = self.client.get("/api/v1/workshop-reporting/schedule-progress-statuses/", {
            "schedule_ids": str(self.schedule.pk),
        })
        self.assertEqual(progress_response.status_code, 200, progress_response.data)
        before_progress = progress_response.data["data"][0]["progress"]
        self.assertEqual(set(before_progress), {"MATERIAL", "METAL", "SEWING", "ASSEMBLY"})
        self.assertTrue(all(row["percentage"] == 100 for row in before_progress.values()))

        response = self.complete()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["progress"], before_progress)
        self.assertEqual(response.data["data"]["sales_sync"]["status"], "NOT_APPLICABLE")
        self.assertEqual(response.data["data"]["production_sync"], {
            "before_status": "IN_PRODUCTION", "after_status": "COMPLETED",
        })
        self.assertIsNone(response.data["data"]["sales_sync"]["before_status"])
        self.assertIsNone(response.data["data"]["sales_sync"]["after_status"])
        self.task.refresh_from_db()
        self.schedule.refresh_from_db()
        self.assertEqual(self.task.status, ProductionTaskStatus.COMPLETED)
        self.assertIsNotNone(self.task.completed_at)
        self.assertEqual(self.task.actual_quantity, 0)
        self.assertEqual(self.task.actual_good_quantity, 0)
        self.assertFalse(self.task.run_batches.exists())
        self.assertEqual(response["ETag"], etag_for_instance(self.schedule))
        self.assertEqual(AuditLog.objects.filter(object_id=self.task.pk, action="COMPLETED").count(), 1)
        self.assertEqual(AuditLog.objects.filter(object_id=self.schedule.pk, action="COMPLETED").count(), 1)

    def test_each_percentage_must_be_exactly_one_hundred(self):
        for category in ("MATERIAL", "METAL", "SEWING", "ASSEMBLY"):
            for percentage in (0, 99, None, 101):
                with self.subTest(category=category, percentage=percentage), patch(
                    "apps.production_scheduling.completion.schedule_progress_statuses",
                    return_value=self.progress_rows(**{category: {"percentage": percentage}}),
                ):
                    response = self.complete()
                    self.assertEqual(response.status_code, 409, response.data)
                    self.assert_task_unchanged()

    def test_rounded_real_progress_at_one_hundred_can_complete_with_199_of_200(self):
        self.line.quantity = 200
        self.line.save(update_fields=["quantity", "updated_at"])
        self.plan.planned_quantity = 200
        self.plan.source_quantity_snapshot = 200
        self.plan.save(update_fields=["planned_quantity", "source_quantity_snapshot", "updated_at"])
        self.seed_completed_progress()
        WorkReportLine.objects.filter(report__schedule_product=self.plan).update(quantity=199, amount=199)
        WorkReport.objects.filter(schedule_product=self.plan).update(total_amount=199)
        FinishedGoodsReceipt.objects.filter(production_task_product=self.line).update(received_quantity=199)
        progress_response = self.client.get("/api/v1/workshop-reporting/schedule-progress-statuses/", {
            "schedule_ids": str(self.schedule.pk),
        })
        self.assertEqual(progress_response.status_code, 200, progress_response.data)
        progress = progress_response.data["data"][0]["progress"]
        self.assertTrue(all(row["percentage"] == 100 for row in progress.values()), progress)
        response = self.complete()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["progress"], progress)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, ProductionTaskStatus.COMPLETED)
        self.assertEqual(self.task.actual_quantity, 0)
        self.assertEqual(self.task.actual_good_quantity, 0)
        self.assertEqual(list(WorkReportLine.objects.filter(
            report__schedule_product=self.plan,
        ).values_list("quantity", flat=True)), [Decimal("199"), Decimal("199")])
        self.assertEqual(FinishedGoodsReceipt.objects.get(production_task_product=self.line).received_quantity, 199)

    def test_missing_progress_or_category_cannot_pass_empty_all_check(self):
        invalid_rows = [[], [{"schedule_id": str(self.schedule.pk), "progress": {}}]]
        for category in ("MATERIAL", "METAL", "SEWING", "ASSEMBLY"):
            rows = self.progress_rows()
            del rows[0]["progress"][category]
            invalid_rows.append(rows)
        for rows in invalid_rows:
            with self.subTest(rows=rows), patch(
                "apps.production_scheduling.completion.schedule_progress_statuses", return_value=rows,
            ):
                response = self.complete()
                self.assertEqual(response.status_code, 409, response.data)
                self.assert_task_unchanged()

    def test_schedule_etag_is_required(self):
        response = self.complete(omit_schedule_etag=True)
        self.assertEqual(response.status_code, 428, response.data)
        self.assert_task_unchanged()

    def test_stale_schedule_etag_cannot_finish_task(self):
        response = self.complete(schedule_etag='"stale-schedule"')
        self.assertEqual(response.status_code, 412, response.data)
        self.assert_task_unchanged()

    def test_stale_client_task_etag_cannot_be_replaced_with_server_version(self):
        response = self.complete(changes={"task_etag": '"stale-task"'})
        self.assertEqual(response.status_code, 412, response.data)
        self.assert_task_unchanged()

    def test_reason_and_task_etag_are_required_and_blank_values_are_rejected(self):
        for field in ("reason", "task_etag"):
            for value in ("", "   ", None):
                with self.subTest(field=field, value=value):
                    response = self.complete(changes={field: value})
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assert_task_unchanged()
        for payload in ({"reason": "缺少任务版本"}, {"task_etag": etag_for_instance(self.task)}):
            with self.subTest(payload=payload):
                response = self.client.post(
                    f"/api/v1/production-schedules/{self.schedule.pk}/complete/", payload,
                    format="json", HTTP_IF_MATCH=etag_for_instance(self.schedule),
                )
                self.assertEqual(response.status_code, 400, response.data)
                self.assert_task_unchanged()

    def test_completed_task_cannot_be_completed_twice_or_create_duplicate_audits(self):
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()):
            response = self.complete()
            self.assertEqual(response.status_code, 200, response.data)
            repeated = self.complete()
        self.assertEqual(repeated.status_code, 409, repeated.data)
        self.assertEqual(AuditLog.objects.filter(object_id=self.task.pk, action="COMPLETED").count(), 1)
        self.assertEqual(AuditLog.objects.filter(object_id=self.schedule.pk, action="COMPLETED").count(), 1)

    def test_reason_longer_than_five_hundred_characters_is_rejected(self):
        response = self.complete(changes={"reason": "完" * 501})
        self.assertEqual(response.status_code, 400, response.data)
        self.assert_task_unchanged()

    def test_schedule_read_permission_does_not_grant_task_completion(self):
        self.user.user_permissions.remove(Permission.objects.get(
            content_type__app_label="production_tasks", codename="change_productiontask",
        ))
        self.authenticate()
        response = self.complete()
        self.assertEqual(response.status_code, 403, response.data)
        self.assert_task_unchanged()

    def test_task_completion_permission_does_not_bypass_schedule_read_permission(self):
        self.user.user_permissions.remove(*Permission.objects.filter(content_type__app_label="production_scheduling"))
        self.authenticate()
        response = self.complete()
        self.assertEqual(response.status_code, 403, response.data)
        self.assert_task_unchanged()

    def test_schedule_view_all_does_not_expand_task_finish_scope(self):
        other_user = get_user_model().objects.create_user(username="completion-outside-task-scope")
        Employee.objects.create(user=other_user, employee_code="COMPLETE-OUTSIDE", display_name="范围外操作员")
        other_user.user_permissions.add(*Permission.objects.filter(
            codename__in=["view_productionschedule", "view_all_productionschedule", "change_productiontask"],
            content_type__app_label__in=["production_scheduling", "production_tasks"],
        ))
        self.authenticate(other_user)
        response = self.complete()
        self.assertEqual(response.status_code, 403, response.data)
        self.assert_task_unchanged()

    @override_settings(
        ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
        SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True,
    )
    def test_scoped_roles_require_dedicated_finish_grant_instead_of_change_grant(self):
        self.user.user_permissions.clear()
        self.scope_user, self.scope_employee = self.user, self.employee
        scoped_fixtures.ScopedActorMixin.grant(self, "production_scheduling.view_productionschedule")
        scoped_fixtures.ScopedActorMixin.grant(self, "production_tasks.change_productiontask")
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()):
            denied = self.complete()
        self.assertEqual(denied.status_code, 403, denied.data)
        self.assert_task_unchanged()
        scoped_fixtures.ScopedActorMixin.grant(self, "access_control.finish_productiontask")
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()):
            completed = self.complete()
        self.assertEqual(completed.status_code, 200, completed.data)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, ProductionTaskStatus.COMPLETED)

    def test_sales_order_with_unmet_conditions_is_skipped_while_task_completes(self):
        order = self.link_sales_order()
        self.grant_sales_completion()
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()), patch(
            "apps.production_scheduling.completion.complete_sales_order",
        ) as sales_complete:
            response = self.complete(changes={"sales_order_etag": etag_for_instance(order)})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["sales_sync"]["status"], "SKIPPED")
        self.assertTrue(response.data["data"]["sales_sync"]["reason"])
        sales_complete.assert_not_called()
        order.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual(order.status, SalesOrderStatus.CONFIRMED)
        self.assertEqual(self.task.status, ProductionTaskStatus.COMPLETED)

    def test_sales_order_ready_for_normal_completion_is_synchronized(self):
        order = self.link_sales_order(ready=True)
        self.grant_sales_completion()
        self.grant_sales_read()
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()):
            response = self.complete(changes={"sales_order_etag": etag_for_instance(order)})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["sales_sync"]["status"], "COMPLETED")
        self.assertEqual(response.data["data"]["sales_sync"]["before_status"], "CONFIRMED")
        self.assertEqual(response.data["data"]["sales_sync"]["after_status"], "COMPLETED")
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrderStatus.COMPLETED)
        self.assertEqual(order.collaboration_events.filter(event_type=CollaborationEventType.NOTE).count(), 1)

    def test_sales_order_without_completion_permission_is_not_modified(self):
        order = self.link_sales_order(ready=True)
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()):
            response = self.complete(changes={"sales_order_etag": etag_for_instance(order)})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["sales_sync"]["status"], "SKIPPED")
        self.assertTrue(response.data["data"]["sales_sync"]["reason"])
        self.assertIsNone(response.data["data"]["sales_sync"]["before_status"])
        self.assertIsNone(response.data["data"]["sales_sync"]["after_status"])
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrderStatus.CONFIRMED)

    def test_stale_sales_order_etag_skips_sales_synchronization(self):
        order = self.link_sales_order(ready=True)
        self.grant_sales_completion()
        self.grant_sales_read()
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()):
            response = self.complete(changes={"sales_order_etag": '"stale-sales"'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["sales_sync"]["status"], "SKIPPED")
        self.assertEqual(response.data["data"]["sales_sync"]["before_status"], "CONFIRMED")
        self.assertEqual(response.data["data"]["sales_sync"]["after_status"], "CONFIRMED")
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrderStatus.CONFIRMED)

    def test_missing_sales_order_etag_skips_sales_synchronization(self):
        order = self.link_sales_order(ready=True)
        self.grant_sales_completion()
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()):
            response = self.complete()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["sales_sync"]["status"], "SKIPPED")
        self.assertTrue(response.data["data"]["sales_sync"]["reason"])
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrderStatus.CONFIRMED)

    def test_sales_completion_permission_does_not_expand_sales_order_scope(self):
        order = self.link_sales_order(ready=True)
        self.grant_sales_completion()
        outsider = Employee.objects.create(employee_code="COMPLETE-SALES-OWNER", display_name="其他销售负责人")
        order.salesperson = outsider
        order.save(update_fields=["salesperson", "updated_at"])
        CustomerAssignment.objects.filter(customer_account=self.customer).update(
            effective_from=timezone.now() - timedelta(days=2), effective_to=timezone.now() - timedelta(days=1),
        )
        self.authenticate()
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()), patch(
            "apps.production_scheduling.completion.complete_sales_order",
        ) as sales_complete:
            response = self.complete(changes={"sales_order_etag": etag_for_instance(order)})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["sales_sync"]["status"], "SKIPPED")
        sales_complete.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrderStatus.CONFIRMED)

    def test_already_completed_sales_order_is_reported_without_duplicate_completion(self):
        order = self.link_sales_order(status=SalesOrderStatus.COMPLETED)
        self.grant_sales_completion()
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()), patch(
            "apps.production_scheduling.completion.complete_sales_order",
        ) as sales_complete:
            response = self.complete(changes={"sales_order_etag": etag_for_instance(order)})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["sales_sync"]["status"], "ALREADY_COMPLETED")
        sales_complete.assert_not_called()

    def test_unexpected_sales_failure_rolls_back_task_schedule_and_audits(self):
        order = self.link_sales_order(ready=True)
        self.grant_sales_completion()
        self.schedule.refresh_from_db()
        before_updated_at = self.schedule.updated_at
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()), patch(
            "apps.production_scheduling.completion.complete_sales_order", side_effect=RuntimeError("unexpected sales failure"),
        ):
            with self.assertRaisesMessage(RuntimeError, "unexpected sales failure"):
                self.complete(changes={"sales_order_etag": etag_for_instance(order)})
        self.assert_task_unchanged()
        self.schedule.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.schedule.updated_at, before_updated_at)
        self.assertEqual(order.status, SalesOrderStatus.CONFIRMED)

    def test_extra_quantities_and_batches_are_rejected_and_existing_values_are_preserved(self):
        self.link_sales_order()
        self.task.actual_quantity = Decimal("17")
        self.task.actual_good_quantity = Decimal("15")
        self.task.excess_quantity = Decimal("2")
        self.task.save(update_fields=["actual_quantity", "actual_good_quantity", "excess_quantity", "updated_at"])
        for index, status in enumerate(("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"), start=1):
            ProductionRunBatch.objects.create(
                production_task=self.task, batch_number=f"EXISTING-{index}", planned_quantity=25,
                actual_quantity=index, good_quantity=index, status=status, note="保留历史批次",
            )
        before_batches = list(self.task.run_batches.order_by("id").values())
        response = self.complete(changes={"actual_quantity": "999", "actual_good_quantity": "999", "run_batches": []})
        self.assertEqual(response.status_code, 400, response.data)
        self.assert_task_unchanged()
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()):
            completed = self.complete()
        self.assertEqual(completed.status_code, 200, completed.data)
        self.task.refresh_from_db()
        self.assertEqual((self.task.actual_quantity, self.task.actual_good_quantity, self.task.excess_quantity), (
            Decimal("17"), Decimal("15"), Decimal("2"),
        ))
        self.assertEqual(list(self.task.run_batches.order_by("id").values()), before_batches)

    def test_session_write_without_csrf_token_is_rejected(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(
            f"/api/v1/production-schedules/{self.schedule.pk}/complete/",
            {"reason": "测试CSRF保护", "task_etag": etag_for_instance(self.task)},
            format="json", HTTP_IF_MATCH=etag_for_instance(self.schedule),
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertIn("CSRF", str(response.data))
        self.assert_task_unchanged()

    def test_preview_is_read_only_and_uses_order_quantity_and_receipt_originals(self):
        self.seed_completed_progress()
        self.line.material_snapshot = "PE"
        self.line.save(update_fields=["material_snapshot", "updated_at"])
        self.plan.planned_quantity = 80
        self.plan.product_snapshot = {
            "product_name": "排产快照产品", "specification": "100x100；颜色：红；材质：PE", "color_name": "红",
        }
        self.plan.save(update_fields=["planned_quantity", "product_snapshot", "updated_at"])
        self.schedule.refresh_from_db()
        self.task.refresh_from_db()
        before_schedule = (self.schedule.updated_at, self.schedule.version)
        before_task = (self.task.status, self.task.updated_at, self.task.completed_at)
        before_audits = AuditLog.objects.count()
        response = self.preview()
        self.assertEqual(response.status_code, 200, response.data)
        result = response.data["data"]
        self.assertEqual(result["schedule_id"], str(self.schedule.pk))
        self.assertEqual(result["schedule_number"], self.schedule.schedule_number)
        self.assertEqual(response["ETag"], etag_for_instance(self.schedule))
        self.assertEqual(result["schedule_etag"], response["ETag"])
        self.assertEqual(result["task"], {
            "id": str(self.task.pk), "task_number": self.task.task_number, "status": "IN_PRODUCTION",
            "status_display": self.task.get_status_display(), "etag": etag_for_instance(self.task),
        })
        self.assertEqual(result["products"], [{
            "schedule_product_id": str(self.plan.pk), "product_name": "排产快照产品",
            "specification": "100x100", "color": "红", "material": "PE",
            "required_quantity": 100, "received_quantity": 100, "unit_name": self.line.unit.unit_name,
        }])
        self.assertTrue(all(row["percentage"] == 100 for row in result["progress"].values()))
        self.assertEqual(result["sales_order"], {
            "id": None, "order_number": None, "status": None, "status_display": None,
            "etag": None, "can_sync": False, "reason": "生产任务未关联销售订单。",
        })
        self.schedule.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual((self.schedule.updated_at, self.schedule.version), before_schedule)
        self.assertEqual((self.task.status, self.task.updated_at, self.task.completed_at), before_task)
        self.assertEqual(AuditLog.objects.count(), before_audits)
        self.assertEqual(FinishedGoodsReceipt.objects.get(production_task_product=self.line).remaining_quantity, 0)

    def test_preview_keeps_multiple_product_quantities_and_units_separate(self):
        self.seed_completed_progress()
        unit = ProductionUnit.objects.create(unit_code="COMPLETE-SETS", unit_name="完结测试套")
        product = ProductInformation.objects.create(
            product_number="COMPLETE-PRODUCT-002", product_code="COMPLETE-CODE-002",
            category=self.product.category, product_name="第二个产品", specification="第二规格",
            unit=unit, product_item=self.product.product_item, scale="REGULAR",
        )
        line = ProductionTaskProduct.objects.create(
            production_task=self.task, line_number=2, product=product,
            product_number_snapshot=product.product_number, product_name_snapshot=product.product_name,
            specification_snapshot=product.specification, quantity=30, unit=unit,
            currency=self.currency, unit_price=10, total_amount=300, exchange_rate=1,
        )
        today = timezone.localdate()
        plan = ProductionScheduleProduct.objects.create(
            schedule=self.schedule, product_line=line, line_number=2, planned_quantity=15,
            source_quantity_snapshot=30, unit=unit, unit_name_snapshot=unit.unit_name,
            material_inbound_date=today, metal_return_date=today, sewing_return_date=today,
            finished_inbound_date=today, product_snapshot={"product_name": product.product_name},
            source_revision_hash="complete-multiple",
        )
        ProductionScheduleProductCraft.objects.create(
            schedule_product=plan, craft=self.internal_craft, craft_type_snapshot="INTERNAL",
            craft_name_snapshot=self.internal_craft.name, plan_category="METAL",
        )
        location = FinishedGoodsReceipt.objects.get(production_task_product=self.line).location
        FinishedGoodsReceipt.objects.create(
            receipt_number="COMPLETE-RK-002", production_task_product=line, location=location,
            task_number_snapshot=self.task.task_number, order_number_snapshot=self.task.order_number,
            product_number_snapshot=product.product_number, product_name_snapshot=product.product_name,
            item_number_snapshot=product.product_item.item_number, actual_color="蓝", unit=unit,
            received_quantity=20, remaining_quantity=0, received_by_employee=self.employee,
        )
        response = self.preview()
        self.assertEqual(response.status_code, 200, response.data)
        products = response.data["data"]["products"]
        self.assertEqual(len(products), 2)
        self.assertEqual([(row["required_quantity"], row["received_quantity"], row["unit_name"]) for row in products], [
            (100, 100, self.line.unit.unit_name), (30, 20, unit.unit_name),
        ])

    def test_preview_requires_both_schedule_read_and_task_completion_permissions(self):
        permissions = list(self.user.user_permissions.all())
        for missing_app in ("production_scheduling", "production_tasks"):
            with self.subTest(missing_app=missing_app):
                self.user.user_permissions.set([permission for permission in permissions if permission.content_type.app_label != missing_app])
                self.authenticate()
                response = self.preview()
                self.assertEqual(response.status_code, 403, response.data)
                self.assert_task_unchanged()

    def test_preview_does_not_expand_task_finish_scope_with_schedule_view_all(self):
        user = get_user_model().objects.create_user(username="preview-outside-task-scope")
        Employee.objects.create(user=user, employee_code="PREVIEW-OUTSIDE", display_name="预览范围外操作员")
        user.user_permissions.add(*Permission.objects.filter(
            codename__in=["view_productionschedule", "view_all_productionschedule", "change_productiontask"],
            content_type__app_label__in=["production_scheduling", "production_tasks"],
        ))
        self.authenticate(user)
        response = self.preview()
        self.assertEqual(response.status_code, 403, response.data)
        self.assert_task_unchanged()

    def test_preview_hides_sales_details_without_sales_read_permission(self):
        self.link_sales_order(ready=True)
        self.grant_sales_completion()
        response = self.preview()
        self.assertEqual(response.status_code, 200, response.data)
        sales = response.data["data"]["sales_order"]
        for field in ("id", "order_number", "status", "status_display", "etag"):
            self.assertIsNone(sales[field], field)
        self.assertFalse(sales["can_sync"])
        self.assertTrue(sales["reason"])

    def test_preview_sales_read_access_does_not_grant_completion_and_conditions_are_rechecked(self):
        order = self.link_sales_order()
        self.grant_sales_read()
        response = self.preview()
        self.assertEqual(response.status_code, 200, response.data)
        sales = response.data["data"]["sales_order"]
        self.assertEqual(sales["id"], str(order.pk))
        self.assertEqual(sales["order_number"], order.order_number)
        self.assertEqual(sales["status"], order.status)
        self.assertEqual(sales["status_display"], order.get_status_display())
        self.assertEqual(sales["etag"], etag_for_instance(order))
        self.assertFalse(sales["can_sync"])
        self.grant_sales_completion()
        permitted = self.preview()
        self.assertEqual(permitted.status_code, 200, permitted.data)
        self.assertTrue(permitted.data["data"]["sales_order"]["can_sync"])
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()):
            completed = self.complete(changes={"sales_order_etag": sales["etag"]})
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(completed.data["data"]["sales_sync"]["status"], "SKIPPED")
        self.assertEqual(completed.data["data"]["sales_sync"]["before_status"], "CONFIRMED")
        self.assertEqual(completed.data["data"]["sales_sync"]["after_status"], "CONFIRMED")
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrderStatus.CONFIRMED)

    def test_preview_sales_read_permission_does_not_bypass_sales_object_scope(self):
        order = self.link_sales_order(ready=True)
        self.grant_sales_read()
        self.grant_sales_completion()
        outsider = Employee.objects.create(employee_code="PREVIEW-SALES-OWNER", display_name="其他销售负责人")
        order.salesperson = outsider
        order.save(update_fields=["salesperson", "updated_at"])
        CustomerAssignment.objects.filter(customer_account=self.customer).update(
            effective_from=timezone.now() - timedelta(days=2), effective_to=timezone.now() - timedelta(days=1),
        )
        response = self.preview()
        self.assertEqual(response.status_code, 200, response.data)
        sales = response.data["data"]["sales_order"]
        self.assertIsNone(sales["id"])
        self.assertIsNone(sales["status"])
        self.assertIsNone(sales["etag"])
        self.assertFalse(sales["can_sync"])

    @override_settings(
        ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
        SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True,
    )
    def test_preview_sales_read_scope_does_not_expand_sales_completion_scope(self):
        order = self.link_sales_order(ready=True)
        outsider = Employee.objects.create(employee_code="PREVIEW-OTHER-SELLER", display_name="其他销售负责人")
        order.salesperson = outsider
        order.save(update_fields=["salesperson", "updated_at"])
        CustomerAssignment.objects.filter(customer_account=self.customer).update(
            effective_from=timezone.now() - timedelta(days=2), effective_to=timezone.now() - timedelta(days=1),
        )
        self.user.user_permissions.clear()
        self.scope_user, self.scope_employee = self.user, self.employee
        scoped_fixtures.ScopedActorMixin.grant(self, "production_scheduling.view_productionschedule")
        scoped_fixtures.ScopedActorMixin.grant(self, "access_control.finish_productiontask")
        scoped_fixtures.ScopedActorMixin.grant(self, "sales_orders.view_salesorder", scope="ALL")
        scoped_fixtures.ScopedActorMixin.grant(self, "access_control.complete_salesorder", scope="OWN")
        response = self.preview()
        self.assertEqual(response.status_code, 200, response.data)
        sales = response.data["data"]["sales_order"]
        self.assertEqual(sales["id"], str(order.pk))
        self.assertEqual(sales["status"], "CONFIRMED")
        self.assertFalse(sales["can_sync"])
        with patch("apps.production_scheduling.completion.schedule_progress_statuses", return_value=self.progress_rows()):
            completed = self.complete(changes={"sales_order_etag": sales["etag"]})
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(completed.data["data"]["sales_sync"]["status"], "SKIPPED")
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrderStatus.CONFIRMED)

    def test_preview_does_not_replace_submit_progress_recheck(self):
        self.seed_completed_progress()
        preview = self.preview()
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(all(row["percentage"] == 100 for row in preview.data["data"]["progress"].values()))
        FinishedGoodsReceipt.objects.filter(production_task_product=self.line).update(received_quantity=90)
        completed = self.complete(changes={"task_etag": preview.data["data"]["task"]["etag"]}, schedule_etag=preview["ETag"])
        self.assertEqual(completed.status_code, 409, completed.data)
        self.assert_task_unchanged()
