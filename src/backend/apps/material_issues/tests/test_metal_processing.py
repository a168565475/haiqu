import copy
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.middleware.csrf import _get_new_csrf_string
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from apps.inventory.models import MaterialStockBalance, MaterialStockMovement, SemiFinishedStockBalance, SemiFinishedStockMovement
from apps.organizations.models import Employee
from apps.outsourcing.tests.test_material_flow import MaterialFlowFixture
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory, ProductionUnit
from apps.workshop_config.models import Craft, Workshop, WorkshopEmployee
from apps.workshop_reporting.models import WorkReport, WorkReportLine
from ..models import MaterialIssue, MaterialIssueLine, MetalProcessingClosure, MetalProcessingCompletion, MetalProcessingSource, OrderMaterialRequirement


BASE = "/api/v1/metal-processing-sources/"


class ProcessingFixture(MaterialFlowFixture):
    def setUp(self):
        super().setUp()
        f = self.f
        # 原委外夹具的铆钉没有库存身份；金工领料必须先补齐同车间 BOM 映射。
        hardware_category, _ = ProductCategory.objects.get_or_create(category_name="五金", defaults={"item_type": "MATERIAL"})
        hardware_unit, _ = ProductionUnit.objects.get_or_create(unit_name="个", defaults={"unit_code": "METAL-EACH"})
        hardware = RawMaterialInformation.objects.create(material_number="METAL-TEST-RIVET", item_type="MATERIAL",
            category=hardware_category, material_name="铆钉", specification="M6", unit=hardware_unit)
        f.hardware.raw_values = {"source_inventory_material_id": str(hardware.pk)}
        f.hardware.save()
        self.workshop, _ = Workshop.objects.get_or_create(name="金工车间", defaults={"status": "ACTIVE"})
        self.recipient = WorkshopEmployee.objects.create(workshop=self.workshop, name="金工领料测试", position="领料员",
                                                         is_supervisor=False, status="ACTIVE")
        craft = Craft.objects.create(craft_type="INTERNAL", name="金工完成测试", workshop=self.workshop,
                                      plan_category="METAL", status="ACTIVE", created_by_employee=f.employee,
                                      updated_by_employee=f.employee)
        ProductionScheduleProductCraft.objects.create(schedule_product=f.schedule_product, craft=craft,
            craft_type_snapshot="INTERNAL", craft_name_snapshot=craft.name, plan_category="METAL")
        self.task = f.bom.production_task
        self.line = self.issue_line()

    def issue_action(self, issue_id, action, data=None):
        url = f"/api/v1/material-issues/{issue_id}/"
        detail = self.client.get(url)
        response = self.client.post(url + action + "/", data or {}, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def issue_line(self, quantity=210, confirm=True):
        f = self.f
        response = self.client.get("/api/v1/material-issues/requirements/", {
            "production_task_id": str(self.task.pk), "product_line_id": str(f.product_line.pk),
            "workshop_id": str(self.workshop.pk)})
        self.assertEqual(response.status_code, 200, response.data)
        pipe = next(row for row in response.data["data"]["items"] if row.get("conversion_snapshot", {}).get("kind") == "PIPE")
        payload = {"client_request_id": str(uuid.uuid4()), "schedule_product_id": str(f.schedule_product.pk),
                   "plan_category": "METAL", "production_task_id": str(self.task.pk), "product_line_id": str(f.product_line.pk),
                   "workshop_id": str(self.workshop.pk), "recipient_workshop_employee_id": str(self.recipient.pk),
                   "issue_at": timezone.now().isoformat(), "lines": [{"requirement_id": pipe["requirement_id"],
                   "requested_quantity": str(quantity), "batch_allocations": [
                       {"inbound_line_id": str(self.pipe_batch.pk), "requested_pieces": str(quantity)}]}]}
        response = self.client.post("/api/v1/material-issues/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        issue_id = response.data["data"]["id"]
        if confirm:
            self.issue_action(issue_id, "submit")
            self.issue_action(issue_id, "confirm-issue", {"request_id": str(uuid.uuid4())})
        return MaterialIssueLine.objects.get(issue_id=issue_id)

    def detail(self, line=None):
        response = self.client.get(BASE + str((line or self.line).pk) + "/")
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def complete_payload(self, quantity=200, **changes):
        return {"request_id": str(uuid.uuid4()), "good_pieces": quantity,
                "completion_date": str(timezone.localdate()), **changes}

    def write(self, action, data, expected=200, line=None, etag=None):
        line = line or self.line
        current = self.detail(line)
        response = self.client.post(BASE + str(line.pk) + "/" + action + "/", data, format="json",
                                    HTTP_IF_MATCH=etag if etag is not None else current.get("ETag", '"invalid"'))
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def unchanged_ledgers(self):
        models = (MaterialStockBalance, MaterialStockMovement, SemiFinishedStockBalance, SemiFinishedStockMovement,
                  OrderMaterialRequirement, MaterialIssue, MaterialIssueLine, WorkReport, WorkReportLine)
        return {model._meta.label: list(model.objects.order_by("pk").values()) for model in models}


class MetalProcessingApiTests(ProcessingFixture, APITestCase):
    def test_read_only_candidates_details_and_filters(self):
        before = self.unchanged_ledgers()
        for suffix in ("", f"{self.line.pk}/", f"{self.line.pk}/closure-preview/"):
            response = self.client.get(BASE + suffix)
            self.assertEqual(response.status_code, 200, response.data)
        data = self.detail().data["data"]
        self.assertEqual((data["issued_pieces"], data["completed_pieces"], data["bar_count"], data["meters"]), (210, 0, 35, "106.75"))
        self.assertFalse(MetalProcessingSource.objects.exists())
        self.assertEqual(before, self.unchanged_ledgers())
        for key in ("production_task_id", "product_line_id", "component_identity", "issue_id"):
            self.assertEqual(self.client.get(BASE, {key: "bad"}).status_code, 400)
            self.assertEqual(self.client.get(BASE, {key: str(uuid.uuid4())}).data["meta"]["total"], 0)
        self.assertEqual(self.client.get(BASE, {"status": "bad"}).status_code, 400)
        self.assertEqual(self.client.get(BASE, {"issue_number": self.line.issue.issue_number}).data["meta"]["total"], 1)

    def test_completion_limits_and_no_second_stock_or_wage_write(self):
        before = self.unchanged_ledgers()
        self.write("completions", self.complete_payload(200))
        self.write("completions", self.complete_payload(10))
        self.write("completions", self.complete_payload(1), 400)
        source = MetalProcessingSource.objects.get()
        self.assertEqual(source.completed_pieces, 210)
        self.assertEqual(source.completions.count(), 2)
        self.assertEqual(before, self.unchanged_ledgers())

    def test_invalid_quantities_dates_and_server_controlled_fields(self):
        for amount in (0, -1, 1.1, "1.0", True, None, "NaN", "Infinity", "bad", 10**14, 211):
            self.write("completions", self.complete_payload(amount), 400)
        self.write("completions", self.complete_payload(completion_date="2026-02-30"), 400)
        self.write("completions", self.complete_payload(reserved_pieces=1), 400)
        self.write("completions", self.complete_payload(request_id="bad"), 400)
        self.assertFalse(MetalProcessingSource.objects.exists())

    def test_closure_preserves_differences_and_freezes_source(self):
        before = self.unchanged_ledgers()
        self.write("completions", self.complete_payload())
        response = self.write("close", {"request_id": str(uuid.uuid4()), "remark": "  实际差额核对结清  "})
        data = response.data["data"]
        self.assertEqual((data["issued_pieces"], data["completed_pieces"], data["available_pieces"]), (210, 200, 0))
        closure = MetalProcessingClosure.objects.get()
        self.assertEqual(closure.remark, "实际差额核对结清")
        self.assertEqual((closure.quantity_snapshot["unfinished_pieces"], closure.quantity_snapshot["unallocated_pieces"]), (10, 200))
        self.assertEqual(data["closure"]["actor_employee_id"], str(self.f.employee.pk))
        self.write("completions", self.complete_payload(1), 409)
        self.write("close", {"request_id": str(uuid.uuid4()), "remark": "再次结清"}, 409)
        for method in (self.client.delete, self.client.patch):
            self.assertIn(method(BASE + str(self.line.pk) + "/", {}, format="json").status_code, (403, 405))
        self.assertEqual(self.client.get(BASE, {"status": "CLOSED"}).data["meta"]["total"], 1)
        self.assertEqual(self.client.get(BASE, {"status": "OPEN"}).data["meta"]["total"], 0)
        self.assertEqual(before, self.unchanged_ledgers())

    def test_closure_before_any_completion_and_remark_validation(self):
        for remark in ("", " \n\t", "字" * 1001, None):
            self.write("close", {"request_id": str(uuid.uuid4()), "remark": remark}, 400)
        self.assertFalse(MetalProcessingSource.objects.exists())
        response = self.write("close", {"request_id": str(uuid.uuid4()), "remark": "字" * 1000})
        self.assertEqual(response.data["data"]["closure"]["quantities"]["unfinished_pieces"], 210)

    def test_reserved_block_and_dispatched_difference_fixture(self):
        self.write("completions", self.complete_payload())
        source = MetalProcessingSource.objects.get()
        # P4 尚未接入，以下仅为结清边界夹具，不代表已实现真实交接。
        source.reserved_pieces = 20
        source.dispatched_pieces = 180
        source.save()
        preview = self.client.get(BASE + str(self.line.pk) + "/closure-preview/").data["data"]
        self.assertFalse(preview["can_close"])
        self.write("close", {"request_id": str(uuid.uuid4()), "remark": "还有占用"}, 409)
        source.reserved_pieces = 0
        source.save()
        self.write("close", {"request_id": str(uuid.uuid4()), "remark": "已核对差额"})
        quantities = MetalProcessingClosure.objects.get().quantity_snapshot
        self.assertEqual((quantities["unfinished_pieces"], quantities["unallocated_pieces"]), (10, 20))
        source.refresh_from_db()
        self.assertEqual((source.completed_pieces, source.dispatched_pieces), (200, 180))

    def test_idempotency_stale_missing_version_and_payload_conflicts(self):
        etag = self.detail()["ETag"]
        payload = self.complete_payload()
        url = BASE + str(self.line.pk) + "/completions/"
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 428)
        first = self.write("completions", payload, etag=etag)
        second = self.write("completions", payload, etag=etag)
        self.assertEqual(first.data, second.data)
        self.write("completions", {**payload, "good_pieces": 1}, 409)
        self.write("completions", self.complete_payload(1), 412, etag=etag)
        closure_payload = {"request_id": str(uuid.uuid4()), "remark": "人工核对"}
        closure_etag = self.detail()["ETag"]
        first_close = self.write("close", closure_payload)
        self.assertEqual(first_close.data, self.write("close", closure_payload, etag=closure_etag).data)
        self.assertEqual(first.data, self.write("completions", payload, etag=etag).data)
        self.write("close", {"request_id": payload["request_id"], "remark": "复用完成请求"}, 409)
        self.assertEqual(MetalProcessingCompletion.objects.count(), 1)
        self.assertEqual(MetalProcessingClosure.objects.count(), 1)

    def test_other_source_cannot_reuse_request(self):
        other = self.issue_line(12)
        payload = self.complete_payload(10)
        self.write("completions", payload)
        self.write("completions", payload, 409, line=other)
        self.assertEqual(MetalProcessingSource.objects.count(), 1)

    def test_old_bom_change_does_not_recalculate_frozen_source(self):
        before = self.detail().data["data"]
        self.f.profile.cutting_length_mm = 999
        self.f.profile.save()
        self.f.bom.status = "PENDING_CONFIRMATION"
        self.f.bom.save()
        after = self.write("completions", self.complete_payload(7)).data["data"]
        self.assertEqual(after["source_snapshot"], before["source_snapshot"])
        self.assertEqual(after["completed_pieces"], 7)

    def test_missing_or_inconsistent_snapshot_blocks_without_guessing(self):
        original = copy.deepcopy(self.line.conversion_snapshot)
        for key, value in (("source_revision_hash", ""), ("raw_material_id", str(uuid.uuid4())),
                           ("component_identity", str(uuid.uuid4())), ("pieces_per_bar", "NaN")):
            self.line.conversion_snapshot = {**original, key: value}
            self.line.save()
            self.assertFalse(self.detail().data["data"]["can_register"])
            self.write("completions", self.complete_payload(1), 400)
        self.assertFalse(MetalProcessingSource.objects.exists())

    def test_frozen_source_change_after_registration_is_conflict(self):
        self.write("completions", self.complete_payload(1))
        self.line.conversion_snapshot["part_name"] = "被改动的冻结来源"
        self.line.save()
        self.assertFalse(self.detail().data["data"]["can_register"])
        self.write("completions", self.complete_payload(1), 409)

    def test_invalid_frozen_batch_identity_length_and_units(self):
        batch = self.line.batch_allocations.get()
        original = copy.deepcopy(batch.snapshot)
        candidates = [{"legacy": True}, {**original, "inbound_line_id": str(uuid.uuid4())},
                      {key: value for key, value in original.items() if key != "raw_bar_length_m"},
                      {**original, "source_unit": "米"}, {**original, "material_unit": "支"},
                      {**original, "inbound_number": ""}, {**original, "raw_bar_length_m": "9.99"}]
        for snapshot in candidates:
            batch.snapshot = snapshot
            batch.save()
            self.assertFalse(self.detail().data["data"]["can_register"])
            self.write("completions", self.complete_payload(1), 400)
        self.assertFalse(MetalProcessingSource.objects.exists())

    def test_not_issued_or_wrong_workshop_excluded(self):
        pending = self.issue_line(12, confirm=False)
        self.assertEqual(self.client.get(BASE + str(pending.pk) + "/").status_code, 404)
        assembly, _ = Workshop.objects.get_or_create(name="装配车间")
        MaterialIssue.objects.filter(pk=self.line.issue_id).update(workshop=assembly)
        self.assertEqual(self.client.get(BASE + str(self.line.pk) + "/").status_code, 404)
        self.assertEqual(self.client.get(BASE).data["meta"]["total"], 0)

    def test_exception_rolls_back_first_registration_and_closure(self):
        with patch.object(MetalProcessingCompletion.objects, "create", side_effect=RuntimeError("验证事务回滚")):
            with self.assertRaisesMessage(RuntimeError, "验证事务回滚"):
                self.write("completions", self.complete_payload())
        self.assertFalse(MetalProcessingSource.objects.exists())
        self.write("completions", self.complete_payload())
        before = list(MetalProcessingSource.objects.values())
        with patch.object(MetalProcessingClosure.objects, "create", side_effect=RuntimeError("验证结清回滚")):
            with self.assertRaisesMessage(RuntimeError, "验证结清回滚"):
                self.write("close", {"request_id": str(uuid.uuid4()), "remark": "核对"})
        self.assertEqual(before, list(MetalProcessingSource.objects.values()))
        self.assertFalse(MetalProcessingClosure.objects.exists())

    def test_database_limits(self):
        self.write("completions", self.complete_payload())
        for fields in ({"completed_pieces": 211}, {"reserved_pieces": 201}, {"dispatched_pieces": 201},
                       {"issued_pieces": 0}, {"status": "OTHER"}, {"completed_pieces": -1}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                MetalProcessingSource.objects.update(**fields)

    def test_session_csrf_and_inactive_employee(self):
        client = APIClient(enforce_csrf_checks=True)
        url = BASE + str(self.line.pk) + "/completions/"
        self.assertEqual(client.get(BASE).status_code, 401)
        client.force_login(self.f.user)
        etag = client.get(BASE + str(self.line.pk) + "/")["ETag"]
        payload = self.complete_payload(1)
        self.assertEqual(client.post(url, payload, format="json", HTTP_IF_MATCH=etag).status_code, 403)
        csrf = _get_new_csrf_string()
        client.cookies["csrftoken"] = csrf
        response = client.post(url, payload, format="json", HTTP_IF_MATCH=etag, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200, response.data)
        Employee.objects.filter(pk=self.f.employee.pk).update(status="INACTIVE")
        self.assertEqual(client.get(BASE).status_code, 403)

    def test_action_permission_scope_and_replay_permission(self):
        user = get_user_model().objects.create_user(username="metal-limited-user")
        Employee.objects.create(user=user, employee_code="METAL-LIMITED", display_name="范围校验员")
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label="material_issues",
            codename__in=["view_metalprocessingsource", "register_metalprocessingcompletion", "close_metalprocessingsource"]))
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(BASE).data["meta"]["total"], 0)
        for suffix in ("", "closure-preview/"):
            self.assertEqual(self.client.get(BASE + str(self.line.pk) + "/" + suffix).status_code, 404)
        self.assertEqual(self.client.post(BASE + str(self.line.pk) + "/completions/", self.complete_payload(1), format="json").status_code, 404)
        user.user_permissions.add(Permission.objects.get(content_type__app_label="material_issues", codename="view_all_materialissue"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        payload = self.complete_payload(1)
        self.write("completions", payload)
        user.user_permissions.remove(Permission.objects.get(codename="register_metalprocessingcompletion"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        self.write("completions", payload, 403)
        user.user_permissions.remove(Permission.objects.get(codename="close_metalprocessingsource"))
        self.client.force_authenticate(get_user_model().objects.get(pk=user.pk))
        self.write("close", {"request_id": str(uuid.uuid4()), "remark": "越权"}, 403)


class MetalProcessingConcurrencyTests(ProcessingFixture, APITransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        with transaction.atomic():
            super().setUp()

    def race(self, requests):
        barrier = Barrier(len(requests))
        etag = self.detail()["ETag"]
        user_id = self.f.user.pk
        line_id = self.line.pk

        def worker(item):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=user_id))
                barrier.wait(timeout=15)
                action, payload = item
                response = client.post(BASE + str(line_id) + "/" + action + "/", payload,
                                       format="json", HTTP_IF_MATCH=etag)
                return response.status_code, response.data
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(worker, requests))

    def test_first_source_race_and_over_limit(self):
        results = self.race([("completions", self.complete_payload(200)), ("completions", self.complete_payload(200))])
        self.assertEqual(sorted(code for code, _ in results), [200, 412], results)
        self.assertEqual(MetalProcessingSource.objects.count(), 1)
        self.assertEqual(MetalProcessingSource.objects.get().completed_pieces, 200)
        self.assertEqual(MetalProcessingCompletion.objects.count(), 1)

    def test_same_request_race_is_idempotent(self):
        payload = self.complete_payload(200)
        results = self.race([("completions", payload), ("completions", payload)])
        self.assertEqual([code for code, _ in results], [200, 200], results)
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(MetalProcessingCompletion.objects.count(), 1)

    def test_registration_closure_race(self):
        self.write("completions", self.complete_payload(200))
        results = self.race([("completions", self.complete_payload(10)),
                             ("close", {"request_id": str(uuid.uuid4()), "remark": "并发核对"})])
        self.assertEqual(sorted(code for code, _ in results), [200, 412], results)
        source = MetalProcessingSource.objects.get()
        self.assertEqual((source.completed_pieces, source.status), (210, "OPEN") if results[0][0] == 200 else (200, "CLOSED"))
