"""单元06：隔离PostgreSQL中的真实业务服务/API，不发送企微、不模拟对象授权。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from tempfile import TemporaryDirectory

from django.db import close_old_connections, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.audit.models import AuditLog
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.inventory.models import MaterialInbound, MaterialStockMovement
from apps.organizations.models import EmployeeRoleAssignment
from apps.production_tasks.services import submit_production_task, transition_production_task
from apps.wecom.models import NotificationDelivery, NotificationEvent, NotificationRule
from apps.wecom.notification_selectors import recipient_payload
from apps.workshop_config.models import Craft, Workshop

from .test_notifications import SETTINGS, create_rule, employee, grant_role


def schedule_fixture():
    from apps.production_scheduling.tests.test_production_scheduling_api import ProductionSchedulingApiTests
    fixture = ProductionSchedulingApiTests()
    fixture.setUp()
    return fixture


def receiver(actor, code, permission, *, workshop=None):
    member = employee(code)
    role = grant_role(member, code, permission, "WORKSHOP" if workshop else "MODULE")
    if workshop:
        RoleGrantResource.objects.create(grant=RoleActionGrant.objects.get(role=role), workshop=workshop)
    return member, role


@override_settings(**SETTINGS)
class ProductionConfirmationNotificationTests(APITestCase):
    def setUp(self):
        self.f = schedule_fixture()
        self.member, self.role = receiver(self.f.employee, "U06_TECH", "production_tasks.view_productiontask")
        create_rule("PRODUCTION_TASK_CONFIRMED", self.f.employee, [self.role.role_code])
        self.admin_role = grant_role(self.f.employee, "ADMINISTRATION", "production_tasks.confirm_productiontask")
        self.f.task.status = "DRAFT"
        self.f.task.includes_tax = False
        self.f.task.save()
        submit_production_task(task=self.f.task, actor_employee=self.f.employee, request=None)
        self.f.task.refresh_from_db()

    def confirm(self, suffix="confirm/", **headers):
        today = timezone.localdate().isoformat()
        return self.f.client.post(f"/api/v1/production-tasks/{self.f.task.pk}/{suffix}",
            {"decision": "CONFIRM", "follower_ids": [str(self.f.employee.pk)],
             "planned_start_date": today, "planned_end_date": today},
            format="json", **({"HTTP_IF_MATCH": etag_for_instance(self.f.task)} if not headers else headers))

    def assert_event(self):
        event = NotificationEvent.objects.get(event_code="PRODUCTION_TASK_CONFIRMED")
        self.assertEqual(event.object_id, str(self.f.task.pk))
        self.assertEqual(event.context["product_name"], self.f.line.product_name_snapshot)
        self.assertEqual(event.recipients.get().employee_id, self.member.pk)
        self.assertEqual(event.recipients.get().deliveries.count(), 2)
        self.assertEqual(NotificationDelivery.objects.get(channel="WECOM").status, "PENDING")
        self.assertTrue(AuditLog.objects.filter(object_id=self.f.task.pk, action="CONFIRMED").exists())

    def test_confirmation_api_and_duplicate(self):
        self.assertFalse(NotificationEvent.objects.exists())  # 草稿、提交不通知。
        response = self.confirm()
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_event()
        self.assertEqual(self.confirm().status_code, 412)
        self.assertEqual(NotificationEvent.objects.count(), 1)

    def test_pmc_decision_api(self):
        response = self.confirm("pmc-decision/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_event()

    def test_multiple_products_keep_truthful_product_context(self):
        from copy import copy
        from uuid import uuid4
        second = copy(self.f.line)
        second.pk, second.line_number = uuid4(), 2
        second.product_name_snapshot = "第二款真实测试产品"
        second.save(force_insert=True)
        response = self.confirm()
        self.assertEqual(response.status_code, 200, response.data)
        context = NotificationEvent.objects.get().context
        self.assertIn(self.f.line.product_name_snapshot, context["product_name"])
        self.assertIn("2项产品", context["product_name"])

    def test_legacy_confirmation_service(self):
        transition_production_task(task=self.f.task, target_status="READY", actor_employee=self.f.employee, request=None)
        self.assert_event()

    def test_missing_and_stale_etag_and_revoked_confirm_permission(self):
        self.assertEqual(self.confirm(HTTP_IF_MATCH="").status_code, 428)
        self.assertEqual(self.confirm(HTTP_IF_MATCH='"old"').status_code, 412)
        RoleActionGrant.objects.filter(role=self.admin_role).delete()
        self.assertEqual(self.confirm().status_code, 403)
        self.assertFalse(NotificationEvent.objects.exists())

    def test_confirmation_rollback_removes_event_recipients_and_deliveries(self):
        with self.assertRaisesRegex(RuntimeError, "rollback"), transaction.atomic():
            transition_production_task(task=self.f.task, target_status="READY", actor_employee=self.f.employee, request=None)
            self.assert_event()
            raise RuntimeError("rollback")
        self.f.task.refresh_from_db()
        self.assertEqual(self.f.task.status, "PENDING_VALIDATION")
        self.assertFalse(NotificationEvent.objects.exists())
        self.assertFalse(NotificationDelivery.objects.exists())

    def test_unsaved_rule_and_no_recipient_are_explicit(self):
        NotificationRule.objects.all().delete()
        transition_production_task(task=self.f.task, target_status="READY", actor_employee=self.f.employee, request=None)
        event = NotificationEvent.objects.get()
        self.assertEqual(event.status, "CONFIG_MISSING")
        self.assertFalse(event.recipients.exists())


@override_settings(**SETTINGS)
class ProcurementInventoryNotificationTests(APITestCase):
    def setUp(self):
        from apps.procurement.tests.test_purchase_completion_api import PurchaseCompletionApiTests
        self.f = PurchaseCompletionApiTests()
        self.f.setUp()
        # 该历史夹具的管材没有根米参数，改为普通配件，不能拿旧管材绕过现有入库门禁。
        self.f.bom_line.section.section_type = "ACCESSORY"
        self.f.bom_line.section.title = "配件"
        self.f.bom_line.section.save()
        self.f.purchase_line.section_type_snapshot = "ACCESSORY"
        self.f.purchase_line.section_title_snapshot = "配件"
        self.f.purchase_line.save()
        for event, name, permission in [
            ("MATERIAL_RECEIPT_RECORDED", "U06_QUALITY", "inventory.quality_confirm_material"),
            ("MATERIAL_INSPECTION_CONFIRMED", "U06_PURCHASE", "procurement.view_purchaseorder"),
            ("PURCHASE_ORDER_COMPLETED", "U06_ADMIN", "procurement.view_purchaseorder"),
        ]:
            member, role = receiver(self.f.employee, name, permission)
            create_rule(event, self.f.employee, [role.role_code])

    def test_partial_receipts_quality_returns_completion_and_target(self):
        receipt = self.f.receive("4.0000")
        received = NotificationEvent.objects.get(event_code="MATERIAL_RECEIPT_RECORDED")
        self.assertEqual(received.status, "CREATED")
        self.assertFalse(MaterialStockMovement.objects.exists())
        self.assertEqual(self.f.complete_order().status_code, 409)
        self.assertEqual(self.f.confirm_quality(receipt, return_quantity="1.0000").status_code, 200)
        inspected = NotificationEvent.objects.get(event_code="MATERIAL_INSPECTION_CONFIRMED")
        self.assertEqual(inspected.target["params"], {"id": str(self.f.order.pk)})
        self.assertEqual(inspected.object_id, received.object_id)
        self.assertIn("合格：3.0000PCS", inspected.rendered_body)
        self.assertIn("退货：1.0000PCS", inspected.rendered_body)
        self.assertIn(self.f.order.order_number, inspected.rendered_body)
        self.assertEqual(self.f.confirm_quality(receipt).status_code, 409)
        self.assertEqual(NotificationEvent.objects.filter(event_code="MATERIAL_INSPECTION_CONFIRMED").count(), 1)
        self.assertEqual(self.f.complete_order("有退货").status_code, 409)
        from apps.procurement.models import PurchaseReturn
        record = PurchaseReturn.objects.get()
        self.assertEqual(self.f.advance_return(record, "confirm").status_code, 200)
        self.assertEqual(self.f.advance_return(record, "complete").status_code, 200)
        completed = self.f.complete_order("本次部分到货，退货已处理，手动完结")
        self.assertEqual(completed.status_code, 200, completed.data)
        event = NotificationEvent.objects.get(event_code="PURCHASE_ORDER_COMPLETED")
        self.assertNotIn("全部", event.rendered_body)
        self.assertNotIn("齐料", event.rendered_body)
        self.assertEqual(event.status, "CREATED")
        self.assertEqual(self.f.complete_order().status_code, 409)
        self.assertEqual(NotificationEvent.objects.count(), 3)

    def test_two_batches_config_change_only_affects_new_events(self):
        self.f.receive("4.0000")
        old = NotificationEvent.objects.get()
        rule = NotificationRule.objects.get(event_code="MATERIAL_RECEIPT_RECORDED")
        new_member, new_role = receiver(self.f.employee, "U06_OTHER_QUALITY", "inventory.quality_confirm_material")
        rule.recipient_role_codes, rule.body_template, rule.version = [new_role.role_code], "新模板 {{document_no}} {{operator}} {{occurred_at}}", 2
        rule.save()
        self.f.receive("2.0000", "6.5000")
        new = NotificationEvent.objects.exclude(pk=old.pk).get()
        self.assertEqual(new.rule_version, 2)
        self.assertEqual(new.recipients.get().employee_id, new_member.pk)
        old.refresh_from_db()
        self.assertEqual(old.rule_version, 1)
        self.assertNotEqual(old.recipients.get().employee_id, new_member.pk)

    def test_failed_receipt_and_outer_rollback_do_not_notify(self):
        response = self.f.client.post("/api/v1/material-inventory/receipts/", self.f.payload(quantity="99"), format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(NotificationEvent.objects.exists())
        with self.assertRaisesRegex(RuntimeError, "rollback"), transaction.atomic():
            self.f.receive()
            self.assertEqual(NotificationEvent.objects.count(), 1)
            raise RuntimeError("rollback")
        self.assertFalse(MaterialInbound.objects.exists())
        self.assertFalse(NotificationDelivery.objects.exists())

    def test_unqualified_recipient_has_no_message(self):
        RoleActionGrant.objects.filter(role__role_code="U06_QUALITY").delete()
        self.f.receive()
        event = NotificationEvent.objects.get()
        self.assertEqual(event.status, "NO_RECIPIENT")
        self.assertFalse(event.recipients.exists())


@override_settings(**SETTINGS)
class SchedulingNotificationTests(APITestCase):
    def setUp(self):
        self.f = schedule_fixture()
        metal = self.f.internal_craft.workshop
        sewing = Workshop.objects.get_or_create(name="车缝车间")[0]
        assembly = Workshop.objects.get_or_create(name="装配车间")[0]
        self.sewing_craft = Craft.objects.create(craft_type="INTERNAL", workshop=sewing, name="U06车缝", plan_category="SEWING")
        self.metal, metal_role = receiver(self.f.employee, "U06_METAL", "production_scheduling.view_productionschedule", workshop=metal)
        self.sewing, sewing_role = receiver(self.f.employee, "U06_SEWING", "production_scheduling.view_productionschedule", workshop=sewing)
        self.assembly, assembly_role = receiver(self.f.employee, "U06_ASSEMBLY", "production_scheduling.view_productionschedule", workshop=assembly)
        EmployeeRoleAssignment.objects.create(employee=self.metal, role_profile=sewing_role, effective_from=timezone.now())
        create_rule("PRODUCTION_PLAN_CREATED", self.f.employee, [metal_role.role_code, sewing_role.role_code, assembly_role.role_code])

    def test_multi_workshop_single_event_dedup_and_idempotent_replay(self):
        payload = self.f.payload()
        payload["items"][0]["craft_ids"].append(str(self.sewing_craft.pk))
        result = self.f.client.post("/api/v1/production-schedules/", payload, format="json")
        self.assertEqual(result.status_code, 201, result.data)
        event = NotificationEvent.objects.get()
        self.assertEqual(event.object_version, "1")
        self.assertCountEqual(list(event.recipients.values_list("employee_id", flat=True)), [self.metal.pk, self.sewing.pk])
        self.assertEqual(NotificationDelivery.objects.count(), 4)
        replay = self.f.client.post("/api/v1/production-schedules/", payload, format="json")
        self.assertEqual(replay.status_code, 201, replay.data)
        self.assertEqual(NotificationEvent.objects.count(), 1)
        RoleGrantResource.objects.filter(grant__role__role_code__in=["U06_METAL", "U06_SEWING"]).delete()
        self.assertFalse(recipient_payload(event.recipients.get(employee=self.metal), self.metal.user)["target_accessible"])

    def test_batch_atomicity_replay_and_stable_versions(self):
        self.f.test_batch_create_generates_one_schedule_per_task_atomically()
        self.assertEqual(NotificationEvent.objects.count(), 3)
        self.assertEqual(set(NotificationEvent.objects.values_list("object_version", flat=True)), {"1"})
        self.assertEqual(NotificationDelivery.objects.count(), 6)  # 三计划，仅金工/兼岗员工各一次。

    def test_ready_all_latest_boms_and_completed_purchase_gates_remain(self):
        self.f.test_create_requires_all_boms_to_be_verified()
        self.assertFalse(NotificationEvent.objects.exists())

    def test_purchase_gate_remains(self):
        self.f.test_create_requires_completed_purchase_order()
        self.assertFalse(NotificationEvent.objects.exists())


@override_settings(**SETTINGS)
class PipeInspectionNotificationTests(APITestCase):
    def test_real_pipe_roots_not_meters_and_all_rejected_no_available_stock(self):
        from apps.procurement.tests.test_pipe_purchase_flow import PipePurchaseFlowTests
        f = PipePurchaseFlowTests()
        f.setUp()
        member, role = receiver(f.employee, "U06_PIPE_PURCHASE", "procurement.view_purchaseorder")
        create_rule("MATERIAL_INSPECTION_CONFIRMED", f.employee, [role.role_code])
        received = f.receive(2)
        self.assertEqual(received.status_code, 201, received.data)
        result = f.quality(received, returned=2)
        self.assertEqual(result.status_code, 200, result.data)
        event = NotificationEvent.objects.get(event_code="MATERIAL_INSPECTION_CONFIRMED")
        self.assertIn("合格：0根；退货：2根", event.rendered_body)
        self.assertFalse(MaterialStockMovement.objects.exists())


@override_settings(**SETTINGS)
class PurchaseCoverageAndPublicationTests(APITestCase):
    def test_multiple_products_remain_blocked_after_single_bom_order(self):
        from apps.procurement.tests.test_purchase_order_api import PurchaseOrderApiTests
        from apps.procurement.models import PurchaseOrder
        from apps.procurement.services import evaluate_purchase_source
        f = PurchaseOrderApiTests()
        f.setUp()
        f.test_multiple_products_require_bom_selection_and_selected_valid_bom_is_editable()
        order = PurchaseOrder.objects.get()
        self.assertEqual(order.production_task.products.count(), 2)
        self.assertEqual(order.lines.values("product_line_id_snapshot").distinct().count(), 1)
        source = evaluate_purchase_source(order.production_task)
        self.assertIn("PURCHASE_ORDER_EXISTS", [item["code"] for item in source["blockers"]])
        self.assertFalse(source["can_create"])

    def test_single_and_batch_supplier_publication_do_not_notify(self):
        from apps.procurement.tests.test_purchase_order_api import PurchaseOrderApiTests
        f = PurchaseOrderApiTests()
        f.setUp()
        with TemporaryDirectory(prefix="supplier-", dir="/app/.tmp/unit06_15cb0") as media, f.settings(MEDIA_ROOT=media):
            f.test_batch_publish_is_atomic_and_rejects_duplicate_selection()
        self.assertFalse(NotificationEvent.objects.exists())


@override_settings(**SETTINGS)
class ConfirmationNotificationConcurrencyTests(TransactionTestCase):
    def test_two_concurrent_confirmation_calls_create_one_event(self):
        f = schedule_fixture()
        grant_role(f.employee, "ADMINISTRATION", "production_tasks.confirm_productiontask")
        member, role = receiver(f.employee, "U06_CONCURRENT_TECH", "production_tasks.view_productiontask")
        create_rule("PRODUCTION_TASK_CONFIRMED", f.employee, [role.role_code])
        f.task.status = "PENDING_VALIDATION"
        f.task.save()
        barrier = Barrier(2)

        def confirm():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                transition_production_task(task=f.task, target_status="READY", actor_employee=f.employee, request=None)
                return "confirmed"
            except Conflict:
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: confirm(), range(2)))
        self.assertCountEqual(results, ["confirmed", "conflict"])
        self.assertEqual(NotificationEvent.objects.count(), 1)
        self.assertEqual(NotificationDelivery.objects.count(), 2)
