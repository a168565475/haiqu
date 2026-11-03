from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.boms.models import BomLine, BomSectionType
from apps.boms.material_flow_calculations import pipe_plan
from apps.access_control.models import RoleActionGrant
from apps.inventory.models import Warehouse, WarehouseZone
from apps.organizations.models import Employee, EmployeeRoleAssignment, RoleProfile
from apps.production_tasks.cost_selectors import task_cost_summary
from apps.production_tasks.models import ProductionTaskStatus
from apps.reference_data.models import ProductCategory, ProductionUnit

from ..models import PurchaseGroup, PurchaseOrder, PurchaseReturn
from . import test_purchase_order_api as order_tests


class PurchaseGroupApiTests(APITestCase):
    make_task = order_tests.PurchaseOrderApiTests.make_task
    make_product_line = order_tests.PurchaseOrderApiTests.make_product_line
    make_bom = order_tests.PurchaseOrderApiTests.make_bom
    get_source = order_tests.PurchaseOrderApiTests.get_source

    def setUp(self):
        order_tests.PurchaseOrderApiTests.setUp(self)
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label__in=[
            "procurement", "inventory", "production_tasks", "access_control",
        ]))
        self.task = self.make_task("GROUP")
        self.product_line = self.make_product_line(self.task)
        self.bom, self.bom_line = self.make_bom(self.product_line, section_type=BomSectionType.ACCESSORY, budget_quantity="100")
        # 测试替身仅用于隔离数据库；实际接口、Session和数量规则仍走真实服务。
        source = self.get_source(self.task).data["data"]
        self.group_payload = {"production_task_id": str(self.task.pk), "bom_id": str(self.bom.pk), "source_revision": source["source_revision"]}
        response = self.client.post("/api/v1/purchase-groups/", self.group_payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.group_id = response.data["data"]["id"]
        self.line_id = response.data["data"]["progress"]["lines"][0]["id"]
        warehouse = Warehouse.objects.create(warehouse_number="GROUP-WH", warehouse_name="批次测试材料仓", warehouse_type="MATERIAL")
        self.zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name="材料区")

    def detail(self):
        response = self.client.get(f"/api/v1/purchase-groups/{self.group_id}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def batch_payload(self, quantity="120", batch_type="NORMAL", **kwargs):
        payload = {"request_id": str(uuid4()), "batch_type": batch_type, "currency_id": str(self.cny.pk), "lines": [{
            "purchase_group_line_id": self.line_id, "actual_purchase_quantity": quantity,
            "supplier_id": str(self.supplier.pk), "unit_price": "2",
            "delivery_date": (timezone.localdate() + timedelta(days=10)).isoformat(),
        }]}
        payload.update(kwargs)
        return payload

    def batch(self, quantity="120", batch_type="NORMAL", *, confirm=True):
        response = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/",
            self.batch_payload(quantity, batch_type), format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(response.status_code, 201, response.data)
        if confirm:
            response = self.client.post(f"/api/v1/purchase-orders/{response.data['data']['id']}/confirm/", {}, format="json")
            self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def receive(self, batch, quantity, *, returned="0", confirm=True, line_index=0, bar_count=None, return_bar_count=None):
        line = batch["lines"][line_index]
        current = self.client.get(f"/api/v1/purchase-orders/{batch['id']}/").data["data"]
        if current["status"] == "SUBMITTED":
            options = self.client.get(f"/api/v1/purchase-orders/{batch['id']}/sheet-options/")
            generated = self.client.post(f"/api/v1/purchase-orders/{batch['id']}/generate-sheets/", {"assignments": [{
                "supplier_id": str(self.supplier.pk), "template_version_id": options.data["data"]["templates"][0]["version_id"],
            }]}, format="json")
            self.assertEqual(generated.status_code, 201, generated.data)
            for sheet in generated.data["data"]:
                detail = self.client.get(f"/api/v1/supplier-purchase-sheets/{sheet['id']}/")
                published = self.client.post(f"/api/v1/supplier-purchase-sheets/{sheet['id']}/publish/", {},
                    format="json", HTTP_IF_MATCH=detail["ETag"])
                self.assertEqual(published.status_code, 200, published.data)
        eligible = self.client.get("/api/v1/material-inventory/eligible-lines/", {"purchase_order_id": batch["id"]})
        self.assertEqual(eligible.status_code, 200, eligible.data)
        matches = [row for row in eligible.data["data"] if str(row["id"]) == str(line["id"])]
        self.assertEqual(len(matches), 1, eligible.data)
        remaining = matches[0]["remaining_quantity"]
        response = self.client.post("/api/v1/material-inventory/receipts/", {"inbound_date": timezone.localdate().isoformat(), "items": [{
            "purchase_order_line_id": line["id"], "zone_id": str(self.zone.pk), "received_quantity": quantity,
            "expected_remaining_quantity": remaining,
            **({"received_bar_count": bar_count} if bar_count is not None else {}),
        }]}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        if confirm:
            data = response.data["data"]
            result = self.client.post(f"/api/v1/material-inventory/quality-batches/{data['id']}/confirm/", {"items": [{
                "line_id": row["id"], "expected_received_quantity": row["received_quantity"], "return_quantity": returned,
                "quality_remark": "批次检验",
                **({"return_bar_count": return_bar_count} if return_bar_count is not None else {}),
            } for row in data["lines"]]}, format="json")
            self.assertEqual(result.status_code, 200, result.data)
        return response

    def test_empty_group_and_idempotent_create_keep_snapshot(self):
        data = self.detail().data["data"]
        self.assertEqual(data["progress"]["status"], "PENDING")
        self.assertEqual(data["batches"], [])
        self.assertEqual(data["progress"]["lines"][0]["progress_percent"], "0.0000")
        repeated = self.client.post("/api/v1/purchase-groups/", self.group_payload, format="json")
        self.assertEqual(repeated.status_code, 201, repeated.data)
        self.assertEqual(repeated.data["data"]["id"], self.group_id)
        self.assertEqual(PurchaseGroup.objects.count(), 1)

    def test_both_batch_types_accept_over_suggestion_and_drafts_do_not_count(self):
        draft = self.batch("120", confirm=False)
        self.assertEqual(self.detail().data["data"]["progress"]["lines"][0]["purchased_quantity"], "0.0000")
        response = self.client.post(f"/api/v1/purchase-orders/{draft['id']}/confirm/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.batch("130", "SUPPLEMENT")
        line = self.detail().data["data"]["progress"]["lines"][0]
        self.assertEqual(line["purchased_quantity"], "250.0000")
        self.assertEqual(line["required_quantity"], "100.0000")
        self.assertEqual(line["accepted_quantity"], "0.0000")

    def test_partial_receipts_progress_80_100_120_and_parent_done_stays_open(self):
        batch = self.batch("120")
        for amount, percent, state in [("80", "80.0000", "PURCHASING"), ("20", "100.0000", "COMPLETED"), ("20", "120.0000", "COMPLETED")]:
            self.receive(batch, amount)
            progress = self.detail().data["data"]["progress"]
            self.assertEqual(progress["lines"][0]["progress_percent"], percent)
            self.assertEqual(progress["status"], state)
        extra = self.batch("10", "SUPPLEMENT")
        self.receive(extra, "10", returned="2")
        progress = self.detail().data["data"]["progress"]
        self.assertEqual(progress["lines"][0]["accepted_quantity"], "128.0000")
        record = PurchaseReturn.objects.get()
        for action in ["confirm", "complete"]:
            detail = self.client.get(f"/api/v1/purchase-returns/{record.pk}/")
            result = self.client.post(f"/api/v1/purchase-returns/{record.pk}/{action}/", {}, format="json", HTTP_IF_MATCH=detail["ETag"])
            self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(self.detail().data["data"]["progress"]["lines"][0]["accepted_quantity"], "128.0000")

    def test_pending_quality_is_excluded_and_manual_batch_close_does_not_complete_parent(self):
        batch = self.batch()
        receipt = self.receive(batch, "80", confirm=False)
        self.assertEqual(self.detail().data["data"]["progress"]["lines"][0]["accepted_quantity"], "0.0000")
        row = receipt.data["data"]["lines"][0]
        quality = self.client.post(f"/api/v1/material-inventory/quality-batches/{receipt.data['data']['id']}/confirm/",
            {"items": [{"line_id": row["id"], "expected_received_quantity": row["received_quantity"], "return_quantity": "0"}]}, format="json")
        self.assertEqual(quality.status_code, 200, quality.data)
        detail = self.client.get(f"/api/v1/purchase-orders/{batch['id']}/")
        closed = self.client.post(f"/api/v1/purchase-orders/{batch['id']}/complete/", {"remark": "本批关闭"}, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(closed.status_code, 200, closed.data)
        self.assertEqual(self.detail().data["data"]["progress"]["status"], "PURCHASING")

    def test_etag_idempotency_foreign_duplicate_and_invalid_quantities(self):
        url = f"/api/v1/purchase-groups/{self.group_id}/batches/"
        payload, etag = self.batch_payload(), self.detail()["ETag"]
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 428)
        self.assertEqual(self.client.post(url, payload, format="json", HTTP_IF_MATCH='"stale"').status_code, 412)
        created = self.client.post(url, payload, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(created.status_code, 201, created.data)
        retry = self.client.post(url, payload, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(created.data["data"]["id"], retry.data["data"]["id"])
        changed = deepcopy(payload)
        changed["lines"][0]["actual_purchase_quantity"] = "121"
        self.assertEqual(self.client.post(url, changed, format="json", HTTP_IF_MATCH=etag).status_code, 409)
        for change in ["foreign", "duplicate", "zero", "negative", "empty"]:
            data = self.batch_payload()
            if change == "foreign":
                data["lines"][0]["purchase_group_line_id"] = str(uuid4())
            elif change == "duplicate":
                data["lines"].append(deepcopy(data["lines"][0]))
            elif change == "empty":
                data["lines"] = []
            else:
                data["lines"][0]["actual_purchase_quantity"] = "0" if change == "zero" else "-1"
            self.assertEqual(self.client.post(url, data, format="json", HTTP_IF_MATCH=self.detail()["ETag"]).status_code, 400, change)
        self.assertEqual(PurchaseOrder.objects.count(), 1)

    def test_frozen_source_survives_bom_edits_and_subset_update(self):
        self.bom_line.budget_quantity = "999"
        self.bom_line.save(update_fields=["budget_quantity", "updated_at"])
        batch = self.batch("20", confirm=False)
        detail = self.client.get(f"/api/v1/purchase-orders/{batch['id']}/")
        row = batch["lines"][0]
        update = self.client.patch(f"/api/v1/purchase-orders/{batch['id']}/", {"lines": [{
            "id": row["id"], "supplier_id": str(self.supplier.pk), "delivery_date": row["delivery_date"],
            "actual_purchase_quantity": "130", "unit_price": "2",
        }]}, format="json", HTTP_IF_MATCH=detail["ETag"])
        self.assertEqual(update.status_code, 200, update.data)
        self.assertEqual(update.data["data"]["lines"][0]["required_quantity"], "100.0000")
        confirmed = self.client.post(f"/api/v1/purchase-orders/{batch['id']}/confirm/", {}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

    def test_source_scope_and_warehouse_read_does_not_grant_purchase_write(self):
        outsider = get_user_model().objects.create_user(username="group-outsider")
        Employee.objects.create(user=outsider, employee_code="GROUP-OUT", display_name="范围外采购")
        outsider.user_permissions.set(Permission.objects.filter(content_type__app_label="procurement"))
        client = APIClient()
        client.force_authenticate(outsider)
        self.assertEqual(client.get(f"/api/v1/purchase-groups/{self.group_id}/").status_code, 404)
        self.assertEqual(client.get("/api/v1/purchase-groups/").data["data"], [])
        self.assertEqual(client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", self.batch_payload(), format="json").status_code, 404)
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label="inventory", codename="receive_material"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", self.batch_payload(), format="json").status_code, 403)

    def test_session_requires_csrf_and_inactive_identity_is_rejected(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", self.batch_payload(), format="json")
        self.assertEqual(response.status_code, 403)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertIn(client.get(f"/api/v1/purchase-groups/{self.group_id}/").status_code, [401, 403])

    @override_settings(MODULE_ACCESS_ENABLED=True, ACCESS_MANAGEMENT_ENABLED=True)
    def test_module_role_grants_allow_existing_purchase_actions_and_deny_missing_action(self):
        self.user.user_permissions.clear()
        role = RoleProfile.objects.create(role_code="GROUP-PURCHASER", display_name="批次采购角色",
            auth_group=Group.objects.create(name="group-purchaser"))
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=role, effective_from=timezone.now())
        view = Permission.objects.get(content_type__app_label="procurement", codename="view_purchaseorder")
        RoleActionGrant.objects.create(role=role, permission=view, scope="MODULE")
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.detail().status_code, 200)
        blocked = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", self.batch_payload(),
            format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(blocked.status_code, 403, blocked.data)
        add = Permission.objects.get(content_type__app_label="procurement", codename="add_purchaseorder")
        RoleActionGrant.objects.create(role=role, permission=add, scope="MODULE")
        allowed = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", self.batch_payload(),
            format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(allowed.status_code, 201, allowed.data)
        self.assertFalse(get_user_model().objects.get(pk=self.user.pk).has_perm("procurement.add_purchaseorder"))

    def test_task_state_gate_and_invalid_type_are_preserved(self):
        invalid = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", self.batch_payload(batch_type="RETURN"),
            format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(invalid.status_code, 400)
        self.task.status = ProductionTaskStatus.COMPLETED
        self.task.save(update_fields=["status"])
        blocked = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", self.batch_payload(),
            format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(blocked.status_code, 409, blocked.data)

    def test_deleted_new_batch_keeps_idempotency_and_never_reuses_batch_number(self):
        payload = self.batch_payload()
        url = f"/api/v1/purchase-groups/{self.group_id}/batches/"
        created = self.client.post(url, payload, format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(created.status_code, 201, created.data)
        batch_id = created.data["data"]["id"]
        deleted = self.client.delete(f"/api/v1/purchase-orders/{batch_id}/", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(deleted.status_code, 204, deleted.data)
        self.assertIsNotNone(PurchaseOrder.objects.get(pk=batch_id).archived_at)
        self.assertEqual(self.detail().data["data"]["batches"], [])
        repeated = self.client.post(url, payload, format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(repeated.status_code, 409, repeated.data)
        self.assertEqual(self.batch(confirm=False)["batch_number"], 2)

    def test_deleting_legacy_first_batch_refreshes_group_etag_and_preserves_source(self):
        task = self.make_task("LEGACY-DELETE")
        product = self.make_product_line(task)
        bom, bom_line = self.make_bom(product, section_type=BomSectionType.ACCESSORY, budget_quantity="100")
        source = self.get_source(task, bom).data["data"]
        payload = order_tests.PurchaseOrderApiTests.create_payload(task, source, actual_purchase_quantity="20")
        created = self.client.post("/api/v1/purchase-orders/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.group_id = str(created.data["data"]["purchase_group_id"])
        before = self.detail()
        self.line_id = before.data["data"]["progress"]["lines"][0]["id"]
        deleted = self.client.delete(f"/api/v1/purchase-orders/{created.data['data']['id']}/")
        self.assertEqual(deleted.status_code, 204, deleted.data)
        after = self.detail()
        self.assertNotEqual(before["ETag"], after["ETag"])
        self.assertEqual(after.data["data"]["batches"], [])
        self.assertEqual(after.data["data"]["progress"]["lines"], before.data["data"]["progress"]["lines"])
        stale = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", self.batch_payload(),
            format="json", HTTP_IF_MATCH=before["ETag"])
        self.assertEqual(stale.status_code, 412, stale.data)
        reopened = self.get_source(task, bom).data["data"]
        self.assertTrue(reopened["can_create"], reopened)
        recreated = self.client.post("/api/v1/purchase-orders/", payload, format="json")
        self.assertEqual(recreated.status_code, 201, recreated.data)
        self.assertEqual(str(recreated.data["data"]["purchase_group_id"]), self.group_id)
        self.assertEqual(PurchaseGroup.objects.filter(production_task=task).count(), 1)
        self.assertFalse(self.get_source(task, bom).data["data"]["can_create"])
        repeated = self.client.post("/api/v1/purchase-orders/", payload, format="json")
        self.assertEqual(repeated.status_code, 409, repeated.data)
        deleted_again = self.client.delete(f"/api/v1/purchase-orders/{recreated.data['data']['id']}/")
        self.assertEqual(deleted_again.status_code, 204, deleted_again.data)
        bom_line.budget_quantity = "200"
        bom_line.save(update_fields=["budget_quantity", "updated_at"])
        changed = self.get_source(task, bom).data["data"]
        self.assertFalse(changed["can_create"], changed)
        self.assertIn("PURCHASE_GROUP_EXISTS", [row["code"] for row in changed["blockers"]])
        refused = self.client.post("/api/v1/purchase-orders/", payload, format="json")
        self.assertEqual(refused.status_code, 409, refused.data)
        self.assertEqual(self.detail().data["data"]["progress"]["lines"], before.data["data"]["progress"]["lines"])
        self.batch("30")

    def test_legacy_complete_entry_reuses_empty_group(self):
        source = self.get_source(self.task, self.bom).data["data"]
        self.assertTrue(source["can_create"], source)
        payload = order_tests.PurchaseOrderApiTests.create_payload(self.task, source, actual_purchase_quantity="20")
        response = self.client.post("/api/v1/purchase-orders/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(str(response.data["data"]["purchase_group_id"]), self.group_id)
        self.assertEqual(PurchaseGroup.objects.filter(production_task=self.task).count(), 1)

    def test_contract_and_cost_are_bound_to_batches_only(self):
        batches = [self.batch("40"), self.batch("80", "SUPPLEMENT")]
        for batch in batches:
            options = self.client.get(f"/api/v1/purchase-orders/{batch['id']}/sheet-options/")
            response = self.client.post(f"/api/v1/purchase-orders/{batch['id']}/generate-sheets/", {"assignments": [{
                "supplier_id": str(self.supplier.pk), "template_version_id": options.data["data"]["templates"][0]["version_id"],
            }]}, format="json")
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(str(response.data["data"][0]["purchase_order_id"]), batch["id"])
        costs = task_cost_summary(task=self.task)
        purchase = next(item for item in costs["categories"] if item["key"] == "purchase")
        self.assertEqual(purchase["amount"], "240.00")
        self.assertEqual(purchase["count"], 2)
    def use_another_group(self, *, quantity="100", second_line=False):
        task = self.make_task("ANOTHER")
        product = self.make_product_line(task)
        bom, line = self.make_bom(product, section_type=BomSectionType.ACCESSORY, budget_quantity=quantity)
        if second_line:
            BomLine.objects.create(section=line.section, line_number=2, category="五金件", material="铁",
                part_name="第二项材料", unit="PCS", budget_quantity="100", raw_values=deepcopy(line.raw_values))
        source = self.get_source(task, bom).data["data"]
        response = self.client.post("/api/v1/purchase-groups/", {"production_task_id": str(task.pk),
            "bom_id": str(bom.pk), "source_revision": source["source_revision"]}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.group_id = response.data["data"]["id"]
        self.line_id = response.data["data"]["progress"]["lines"][0]["id"]
        return response.data["data"]

    def test_partial_materials_do_not_offset_other_material_shortage(self):
        group = self.use_another_group(second_line=True)
        first = self.batch("120")
        self.receive(first, "120")
        progress = self.detail().data["data"]["progress"]
        self.assertEqual(progress["status"], "PURCHASING")
        self.assertEqual(progress["satisfied_line_count"], 1)
        self.assertEqual(progress["lines"][1]["accepted_quantity"], "0.0000")
        self.line_id = group["progress"]["lines"][1]["id"]
        second = self.batch("100")
        self.receive(second, "80")
        progress = self.detail().data["data"]["progress"]
        self.assertEqual([row["progress_percent"] for row in progress["lines"]], ["120.0000", "80.0000"])
        self.assertEqual(progress["status"], "PURCHASING")
        self.receive(second, "20")
        self.assertEqual(self.detail().data["data"]["progress"]["status"], "COMPLETED")

    def test_percentage_rounding_cannot_finish_a_short_material(self):
        self.use_another_group(quantity="1000000")
        batch = self.batch("1000000")
        self.receive(batch, "999999.9999")
        progress = self.detail().data["data"]["progress"]
        self.assertEqual(progress["lines"][0]["progress_percent"], "100.0000")
        self.assertFalse(progress["lines"][0]["is_satisfied"])
        self.assertEqual(progress["status"], "PURCHASING")

    def test_pipe_batch_uses_frozen_root_meter_snapshot_and_net_good_meters(self):
        root, _ = ProductionUnit.objects.get_or_create(unit_name="根", defaults={"unit_code": "GROUP-ROOT"})
        self.inventory_material.unit = root
        self.inventory_material.category = ProductCategory.objects.get(category_name="管材", item_type="MATERIAL")
        self.inventory_material.save(update_fields=["unit", "category"])
        task = self.make_task("PIPE-GROUP")
        product = self.make_product_line(task)
        plan = pipe_plan(cutting_length_mm=500, pieces_per_product=2, pieces_per_bar=6, order_quantity=10)
        bom, bom_line = self.make_bom(product, unit="根", **{key: plan[key] for key in (
            "cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m", "suggested_bar_count", "suggested_purchase_meters",
        )})
        source = self.get_source(task, bom).data["data"]
        created = self.client.post("/api/v1/purchase-groups/", {"production_task_id": str(task.pk), "bom_id": str(bom.pk),
            "source_revision": source["source_revision"]}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.group_id = created.data["data"]["id"]
        self.line_id = created.data["data"]["progress"]["lines"][0]["id"]
        bom_line.cutting_length_mm = Decimal("900")
        bom_line.save(update_fields=["cutting_length_mm"])
        payload = self.batch_payload(quantity=None)
        payload["lines"][0]["actual_bar_count"] = 5
        batch = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", payload,
            format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(batch.status_code, 201, batch.data)
        row = batch.data["data"]["lines"][0]
        self.assertEqual((row["required_quantity"], row["actual_purchase_quantity"], row["source_unit_text"]), ("12.2000", "15.2500", "米"))
        confirmed = self.client.post(f"/api/v1/purchase-orders/{batch.data['data']['id']}/confirm/", {}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.receive(confirmed.data["data"], "15.25", bar_count=5, return_bar_count=1)
        progress = self.detail().data["data"]["progress"]
        self.assertEqual(progress["lines"][0]["purchased_quantity"], "15.2500")
        self.assertEqual(progress["lines"][0]["accepted_quantity"], "12.2000")
        self.assertEqual(progress["status"], "COMPLETED")
        self.assertEqual(PurchaseReturn.objects.get().lines.get().quantity, Decimal("3.05"))
