"""采购表发布、入库角标与完成状态的 API 回归；内容校验按用例隔离。"""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection, connections
from django.utils import timezone
from rest_framework.test import APITestCase, APITransactionTestCase, APIClient

from apps.audit.models import AuditLog
from apps.procurement.models import PurchaseOrder, SupplierPurchaseSheet, Supplier
from apps.procurement.tests import test_purchase_order_api as purchase_tests
from apps.procurement.tests import test_purchase_completion_api as completion_tests
from apps.procurement.tests import test_sample_purchase_api as sample_tests
from apps.inventory.tests import test_inventory_api as inventory_tests


class PublishingFixture:
    setUp = purchase_tests.PurchaseOrderApiTests.setUp
    make_task = purchase_tests.PurchaseOrderApiTests.make_task
    make_product_line = purchase_tests.PurchaseOrderApiTests.make_product_line
    make_bom = purchase_tests.PurchaseOrderApiTests.make_bom
    get_source = purchase_tests.PurchaseOrderApiTests.get_source
    create_payload = staticmethod(purchase_tests.PurchaseOrderApiTests.create_payload)
    create_generated_supplier_sheet = purchase_tests.PurchaseOrderApiTests.create_generated_supplier_sheet

    def make_pair(self):
        first = self.create_generated_supplier_sheet("PROGRESS")
        supplier = Supplier.objects.create(supplier_number="GYS90003", supplier_name="第二供应商", supplier_type="MATERIAL")
        line = first.purchase_order.lines.first()
        line.pk = uuid.uuid4()
        line.line_number = 2
        line.source_bom_line_id_snapshot = uuid.uuid4()
        line.supplier = supplier
        line.save(force_insert=True)
        second = SupplierPurchaseSheet.objects.create(
            purchase_order=first.purchase_order, supplier=supplier, sheet_number="CGDD2099123102",
            supplier_name_snapshot=supplier.supplier_name, template_version=first.template_version,
            status="DRAFT", content_snapshot=deepcopy(first.content_snapshot), total_amount=first.total_amount,
        )
        return first, second

    def publish(self, sheet, client=None):
        client = client or self.client
        url = f"/api/v1/supplier-purchase-sheets/{sheet.pk}/"
        detail = client.get(url)
        self.assertEqual(detail.status_code, 200, detail.data)
        return client.post(url + "publish/", {}, format="json", HTTP_IF_MATCH=detail["ETag"])

    def assert_status(self, sheet, status):
        sheet.purchase_order.refresh_from_db()
        self.assertEqual(sheet.purchase_order.status, status)


class PurchasePublishingTests(PublishingFixture, APITestCase):
    def test_last_supplier_publication_updates_order_stats_and_revision_does_not_regress(self):
        first, second = self.make_pair()
        with patch("apps.procurement.purchase_sheet_services._prepare_sheet_for_publish"):
            self.assertEqual(self.publish(first).status_code, 200)
            self.assert_status(first, "SUBMITTED")
            result = self.publish(second)
            self.assertEqual(result.status_code, 200, result.data)
            self.assert_status(first, "PURCHASING")
        self.assertEqual(self.client.get("/api/v1/purchase-orders/stats/").data["data"]["purchasing"], 1)
        listing = self.client.get("/api/v1/purchase-orders/", {"status": "PURCHASING"})
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(listing.data["meta"]["total"], 1)
        self.assertEqual(listing.data["data"][0]["status_display"], "采购中")
        revised = self.client.post(f"/api/v1/supplier-purchase-sheets/{second.pk}/new-version/", {}, format="json", HTTP_IF_MATCH=result["ETag"])
        self.assertEqual(revised.status_code, 201, revised.data)
        self.assert_status(first, "PURCHASING")
        self.assertEqual(AuditLog.objects.filter(object_type="PURCHASE_ORDER", object_id=str(first.purchase_order_id), action="PURCHASING").count(), 1)

    def test_atomic_batch_failure_and_completed_order_preserved(self):
        first, second = self.make_pair()
        from rest_framework.exceptions import ValidationError
        with patch("apps.procurement.purchase_sheet_services._prepare_sheet_for_publish", side_effect=[None, ValidationError("无效内容")]):
            response = self.client.post("/api/v1/supplier-purchase-sheets/batch-publish/", {"ids": [str(first.pk), str(second.pk)]}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assert_status(first, "SUBMITTED")
        self.assertFalse(SupplierPurchaseSheet.objects.filter(purchase_order=first.purchase_order, status="PUBLISHED").exists())
        PurchaseOrder.objects.filter(pk=first.purchase_order_id).update(status="COMPLETED")
        with patch("apps.procurement.purchase_sheet_services._prepare_sheet_for_publish"):
            result = self.client.post("/api/v1/supplier-purchase-sheets/batch-publish/", {"ids": [str(first.pk), str(second.pk)]}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assert_status(first, "COMPLETED")

    def test_missing_supplier_sheet_does_not_start_and_migration_is_selective(self):
        from importlib import import_module
        migration = import_module("apps.procurement.migrations.0016_purchase_order_purchasing")
        first, second = self.make_pair()
        second.archived_at = timezone.now()
        second.save()
        with patch("apps.procurement.purchase_sheet_services._prepare_sheet_for_publish"):
            self.assertEqual(self.publish(first).status_code, 200)
        self.assert_status(first, "SUBMITTED")
        with connection.schema_editor() as editor:
            migration.backfill_purchasing(apps, editor)
        self.assert_status(first, "SUBMITTED")
        second.archived_at = None
        second.status = "PUBLISHED"
        second.save()
        with connection.schema_editor() as editor:
            migration.backfill_purchasing(apps, editor)
            migration.backfill_purchasing(apps, editor)
        self.assert_status(first, "PURCHASING")


class PurchaseProgressInventoryTests(APITestCase):
    setUp = inventory_tests.MaterialInventoryApiTests.setUp
    payload = inventory_tests.MaterialInventoryApiTests.payload
    confirm_quality = inventory_tests.MaterialInventoryApiTests.confirm_quality
    receive = completion_tests.PurchaseCompletionApiTests.receive
    complete_order = completion_tests.PurchaseCompletionApiTests.complete_order
    advance_return = completion_tests.PurchaseCompletionApiTests.advance_return

    def badge(self):
        response = self.client.get("/api/v1/material-inventory/options/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]["purchasing_order_count"]

    def test_purchasing_receiving_completion_and_badge(self):
        self.assertEqual(self.badge(), 0)
        self.order.status = "PURCHASING"
        self.order.save()
        self.assertEqual(self.badge(), 1)
        orders = self.client.get("/api/v1/material-inventory/eligible-purchase-orders/")
        self.assertIn(str(self.order.pk), [str(row["id"]) for row in orders.data["data"]])
        lines = self.client.get("/api/v1/material-inventory/eligible-lines/", {"purchase_order_id": str(self.order.pk)})
        self.assertTrue(lines.data["data"])
        received = self.receive()
        self.assertEqual(self.badge(), 1)  # 收满但尚未完成采购，仍按状态计数。
        self.assertEqual(self.complete_order().status_code, 409)
        self.assertEqual(self.confirm_quality(received).status_code, 200)
        completed = self.complete_order()
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(self.badge(), 0)
        log = AuditLog.objects.get(object_type="PURCHASE_ORDER", object_id=str(self.order.pk), action="COMPLETED")
        self.assertEqual(log.before_data["status"], "PURCHASING")

    def test_purchasing_returns_still_require_completion_and_remark(self):
        self.order.status = "PURCHASING"
        self.order.save()
        completion_tests.PurchaseCompletionApiTests.test_return_workflow_requires_confirmation_and_remark_but_not_replenishment(self)

    def test_badge_archival_permission_and_scope(self):
        self.order.status = "PURCHASING"
        self.order.save()
        self.assertEqual(self.badge(), 1)
        self.order.archived_at = timezone.now()
        self.order.save()
        self.assertEqual(self.badge(), 0)
        self.order.archived_at = None
        self.order.save()
        user = get_user_model().objects.create_user(username="unrelated_inventory")
        from apps.organizations.models import Employee
        Employee.objects.create(user=user, employee_code="UNRELATED_INV", display_name="其他仓库员")
        user.user_permissions.set(Permission.objects.filter(content_type__app_label="inventory", codename__in=["view_materialinbound", "receive_material"]))
        self.client.force_authenticate(user)
        self.assertEqual(self.badge(), 0)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label="inventory", codename="receive_material"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.badge(), 0)


class SampleProgressTests(APITestCase):
    setUp = sample_tests.SamplePurchaseApiTests.setUp
    purchase_payload = sample_tests.SamplePurchaseApiTests.purchase_payload
    create_order = sample_tests.SamplePurchaseApiTests.create_order

    def test_sample_publication_and_scoped_badge(self):
        self.create_order()
        url = self.root + self.sample_order_id + "/"
        self.assertEqual(self.client.post(url + "confirm/", {}, format="json").status_code, 200)
        template = self.client.get(url + "sheet-options/").data["data"]["templates"][0]
        generated = self.client.post(url + "generate-sheets/", {"assignments": [{"supplier_id": str(self.supplier.pk), "template_version_id": str(template["version_id"])}]}, format="json")
        self.assertEqual(generated.status_code, 201, generated.data)
        sheet_url = "/api/v1/supplier-purchase-sheets/" + str(generated.data["data"][0]["id"]) + "/"
        detail = self.client.get(sheet_url)
        with patch("apps.procurement.purchase_sheet_services._prepare_sheet_for_publish"):
            result = self.client.post(sheet_url + "publish/", {}, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(PurchaseOrder.objects.get(pk=self.sample_order_id).status, "PURCHASING")
        self.assertEqual(self.client.get("/api/v1/material-inventory/options/").data["data"]["purchasing_order_count"], 1)


class ConcurrentPublishingTests(PublishingFixture, APITransactionTestCase):
    def test_simultaneous_final_publications_start_purchasing_once(self):
        first, second = self.make_pair()
        gate = Barrier(2)
        user_id = self.user.pk
        def publish_in_worker(sheet):
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=user_id))
                gate.wait(timeout=15)
                return self.publish(sheet, client).status_code
            finally:
                connections.close_all()
        with patch("apps.procurement.purchase_sheet_services._prepare_sheet_for_publish"):
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(list(pool.map(publish_in_worker, [first, second])), [200, 200])
        self.assert_status(first, "PURCHASING")
        self.assertEqual(AuditLog.objects.filter(object_type="PURCHASE_ORDER", object_id=str(first.purchase_order_id), action="PURCHASING").count(), 1)
