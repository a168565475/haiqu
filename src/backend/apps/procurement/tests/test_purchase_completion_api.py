from unittest.mock import patch
import copy
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from apps.inventory.tests.test_inventory_api import MaterialInventoryApiTests
from apps.inventory.models import MaterialInbound, MaterialInboundStatus
from apps.organizations.models import Employee
from apps.procurement.models import PurchaseReturn, PurchaseReturnLine, Supplier


class PurchaseCompletionApiTests(MaterialInventoryApiTests):
    def test_return_list_stats_filters_ordering_and_view_only_scope(self):
        first_receipt = self.receive("4.0000")
        self.assertEqual(self.confirm_quality(first_receipt, return_quantity="1.0000").status_code, 200)
        first = PurchaseReturn.objects.get()
        self.assertEqual(self.advance_return(first, "confirm").status_code, 200)
        self.assertEqual(self.advance_return(first, "complete").status_code, 200)
        second_receipt = self.receive("6.5000", "7.5000")
        self.assertEqual(self.confirm_quality(second_receipt, return_quantity="1.0000").status_code, 200)
        second = PurchaseReturn.objects.exclude(pk=first.pk).get()
        PurchaseReturn.objects.filter(pk=first.pk).update(updated_at="2026-09-10T01:00:00Z")
        PurchaseReturn.objects.filter(pk=second.pk).update(updated_at="2026-09-11T01:00:00Z")
        Supplier.objects.create(supplier_number="GYS98889", supplier_name="没有退货的供应商", supplier_type="MATERIAL", supplier_categories=["TUBE"])
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label="procurement", codename="view_purchaseorder"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        base = "/api/v1/purchase-returns/"
        response = self.client.get(base, {"page_size": 1})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["meta"]["total"], 2)
        self.assertEqual(response.data["data"][0]["id"], str(second.pk))
        self.assertEqual(self.client.get(base, {"purchase_order_id": str(self.order.pk)}).data["meta"]["total"], 2)
        self.assertEqual(self.client.get(base + "stats/", {"purchase_order_id": str(uuid.uuid4())}).data["data"]["total"], 0)
        ascending = self.client.get(base, {"page_size": 1, "ordering": "updated_at"})
        self.assertEqual(ascending.data["data"][0]["id"], str(first.pk))
        expected = {"total": 2, "QUALITY_GENERATED": 1, "PROCUREMENT_CONFIRMED": 0, "COMPLETED": 1}
        self.assertEqual(self.client.get(base + "stats/", {"status": "COMPLETED", "page_size": 1}).data["data"], expected)
        self.assertEqual(self.client.get(base, {"status": "COMPLETED"}).data["meta"]["total"], 1)
        self.assertEqual(self.client.get(base + "stats/", {"q": first.return_number}).data["data"]["total"], 1)
        self.assertEqual(self.client.get(base + "stats/", {"q": "无此退货"}).data["data"]["total"], 0)
        self.assertEqual(self.client.get(base, {"supplier_id": str(uuid.uuid4())}).data["meta"]["total"], 0)
        suppliers = self.client.get(base + "filter-options/").data["data"]["suppliers"]
        self.assertEqual(len(suppliers), 1)
        self.assertEqual(str(suppliers[0]["id"]), str(self.supplier.pk))
        self.assertEqual(self.client.post(base + str(second.pk) + "/confirm/", {}, format="json").status_code, 403)
        for query in [{"status": "NONE"}, {"supplier_id": "bad"}, {"ordering": "supplier"}]:
            self.assertEqual(self.client.get(base, query).status_code, 400)
            self.assertEqual(self.client.get(base + "stats/", query).status_code, 400)
        self.order.archived_at = "2026-09-11T02:00:00Z"
        self.order.save(update_fields=["archived_at"])
        self.assertEqual(self.client.get(base).data["meta"]["total"], 0)
        self.assertEqual(self.client.get(base + "stats/").data["data"]["total"], 0)
        self.assertEqual(self.client.get(base + "filter-options/").data["data"]["suppliers"], [])

    def test_warehouse_and_quality_can_view_return_but_cannot_procurement_confirm(self):
        receipt = self.receive()
        self.assertEqual(self.confirm_quality(receipt, return_quantity="1.0000").status_code, 200)
        record = PurchaseReturn.objects.get()
        for permission_codename in ["quality_confirm_material", "receive_material"]:
            self.user.user_permissions.set(Permission.objects.filter(
                codename__in=[permission_codename, "view_productiontask"],
            ))
            self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))

            listing = self.client.get(
                "/api/v1/purchase-returns/",
                {"purchase_order_id": str(self.order.pk)},
            )
            self.assertEqual(listing.status_code, 200, listing.data)
            self.assertEqual(listing.data["meta"]["total"], 1)
            detail = self.client.get(f"/api/v1/purchase-returns/{record.pk}/")
            self.assertEqual(detail.status_code, 200, detail.data)
            self.assertEqual(
                self.client.post(
                    f"/api/v1/purchase-returns/{record.pk}/confirm/",
                    {},
                    format="json",
                    HTTP_IF_MATCH=detail["ETag"],
                ).status_code,
                403,
            )

        outsider = get_user_model().objects.create_user(username="warehouse_return_outsider")
        Employee.objects.create(user=outsider, employee_code="WAREHOUSE_OUT", display_name="范围外仓库")
        outsider.user_permissions.set(Permission.objects.filter(
            codename__in=["receive_material", "view_productiontask"],
        ))
        outsider_client = APIClient()
        outsider_client.force_authenticate(outsider)
        outsider_listing = outsider_client.get("/api/v1/purchase-returns/")
        self.assertEqual(outsider_listing.status_code, 200, outsider_listing.data)
        self.assertEqual(outsider_listing.data["data"], [])

    def test_view_only_filter_options_do_not_expose_creation_sources_or_other_suppliers(self):
        Supplier.objects.create(supplier_number="GYS98889", supplier_name="其他供应商", supplier_type="MATERIAL", supplier_categories=["TUBE"])
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label="procurement", codename="view_purchaseorder"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        response = self.client.get("/api/v1/purchase-orders/filter-options/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["data"]["production_tasks"]), 1)
        self.assertEqual(len(response.data["data"]["suppliers"]), 1)
        self.assertEqual(str(response.data["data"]["suppliers"][0]["id"]), str(self.supplier.pk))
        self.assertEqual(self.client.get("/api/v1/purchase-orders/options/").status_code, 403)

    def test_multiple_supplier_returns_must_all_finish_and_keep_source_details(self):
        supplier = Supplier.objects.create(supplier_number="GYS98889", supplier_name="第二家供应商", supplier_type="MATERIAL", supplier_categories=["TUBE"])
        second_line = copy.copy(self.purchase_line)
        second_line.pk = uuid.uuid4()
        second_line._state.adding = True
        second_line.line_number = 2
        second_line.source_bom_line_id_snapshot = uuid.uuid4()
        second_line.supplier = supplier
        second_line.supplier_name_snapshot = supplier.supplier_name
        second_line.supplier_number_snapshot = supplier.supplier_number
        second_line.save(force_insert=True)
        payload = self.payload(quantity="10.5000")
        payload["items"].append({**payload["items"][0], "purchase_order_line_id": str(second_line.pk)})
        receipt = self.client.post("/api/v1/material-inventory/receipts/", payload, format="json")
        self.assertEqual(receipt.status_code, 201, receipt.data)
        self.assertEqual(self.confirm_quality(receipt, return_quantity="1.0000").status_code, 200)
        records = list(PurchaseReturn.objects.order_by("supplier_number_snapshot"))
        self.assertEqual(len(records), 2)
        supplier.supplier_name = "已改名供应商"
        supplier.save()
        detail = self.client.get(f"/api/v1/purchase-returns/{records[1].pk}/").data["data"]
        self.assertEqual(detail["supplier_name"], "第二家供应商")
        self.assertEqual(detail["lines"][0]["part_name"], "测试钢管")
        self.assertEqual(detail["lines"][0]["unit"], "支")
        self.assertEqual(detail["lines"][0]["quality_remark"], "检验合格")
        for index, record in enumerate(records):
            self.assertEqual(self.complete_order("已退货").status_code, 409)
            self.assertEqual(self.advance_return(record, "confirm").status_code, 200)
            inbound_status = self.client.get("/api/v1/material-inventory/procurement-inbound-orders/").data["data"][0]
            self.assertEqual(
                inbound_status["return_status"],
                "QUALITY_GENERATED" if index == 0 else "PROCUREMENT_CONFIRMED",
            )
            self.assertEqual(self.advance_return(record, "complete").status_code, 200)
            if index == 0:
                inbound_status = self.client.get("/api/v1/material-inventory/procurement-inbound-orders/").data["data"][0]
                self.assertEqual(inbound_status["return_status"], "QUALITY_GENERATED")
                order_summary = self.client.get("/api/v1/purchase-orders/").data["data"][0]["completion"]
                self.assertEqual(order_summary["return_status"], "QUALITY_GENERATED")
                self.assertEqual(order_summary["return_total"], 2)
                self.assertEqual(order_summary["return_completed_count"], 1)
                self.assertEqual(order_summary["return_pending_confirmation_count"], 1)
                self.assertEqual(order_summary["return_status_display"], "已完成1/2 · 1单待确认")
        self.assertEqual(self.complete_order("全部退货已完成").status_code, 200)

    def test_purchase_return_filter_matches_readonly_summary_and_missing_records_block_completion(self):
        receipt = self.receive()
        self.assertEqual(self.confirm_quality(receipt, return_quantity="1.0000").status_code, 200)
        record = PurchaseReturn.objects.get()
        for return_status, count in [("QUALITY_GENERATED", 1), ("NONE", 0), ("COMPLETED", 0), ("MISSING", 0)]:
            response = self.client.get("/api/v1/purchase-orders/", {"return_status": return_status})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(len(response.data["data"]), count)
            if return_status == "QUALITY_GENERATED":
                self.assertEqual(response.data["data"][0]["completion"]["return_status_display"], "品质生成 · 待确认退货")
        self.assertEqual(self.advance_return(record, "confirm").status_code, 200)
        response = self.client.get("/api/v1/purchase-orders/", {"return_status": "PROCUREMENT_CONFIRMED"})
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["completion"]["return_status_display"], "已确认退货 · 待退货完成")
        PurchaseReturnLine.objects.all().delete()
        response = self.client.get("/api/v1/purchase-orders/", {"return_status": "MISSING"})
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["completion"]["return_status"], "MISSING")
        self.assertEqual(self.complete_order("缺少单据").status_code, 409)
        invalid = self.client.get("/api/v1/purchase-orders/", {"return_status": "INVALID"})
        self.assertEqual(invalid.status_code, 400)

    # 复用材料入库的真实业务夹具，测试经仓库、品质到采购的完整调用链。
    def receive(self, quantity="10.5000", expected="10.5000"):
        response = self.client.post("/api/v1/material-inventory/receipts/", self.payload(quantity=quantity, expected=expected), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def complete_order(self, remark="", *, etag=None):
        url = f"/api/v1/purchase-orders/{self.order.pk}/"
        if etag is None:
            detail = self.client.get(url)
            self.assertEqual(detail.status_code, 200, detail.data)
            etag = detail["ETag"]
        return self.client.post(f"{url}complete/", {"remark": remark}, format="json", HTTP_IF_MATCH=etag)

    def advance_return(self, record, action):
        url = f"/api/v1/purchase-returns/{record.pk}/"
        detail = self.client.get(url)
        self.assertEqual(detail.status_code, 200, detail.data)
        return self.client.post(f"{url}{action}/", {}, format="json", HTTP_IF_MATCH=detail["ETag"])

    def test_purchase_completion_requires_started_inbound_flows_but_not_full_quantity(self):
        self.assertEqual(self.complete_order().status_code, 409)
        partial = self.receive("4.2500")
        self.assertEqual(self.complete_order().status_code, 409)
        self.assertEqual(self.confirm_quality(partial).status_code, 200)
        pending = self.receive("1.0000", "6.2500")
        self.assertEqual(self.complete_order().status_code, 409)
        self.assertEqual(self.confirm_quality(pending).status_code, 200)
        result = self.complete_order()
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["data"]["status"], "COMPLETED")
        self.assertEqual(result.data["data"]["completion"]["inbound_status"], "PARTIAL_RECEIVED")
        self.assertEqual(result.data["data"]["completion"]["inbound_status_display"], "部分入库")
        self.assertTrue(result.data["data"]["completed_at"])
        self.assertEqual(PurchaseReturn.objects.count(), 0)
        self.assertEqual(self.complete_order().status_code, 409)
        stats = self.client.get("/api/v1/purchase-orders/stats/")
        self.assertEqual(stats.data["data"]["completed"], 1)
        listing = self.client.get("/api/v1/purchase-orders/", {"status": "COMPLETED"})
        self.assertEqual(len(listing.data["data"]), 1)

    def test_purchase_order_summary_follows_material_inbound_workflow(self):
        def inbound_status():
            response = self.client.get("/api/v1/purchase-orders/", {"status": "PURCHASING"})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(len(response.data["data"]), 1)
            completion = response.data["data"][0]["completion"]
            return completion["inbound_status"], completion["inbound_status_display"]

        self.assertEqual(inbound_status(), ("PENDING_RECEIPT", "等待入库"))
        first = self.receive("4.2500")
        self.assertEqual(inbound_status(), ("PENDING_QUALITY", "待品质确认"))
        self.assertEqual(self.confirm_quality(first).status_code, 200)
        self.assertEqual(inbound_status(), ("PARTIAL_RECEIVED", "部分入库"))
        second = self.receive("6.2500", "6.2500")
        self.assertEqual(inbound_status(), ("PENDING_QUALITY", "待品质确认"))
        self.assertEqual(self.confirm_quality(second).status_code, 200)
        self.assertEqual(inbound_status(), ("COMPLETED", "已完成"))

    def test_return_workflow_requires_confirmation_and_remark_but_not_replenishment(self):
        receipt = self.receive()
        self.assertEqual(self.confirm_quality(receipt, return_quantity="2.5000").status_code, 200)
        record = PurchaseReturn.objects.get()
        self.assertEqual(record.status, "QUALITY_GENERATED")
        self.assertEqual(str(record.lines.get().quantity), "2.5000")
        self.assertEqual(self.complete_order("退货处理中").status_code, 409)
        self.assertEqual(self.advance_return(record, "complete").status_code, 409)
        self.assertEqual(self.advance_return(record, "confirm").status_code, 200)
        self.assertEqual(self.advance_return(record, "confirm").status_code, 409)
        self.assertEqual(self.complete_order("已确认退货").status_code, 409)
        self.assertEqual(self.advance_return(record, "complete").status_code, 200)
        self.assertEqual(self.complete_order("  ").status_code, 400)
        completed = self.complete_order("  退货已完成  ")
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(completed.data["data"]["completion_remark"], "退货已完成")
        self.assertEqual(completed.data["data"]["completion"]["return_status"], "COMPLETED")
        # 完成后的补货仍可正常收货、质检，不会撤销已完成状态。
        replenishment = self.receive("2.5000", "2.5000")
        self.assertEqual(self.confirm_quality(replenishment).status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "COMPLETED")
        self.assertEqual(PurchaseReturn.objects.count(), 1)

    def test_completed_order_waits_for_latest_return_before_another_replenishment(self):
        first_receipt = self.receive()
        self.assertEqual(self.confirm_quality(first_receipt, return_quantity="2.5000").status_code, 200)
        first_return = PurchaseReturn.objects.get()
        self.assertEqual(self.advance_return(first_return, "confirm").status_code, 200)
        self.assertEqual(self.advance_return(first_return, "complete").status_code, 200)
        self.assertEqual(self.complete_order("首轮退货已完成").status_code, 200)

        replenishment = self.receive("2.5000", "2.5000")
        self.assertEqual(self.confirm_quality(replenishment, return_quantity="1.0000").status_code, 200)
        latest_return = PurchaseReturn.objects.exclude(pk=first_return.pk).get()
        self.assertEqual(latest_return.status, "QUALITY_GENERATED")

        blocked = self.client.post(
            "/api/v1/material-inventory/receipts/",
            self.payload(quantity="1.0000", expected="1.0000"),
            format="json",
        )
        self.assertEqual(blocked.status_code, 409, blocked.data)

    def test_quality_return_generation_is_atomic_and_cannot_duplicate(self):
        receipt = self.receive()
        with patch("apps.procurement.completion_services.next_business_number", side_effect=RuntimeError("模拟编号异常")):
            with self.assertRaises(RuntimeError):
                self.confirm_quality(receipt, return_quantity="1.0000")
        inbound = MaterialInbound.objects.get(pk=receipt.data["data"]["id"])
        self.assertEqual(inbound.status, MaterialInboundStatus.PENDING_QUALITY)
        self.assertEqual(inbound.lines.get().return_quantity, 0)
        self.assertEqual(PurchaseReturn.objects.count(), 0)
        self.assertEqual(self.confirm_quality(receipt, return_quantity="1.0000").status_code, 200)
        self.assertEqual(self.confirm_quality(receipt, return_quantity="1.0000").status_code, 409)
        self.assertEqual(PurchaseReturn.objects.count(), 1)
        self.assertEqual(PurchaseReturnLine.objects.count(), 1)

    def test_completion_and_return_actions_enforce_scope_permission_and_etag(self):
        receipt = self.receive()
        self.assertEqual(self.confirm_quality(receipt, return_quantity="1.0000").status_code, 200)
        record = PurchaseReturn.objects.get()
        order_url = f"/api/v1/purchase-orders/{self.order.pk}/complete/"
        return_url = f"/api/v1/purchase-returns/{record.pk}/confirm/"
        for url in [order_url, return_url]:
            self.assertEqual(self.client.post(url, {}, format="json").status_code, 428)
            self.assertEqual(self.client.post(url, {}, format="json", HTTP_IF_MATCH='"stale"').status_code, 412)
        outsider = get_user_model().objects.create_user(username="purchase_outsider")
        Employee.objects.create(user=outsider, employee_code="PUR_OUT", display_name="其他采购")
        outsider.user_permissions.set(Permission.objects.filter(content_type__app_label="procurement"))
        other_client = APIClient()
        other_client.force_authenticate(outsider)
        self.assertEqual(other_client.get("/api/v1/purchase-returns/").data["data"], [])
        self.assertEqual(other_client.get("/api/v1/purchase-orders/filter-options/").data["data"]["suppliers"], [])
        self.assertEqual(other_client.post(return_url, {}, format="json").status_code, 404)
        self.assertEqual(other_client.post(order_url, {}, format="json").status_code, 404)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label="procurement", codename="submit_purchaseorder"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.client.post(return_url, {}, format="json").status_code, 403)
        self.assertEqual(self.client.post(order_url, {}, format="json").status_code, 403)
