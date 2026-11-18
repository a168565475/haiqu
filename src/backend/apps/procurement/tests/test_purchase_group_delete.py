from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections
from django.middleware.csrf import _get_new_csrf_string
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditLog
from apps.boms.models import BomSectionType
from apps.inventory.models import MaterialInbound
from apps.organizations.models import Employee
from apps.products.models import RawMaterialInformation
from apps.procurement.models import PurchaseGroup, PurchaseGroupLine, PurchaseOrder, PurchaseOrderLine, PurchaseReturn
from apps.procurement.tests import test_purchase_groups as group_tests
from apps.procurement.tests.group_test_fixtures import ensure_group_test_reference_data


class PurchaseGroupDeleteFixture:
    make_task = group_tests.PurchaseGroupApiTests.make_task
    make_product_line = group_tests.PurchaseGroupApiTests.make_product_line
    make_bom = group_tests.PurchaseGroupApiTests.make_bom
    get_source = group_tests.PurchaseGroupApiTests.get_source
    detail = group_tests.PurchaseGroupApiTests.detail
    batch_payload = group_tests.PurchaseGroupApiTests.batch_payload
    batch = group_tests.PurchaseGroupApiTests.batch

    def setUp(self):
        ensure_group_test_reference_data()
        group_tests.PurchaseGroupApiTests.setUp(self)

    @property
    def delete_url(self):
        return f"/api/v1/purchase-groups/{self.group_id}/"

    def delete_group(self, *, etag=None, client=None):
        return (client or self.client).delete(
            self.delete_url, HTTP_IF_MATCH=etag or self.detail()["ETag"],
        )

    def assert_blocked(self):
        detail = self.detail()
        self.assertFalse(detail.data["data"]["deletion"]["can_delete"])
        self.assertTrue(detail.data["data"]["deletion"]["blocked_reason"])
        before_orders = set(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).values_list("pk", flat=True))
        before_lines = set(PurchaseOrderLine.objects.filter(purchase_order_id__in=before_orders).values_list("pk", flat=True))
        response = self.delete_group(etag=detail["ETag"])
        self.assertEqual(response.status_code, 409, response.data)
        self.assertTrue(PurchaseGroup.objects.filter(pk=self.group_id).exists())
        self.assertTrue(PurchaseGroupLine.objects.filter(pk=self.line_id).exists())
        self.assertEqual(set(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).values_list("pk", flat=True)), before_orders)
        self.assertEqual(set(PurchaseOrderLine.objects.filter(purchase_order_id__in=before_orders).values_list("pk", flat=True)), before_lines)
        self.assertFalse(AuditLog.objects.filter(object_type="PURCHASE_GROUP", object_id=self.group_id, action="DELETED").exists())


class PurchaseGroupDeleteApiTests(PurchaseGroupDeleteFixture, APITestCase):
    def test_empty_group_is_physically_deleted_and_repeat_returns_not_found(self):
        detail = self.detail()
        self.assertEqual(detail.data["data"]["deletion"], {"can_delete": True, "blocked_reason": ""})
        response = self.delete_group(etag=detail["ETag"])
        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(PurchaseGroup.objects.filter(pk=self.group_id).exists())
        self.assertFalse(PurchaseGroupLine.objects.filter(pk=self.line_id).exists())
        self.assertEqual(self.client.get(self.delete_url).status_code, 404)
        self.assertEqual(self.delete_group(etag=detail["ETag"]).status_code, 404)
        self.assertEqual(AuditLog.objects.filter(object_type="PURCHASE_GROUP", object_id=self.group_id, action="DELETED").count(), 1)
        self.assertTrue(self.task.__class__.objects.filter(pk=self.task.pk).exists())
        self.assertTrue(self.bom.__class__.objects.filter(pk=self.bom.pk).exists())

    def test_all_drafts_including_archived_are_deleted_and_latest_bom_can_rebuild(self):
        first = self.batch("12", confirm=False)
        second = self.batch("13", "SUPPLEMENT", confirm=False)
        PurchaseOrder.objects.filter(pk=first["id"]).update(archived_at=timezone.now())
        order_ids = [first["id"], second["id"]]
        line_ids = list(PurchaseOrderLine.objects.filter(purchase_order_id__in=order_ids).values_list("pk", flat=True))
        before = self.detail()
        self.assertEqual(before.data["data"]["progress"]["lines"][0]["purchased_quantity"], "0.0000")
        self.assertTrue(before.data["data"]["deletion"]["can_delete"])
        response = self.delete_group(etag=before["ETag"])
        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(PurchaseOrder.objects.filter(pk__in=order_ids).exists())
        self.assertFalse(PurchaseOrderLine.objects.filter(pk__in=line_ids).exists())
        self.assertFalse(PurchaseGroupLine.objects.filter(pk=self.line_id).exists())

        self.inventory_material = RawMaterialInformation.objects.create(
            item_type="MATERIAL", material_number="DELETE-REBUILD-MATERIAL",
            category=self.inventory_material.category, material_name="修改后新增材料", specification="M10",
            unit=self.inventory_material.unit, warehouse_number="DELETE-WH", warehouse_name="测试材料仓",
        )
        latest_bom, latest_line = self.make_bom(
            self.product_line, version=2, section_type=BomSectionType.ACCESSORY,
            part_name="修改后新增材料", budget_quantity="75",
        )
        source = self.get_source(self.task, latest_bom)
        self.assertEqual(source.status_code, 200, source.data)
        recreated = self.client.post("/api/v1/purchase-groups/", {
            "production_task_id": str(self.task.pk), "bom_id": str(latest_bom.pk),
            "source_revision": source.data["data"]["source_revision"],
        }, format="json")
        self.assertEqual(recreated.status_code, 201, recreated.data)
        self.assertNotEqual(recreated.data["data"]["id"], self.group_id)
        new_line = PurchaseGroupLine.objects.get(purchase_group_id=recreated.data["data"]["id"])
        self.assertEqual(new_line.source_bom_line_id_snapshot, latest_line.pk)
        self.assertEqual(new_line.required_quantity, 75)
        self.assertEqual(new_line.source_snapshot["calculation_snapshot"]["raw_material_id"], str(self.inventory_material.pk))

    def test_every_confirmed_status_blocks_even_when_batch_is_archived(self):
        batch = self.batch("12")
        for state in ["SUBMITTED", "PURCHASING", "COMPLETED"]:
            for archived in [False, True]:
                with self.subTest(status=state, archived=archived):
                    PurchaseOrder.objects.filter(pk=batch["id"]).update(
                        status=state, archived_at=timezone.now() if archived else None,
                    )
                    self.assert_blocked()

    def test_draft_with_completion_record_blocks_deletion(self):
        batch = self.batch("12", confirm=False)
        PurchaseOrder.objects.filter(pk=batch["id"]).update(completed_at=timezone.now())
        self.assert_blocked()

    def test_manually_completed_group_blocks_deletion(self):
        PurchaseGroup.objects.filter(pk=self.group_id).update(
            manual_completed_at=timezone.now(), manual_completed_by_employee=self.employee,
        )
        self.assert_blocked()

    def test_draft_with_material_inbound_blocks_deletion(self):
        batch = self.batch("12", confirm=False)
        inbound = MaterialInbound.objects.create(
            inbound_number="DELETE-INBOUND", purchase_order_id=batch["id"], received_by_employee=self.employee,
        )
        self.assert_blocked()
        self.assertTrue(MaterialInbound.objects.filter(pk=inbound.pk).exists())

    def test_return_link_blocks_even_without_inbound_order_link(self):
        batch = self.batch("12", confirm=False)
        inbound = MaterialInbound.objects.create(inbound_number="DELETE-RETURN-INBOUND", received_by_employee=self.employee)
        returned = PurchaseReturn.objects.create(
            return_number="DELETE-RETURN", purchase_order_id=batch["id"], inbound=inbound,
            supplier=self.supplier, supplier_number_snapshot=self.supplier.supplier_number,
            supplier_name_snapshot=self.supplier.supplier_name, generated_by_employee=self.employee,
        )
        self.assert_blocked()
        self.assertTrue(PurchaseReturn.objects.filter(pk=returned.pk).exists())

    def test_missing_and_stale_etags_do_not_delete(self):
        etag = self.detail()["ETag"]
        self.assertEqual(self.client.delete(self.delete_url).status_code, 428)
        batch = self.batch("12", confirm=False)
        response = self.delete_group(etag=etag)
        self.assertEqual(response.status_code, 412, response.data)
        self.assertTrue(PurchaseGroup.objects.filter(pk=self.group_id).exists())
        self.assertTrue(PurchaseOrder.objects.filter(pk=batch["id"]).exists())
        self.assertEqual(self.client.delete(f"/api/v1/purchase-groups/{uuid4()}/", HTTP_IF_MATCH=etag).status_code, 404)

    def test_delete_permission_is_required(self):
        etag = self.detail()["ETag"]
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label="procurement", codename="delete_purchaseorder"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.delete_group(etag=etag).status_code, 403)
        self.assertTrue(PurchaseGroup.objects.filter(pk=self.group_id).exists())

    def test_out_of_scope_group_returns_not_found(self):
        outsider = get_user_model().objects.create_user(username="delete_outsider", password="test-password")
        Employee.objects.create(user=outsider, employee_code="DELETE-OUTSIDER", display_name="范围外员工")
        outsider.user_permissions.set(Permission.objects.filter(content_type__app_label="procurement"))
        client = APIClient()
        client.force_authenticate(outsider)
        self.assertEqual(client.get(self.delete_url).status_code, 404)
        self.assertEqual(self.delete_group(client=client).status_code, 404)
        self.assertTrue(PurchaseGroup.objects.filter(pk=self.group_id).exists())

    def test_session_csrf_is_enforced_and_valid_token_can_delete(self):
        etag = self.detail()["ETag"]
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(self.delete_group(etag=etag, client=client).status_code, 403)
        self.assertTrue(PurchaseGroup.objects.filter(pk=self.group_id).exists())
        token = _get_new_csrf_string()
        client.cookies["csrftoken"] = token
        response = client.delete(self.delete_url, HTTP_IF_MATCH=etag, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 204, response.data)

    def test_audit_failure_rolls_back_group_drafts_and_lines(self):
        batch = self.batch("12", confirm=False)
        line_ids = list(PurchaseOrderLine.objects.filter(purchase_order_id=batch["id"]).values_list("pk", flat=True))
        etag = self.detail()["ETag"]
        with patch("apps.procurement.group_services.write_audit_log", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                self.delete_group(etag=etag)
        self.assertTrue(PurchaseGroup.objects.filter(pk=self.group_id).exists())
        self.assertTrue(PurchaseGroupLine.objects.filter(pk=self.line_id).exists())
        self.assertTrue(PurchaseOrder.objects.filter(pk=batch["id"]).exists())
        self.assertEqual(PurchaseOrderLine.objects.filter(pk__in=line_ids).count(), len(line_ids))
        self.assertEqual(self.detail()["ETag"], etag)
        self.assertFalse(AuditLog.objects.filter(object_type="PURCHASE_GROUP", object_id=self.group_id, action="DELETED").exists())


class PurchaseGroupDeleteConcurrencyTests(PurchaseGroupDeleteFixture, TransactionTestCase):
    def race(self, methods):
        user_id, group_id, etag = self.user.pk, self.group_id, self.detail()["ETag"]
        payload = self.batch_payload("12")
        barrier = Barrier(2)

        def call(method):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=user_id))
                barrier.wait(timeout=15)
                if method == "DELETE":
                    response = client.delete(f"/api/v1/purchase-groups/{group_id}/", HTTP_IF_MATCH=etag)
                else:
                    response = client.post(f"/api/v1/purchase-groups/{group_id}/batches/", payload,
                                           format="json", HTTP_IF_MATCH=etag)
                return response.status_code, response.data
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(call, method) for method in methods]
            return [future.result(timeout=40) for future in futures]

    def test_concurrent_deletes_only_delete_once(self):
        self.batch("12", confirm=False)
        results = self.race(["DELETE", "DELETE"])
        self.assertEqual(sorted(status for status, _ in results), [204, 404], results)
        self.assertFalse(PurchaseGroup.objects.filter(pk=self.group_id).exists())
        self.assertFalse(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).exists())
        self.assertEqual(AuditLog.objects.filter(object_type="PURCHASE_GROUP", object_id=self.group_id, action="DELETED").count(), 1)

    def test_create_batch_and_delete_serialize_without_orphans(self):
        results = self.race(["DELETE", "POST"])
        statuses = tuple(status for status, _ in results)
        self.assertIn(statuses, [(204, 404), (412, 201)], results)
        if statuses[0] == 204:
            self.assertFalse(PurchaseGroup.objects.filter(pk=self.group_id).exists())
            self.assertFalse(PurchaseGroupLine.objects.filter(pk=self.line_id).exists())
            self.assertFalse(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).exists())
        else:
            self.assertTrue(PurchaseGroup.objects.filter(pk=self.group_id).exists())
            self.assertEqual(PurchaseOrder.objects.filter(purchase_group_id=self.group_id, status="DRAFT").count(), 1)
            self.assertEqual(PurchaseOrderLine.objects.filter(purchase_group_line_id=self.line_id).count(), 1)
