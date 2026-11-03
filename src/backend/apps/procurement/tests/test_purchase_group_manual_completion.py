from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.middleware.csrf import _get_new_csrf_string
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.models import RoleActionGrant
from apps.audit.models import AuditLog
from apps.inventory.models import MaterialInbound, PublicStockCutoverControl
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.procurement.models import PurchaseGroup, PurchaseOrder, PurchaseReturn, PurchaseReturnLine
from apps.procurement.tests import test_purchase_groups as group_tests


class PurchaseGroupManualCompletionTests(APITestCase):
    make_task = group_tests.PurchaseGroupApiTests.make_task
    make_product_line = group_tests.PurchaseGroupApiTests.make_product_line
    make_bom = group_tests.PurchaseGroupApiTests.make_bom
    get_source = group_tests.PurchaseGroupApiTests.get_source
    setUp = group_tests.PurchaseGroupApiTests.setUp
    detail = group_tests.PurchaseGroupApiTests.detail
    batch_payload = group_tests.PurchaseGroupApiTests.batch_payload
    batch = group_tests.PurchaseGroupApiTests.batch
    receive = group_tests.PurchaseGroupApiTests.receive

    @property
    def complete_url(self):
        return f"/api/v1/purchase-groups/{self.group_id}/complete/"

    def complete(self, remark="", *, etag=None):
        return self.client.post(self.complete_url, {"remark": remark}, format="json",
                                HTTP_IF_MATCH=etag or self.detail()["ETag"])

    def audit_count(self):
        return AuditLog.objects.filter(object_type="PURCHASE_GROUP", object_id=self.group_id,
                                       action="MANUALLY_COMPLETED").count()

    def ready(self):
        batch = self.batch()
        self.receive(batch, "40")
        return batch

    def advance_return(self, record, action):
        url = f"/api/v1/purchase-returns/{record.pk}/"
        detail = self.client.get(url)
        response = self.client.post(f"{url}{action}/", {}, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(response.status_code, 200, response.data)

    def test_partial_group_with_unreceived_batch_completes_without_changing_progress_or_batches(self):
        self.ready()
        self.batch("20", "SUPPLEMENT")
        before = self.detail()
        states = list(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).values_list("id", "status"))
        response = self.complete("  数量不足，采购确认结束  ", etag=before["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(data["display_status"], "COMPLETED")
        self.assertEqual(data["progress"], before.data["data"]["progress"])
        self.assertEqual(data["progress"]["status"], "PURCHASING")
        self.assertEqual(data["manual_completed_by_name"], self.employee.display_name)
        self.assertEqual(data["manual_completion_remark"], "数量不足，采购确认结束")
        self.assertTrue(data["manual_completed_at"])
        self.assertNotEqual(response["ETag"], before["ETag"])
        self.assertFalse(data["completion"]["can_complete"])
        self.assertEqual(list(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).values_list("id", "status")), states)
        self.assertEqual(self.audit_count(), 1)
        record = PurchaseGroup.objects.get(pk=self.group_id)
        stamp = (record.manual_completed_at, record.manual_completed_by_employee_id, record.manual_completion_remark)
        self.batch("10", "SUPPLEMENT")
        record.refresh_from_db()
        self.assertEqual((record.manual_completed_at, record.manual_completed_by_employee_id, record.manual_completion_remark), stamp)
        self.assertEqual(self.detail().data["data"]["display_status"], "COMPLETED")

    def test_fully_received_group_can_record_manual_completion_once_without_changing_progress_or_batches(self):
        batch = self.batch("120")
        self.receive(batch, "120")
        before = self.detail()
        self.assertEqual(before.data["data"]["progress"]["status"], "COMPLETED")
        self.assertTrue(before.data["data"]["completion"]["can_complete"])
        states = list(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).values_list("id", "status"))
        response = self.complete("  全部到齐，采购确认完成  ", etag=before["ETag"])
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(data["display_status"], "COMPLETED")
        self.assertEqual(data["progress"], before.data["data"]["progress"])
        self.assertEqual(data["manual_completed_by_name"], self.employee.display_name)
        self.assertEqual(data["manual_completion_remark"], "全部到齐，采购确认完成")
        self.assertTrue(data["manual_completed_at"])
        self.assertNotEqual(response["ETag"], before["ETag"])
        self.assertFalse(data["completion"]["can_complete"])
        self.assertEqual(list(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).values_list("id", "status")), states)
        record = PurchaseGroup.objects.get(pk=self.group_id)
        stamp = (record.manual_completed_at, record.manual_completed_by_employee_id, record.manual_completion_remark)
        self.assertEqual(record.manual_completed_by_employee_id, self.employee.pk)
        self.assertEqual(self.complete("重复完成", etag=response["ETag"]).status_code, 409)
        record.refresh_from_db()
        self.assertEqual((record.manual_completed_at, record.manual_completed_by_employee_id, record.manual_completion_remark), stamp)
        self.assertEqual(self.audit_count(), 1)

    def test_fully_received_group_still_blocks_pending_quality_in_another_batch(self):
        first = self.batch("120")
        self.receive(first, "120")
        second = self.batch("20", "SUPPLEMENT")
        self.receive(second, "10", confirm=False)
        data = self.detail().data["data"]
        self.assertEqual(data["progress"]["status"], "COMPLETED")
        self.assertFalse(data["completion"]["can_complete"])
        response = self.complete()
        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("待品质确认", response.data["error"]["message"])
        self.assertIsNone(PurchaseGroup.objects.get(pk=self.group_id).manual_completed_at)
        self.assertEqual(self.audit_count(), 0)

    def test_fully_received_group_still_requires_returns_to_finish(self):
        first = self.batch("120")
        self.receive(first, "120")
        second = self.batch("20", "SUPPLEMENT")
        self.receive(second, "10", returned="5")
        record = PurchaseReturn.objects.get(purchase_order_id=second["id"])
        self.assertEqual(self.detail().data["data"]["progress"]["status"], "COMPLETED")
        self.assertFalse(self.detail().data["data"]["completion"]["can_complete"])
        self.assertEqual(self.complete().status_code, 409)
        self.advance_return(record, "confirm")
        self.assertEqual(self.complete().status_code, 409)
        self.assertEqual(self.audit_count(), 0)
        self.assertIsNone(PurchaseGroup.objects.get(pk=self.group_id).manual_completed_at)
        self.advance_return(record, "complete")
        self.assertTrue(self.detail().data["data"]["completion"]["can_complete"])
        response = self.complete("全部到齐且退货已结清")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.audit_count(), 1)

    def test_no_receipt_pending_quality_and_unknown_sources_block(self):
        self.assertEqual(self.complete().status_code, 409)
        batch = self.batch()
        receipt = self.receive(batch, "40", confirm=False)
        self.assertEqual(self.complete().status_code, 409)
        payload = {"items": [{"line_id": row["id"], "expected_received_quantity": row["received_quantity"],
                              "return_quantity": "0", "quality_remark": "通过"} for row in receipt.data["data"]["lines"]]}
        checked = self.client.post(f"/api/v1/material-inventory/quality-batches/{receipt.data['data']['id']}/confirm/",
                                   payload, format="json")
        self.assertEqual(checked.status_code, 200, checked.data)
        PurchaseGroup.objects.filter(pk=self.group_id).update(compatibility_issues=["SOURCE_UNKNOWN"])
        self.assertEqual(self.detail().data["data"]["progress"]["status"], "UNKNOWN")
        self.assertEqual(self.complete().status_code, 409)
        self.assertEqual(self.audit_count(), 0)

    def test_pending_quality_in_other_batch_blocks_previously_ready_group(self):
        self.ready()
        second = self.batch("20", "SUPPLEMENT")
        etag = self.detail()["ETag"]
        self.receive(second, "10", confirm=False)
        self.assertEqual(self.detail()["ETag"], etag)
        response = self.complete(etag=etag)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(self.audit_count(), 0)

    def test_returns_must_finish_but_remark_is_optional(self):
        batch = self.batch()
        self.receive(batch, "40", returned="10")
        record = PurchaseReturn.objects.get(purchase_order_id=batch["id"])
        self.assertEqual(self.complete().status_code, 409)
        self.advance_return(record, "confirm")
        self.assertEqual(self.complete().status_code, 409)
        self.advance_return(record, "complete")
        response = self.complete()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["manual_completion_remark"], "")
        self.assertEqual(response.data["data"]["progress"]["lines"][0]["accepted_quantity"], "30.0000")

    def test_missing_or_mismatched_return_records_block(self):
        batch = self.batch()
        self.receive(batch, "40", returned="10")
        record = PurchaseReturn.objects.get(purchase_order_id=batch["id"])
        self.advance_return(record, "confirm")
        self.advance_return(record, "complete")
        line = record.lines.get()
        PurchaseReturnLine.objects.filter(pk=line.pk).update(quantity="9")
        self.assertEqual(self.complete().status_code, 409)
        PurchaseReturnLine.objects.filter(pk=line.pk).delete()
        self.assertEqual(self.complete().status_code, 409)
        self.assertEqual(self.audit_count(), 0)

    def test_inbound_header_must_belong_to_its_batch(self):
        first = self.ready()
        second = self.batch("20", "SUPPLEMENT")
        MaterialInbound.objects.filter(purchase_order_id=first["id"]).update(purchase_order_id=second["id"])
        self.assertEqual(self.complete().status_code, 409)
        self.assertEqual(self.audit_count(), 0)

    def test_missing_stale_and_duplicate_etags_never_replace_first_completion(self):
        self.ready()
        current = self.detail()
        self.assertEqual(self.client.post(self.complete_url, {}, format="json").status_code, 428)
        self.assertEqual(self.complete(etag='"stale"').status_code, 412)
        self.assertEqual(self.complete("x" * 2001).status_code, 400)
        self.assertEqual(self.audit_count(), 0)
        finished = self.complete("首次完成", etag=current["ETag"])
        self.assertEqual(finished.status_code, 200, finished.data)
        stamp = finished.data["data"]["manual_completed_at"]
        self.assertEqual(self.complete("第二次", etag=current["ETag"]).status_code, 412)
        self.assertEqual(self.complete("第二次", etag=finished["ETag"]).status_code, 409)
        data = self.detail().data["data"]
        self.assertEqual((data["manual_completed_at"], data["manual_completion_remark"]), (stamp, "首次完成"))
        self.assertEqual(self.audit_count(), 1)

    def test_audit_failure_rolls_back_completion_and_etag(self):
        self.ready()
        before = self.detail()
        with patch("apps.procurement.group_services.write_audit_log", side_effect=RuntimeError("audit failed")):
            with self.assertRaisesRegex(RuntimeError, "audit failed"):
                self.complete(etag=before["ETag"])
        after = self.detail()
        self.assertIsNone(after.data["data"]["manual_completed_at"])
        self.assertEqual(after["ETag"], before["ETag"])
        self.assertEqual(self.audit_count(), 0)

    def test_scope_and_view_only_permissions_cannot_complete(self):
        self.ready()
        outsider = get_user_model().objects.create_user(username="manual-group-outsider")
        Employee.objects.create(user=outsider, employee_code="MGC-OUT", display_name="范围外采购")
        outsider.user_permissions.set(Permission.objects.filter(content_type__app_label="procurement"))
        client = APIClient()
        client.force_authenticate(outsider)
        self.assertEqual(client.post(self.complete_url, {}, format="json").status_code, 404)
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label="procurement", codename="view_purchaseorder"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.complete().status_code, 403)
        self.assertEqual(self.audit_count(), 0)

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True)
    def test_module_permission_requires_complete_action(self):
        self.ready()
        self.user.user_permissions.clear()
        role = RoleProfile.objects.create(role_code="GROUP-COMPLETE", display_name="总单完成测试",
                                           auth_group=Group.objects.create(name="group-complete-test"))
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=role, effective_from=timezone.now())
        for code in ("view_purchaseorder", "submit_purchaseorder"):
            RoleActionGrant.objects.create(role=role, permission=Permission.objects.get(
                content_type__app_label="procurement", codename=code), scope="MODULE")
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.complete().status_code, 403)
        RoleActionGrant.objects.create(role=role, permission=Permission.objects.get(
            content_type__app_label="access_control", codename="complete_purchaseorder"), scope="MODULE")
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        response = self.complete()
        self.assertEqual(response.status_code, 200, response.data)

    def test_real_session_requires_csrf_and_accepts_valid_csrf(self):
        self.ready()
        etag = self.detail()["ETag"]
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.complete_url, {}, format="json", HTTP_IF_MATCH=etag).status_code, 403)
        token = _get_new_csrf_string()
        client.cookies["csrftoken"] = token
        response = client.post(self.complete_url, {}, format="json", HTTP_IF_MATCH=etag, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.audit_count(), 1)

    def test_archived_group_and_cutover_gate_block_without_completion(self):
        self.ready()
        etag = self.detail()["ETag"]
        PublicStockCutoverControl.objects.create(state="MAINTENANCE", reason="隔离测试停写")
        blocked = self.client.post(self.complete_url, {}, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(blocked.status_code, 503, blocked.content)
        self.assertEqual(self.audit_count(), 0)
        PublicStockCutoverControl.objects.all().delete()
        PurchaseGroup.objects.filter(pk=self.group_id).update(archived_at=timezone.now())
        self.assertEqual(self.client.post(self.complete_url, {}, format="json", HTTP_IF_MATCH=etag).status_code, 404)
