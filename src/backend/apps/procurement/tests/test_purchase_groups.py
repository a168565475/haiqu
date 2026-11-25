from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
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

from ..models import PurchaseContractTemplate, PurchaseContractTemplateStatus, PurchaseGroup, PurchaseOrder, PurchaseReturn, Supplier, SupplierPurchaseSheet
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
        source_response = self.get_source(self.task)
        self.assertEqual(source_response.status_code, 200, source_response.data)
        source = source_response.data["data"]
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

    def test_external_supply_reconfirmation_keeps_confirmed_batches_and_skips_new_purchase(self):
        from apps.procurement.external_supply import sync_external_supply
        from apps.procurement.tracking_selectors import coverage_rows
        from apps.procurement.services import _bom_source_details
        confirmed = self.batch("40")
        draft = self.batch("20", confirm=False)
        self.bom_line.raw_values["purchase_required"] = False
        self.bom_line.save()
        sync_external_supply(self.bom, [self.bom_line], actor_employee=self.employee, request=None)
        self.assertEqual(_bom_source_details(self.product_line, self.bom)[1], [])
        progress = self.detail().data["data"]["progress"]
        self.assertEqual(progress["lines"], [])
        self.assertEqual(progress["external_supply_line_ids"], [self.line_id])
        self.assertEqual(coverage_rows(task_ids=[self.task.pk]), [])
        self.assertEqual(PurchaseOrder.objects.get(pk=confirmed["id"]).lines.get().actual_purchase_quantity, 40)
        self.assertFalse(PurchaseOrder.objects.get(pk=draft["id"]).lines.exists())
        response = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", self.batch_payload(),
                                    format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("外供", str(response.data))
        self.bom_line.raw_values["purchase_required"] = True
        self.bom_line.save()
        sync_external_supply(self.bom, [self.bom_line], actor_employee=self.employee, request=None)
        self.assertEqual(self.detail().data["data"]["progress"]["external_supply_line_ids"], [])
        progress = self.detail().data["data"]["progress"]["lines"]
        self.assertEqual([row["purchased_quantity"] for row in progress], ["40.0000"])

    def test_copied_revision_matches_only_same_product_component_and_can_restore_purchase(self):
        from apps.procurement.external_supply import sync_external_supply
        revision, line = self.make_bom(self.product_line, version=2, section_type=BomSectionType.ACCESSORY,
                                       budget_quantity="100")
        line.component_identity = self.bom_line.component_identity
        line.raw_values["purchase_required"] = False
        line.save()
        other = BomLine.objects.create(section=line.section, line_number=2, part_name=line.part_name,
                                       raw_values={"purchase_required": False})
        confirmed = self.batch("40")
        draft = self.batch("10", confirm=False)
        sync_external_supply(revision, [other], actor_employee=self.employee, request=None)
        self.assertEqual(len(self.detail().data["data"]["progress"]["lines"]), 1)
        sync_external_supply(revision, [line, other], actor_employee=self.employee, request=None)
        self.assertEqual(self.detail().data["data"]["progress"]["status"], "COMPLETED")
        self.assertFalse(PurchaseOrder.objects.get(pk=draft["id"]).lines.exists())
        self.assertEqual(PurchaseOrder.objects.get(pk=confirmed["id"]).lines.get().bom_line_id, self.bom_line.pk)
        line.raw_values["purchase_required"] = True
        line.save()
        sync_external_supply(revision, [line], actor_employee=self.employee, request=None)
        self.assertEqual(self.detail().data["data"]["progress"]["lines"][0]["purchased_quantity"], "40.0000")

    def test_external_set_anchor_releases_member_and_preserves_other_draft_price(self):
        from apps.procurement.external_supply import sync_external_supply

        child = self.extra_set_component("左件")
        ordinary = self.extra_set_component("单独采购")
        payload = self.batch_payload("9")
        anchor = payload["lines"][0]
        payload["lines"].append({**anchor, "purchase_group_line_id": ordinary})
        anchor.update(unit_price=None, set_pricing={"anchor_id": self.line_id, "quantity": 3, "unit_price": "5"})
        payload["lines"].append({**anchor, "purchase_group_line_id": child})
        response = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", payload,
                                    format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(response.status_code, 201, response.data)
        draft = PurchaseOrder.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(draft.total_amount, Decimal("33"))
        self.bom_line.raw_values["purchase_required"] = False
        self.bom_line.save()
        sync_external_supply(self.bom, [self.bom_line], actor_employee=self.employee, request=None)
        draft.refresh_from_db()
        self.assertIsNone(draft.total_amount)
        self.assertEqual(draft.lines.count(), 2)
        self.assertEqual(draft.lines.get(purchase_group_line_id=ordinary).amount, Decimal("18"))
        remaining = draft.lines.get(purchase_group_line_id=child)
        self.assertNotIn("set_pricing", remaining.calculation_snapshot)
        self.assertEqual(remaining.calculation_snapshot["set_pricing_review"], "外供调整")
        self.assertIsNone(remaining.unit_price)
        self.assertEqual(remaining.supplier_id, self.supplier.pk)

    def test_manual_completion_keeps_record_while_supplement_excludes_external_material(self):
        from apps.procurement.external_supply import sync_external_supply

        last_completed = timezone.now()
        PurchaseGroup.objects.filter(pk=self.group_id).update(manual_completed_at=last_completed,
            manual_completed_by_employee=self.employee, manual_completion_remark="原人工完成")
        self.bom_line.raw_values["purchase_required"] = False
        self.bom_line.save()
        sync_external_supply(self.bom, [self.bom_line], actor_employee=self.employee, request=None)
        group = PurchaseGroup.objects.get(pk=self.group_id)
        self.assertEqual(group.manual_completed_at, last_completed)
        self.assertEqual(group.manual_completion_remark, "原人工完成")
        self.assertEqual(self.detail().data["data"]["progress"]["external_supply_line_ids"], [self.line_id])

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

    def extra_set_component(self, name, *, tape=False):
        from apps.material_catalog.models import MaterialAllowedUnit, MaterialAttributeValue, MaterialCatalog
        from apps.material_catalog.snapshots import build_material_snapshot
        from ..group_services import save_bom_group_line
        from ..services import _source_line

        if tape:
            catalog = MaterialCatalog.objects.create(category_key="AUXILIARY", template_key="TAPE", name=name)
            unit, _ = ProductionUnit.objects.get_or_create(unit_name="米", catalog_owner=None, defaults={"unit_code": "QA-M"})
            MaterialAllowedUnit.objects.create(catalog=catalog, scope="BASE", unit=unit)
            MaterialAttributeValue.objects.create(catalog=catalog, scope="BASE", field_key="width", value="20")
            selected = build_material_snapshot(catalog=catalog, scope="BASE", processing_state="RAW",
                attributes={"width": "20"}, unit_id=unit.pk, required_fields=["width"])
            section = self.bom.sections.create(line_number=2, section_type=BomSectionType.FABRIC, title="辅料类")
            line = section.lines.create(line_number=1, part_name=name, material_catalog=catalog,
                material_selection_snapshot=selected, unit="米", total_purchase_quantity="1600")
        else:
            line = BomLine.objects.get(pk=self.bom_line.pk)
            line.pk = uuid4()
            line.part_name = name
            line.line_number = line.section.lines.count() + 1
            line.save(force_insert=True)
        group = PurchaseGroup.objects.get(pk=self.group_id)
        source = _source_line(self.bom, line.section, line, self.product_line)
        save_bom_group_line(group, group.lines.count() + 1, source)
        return str(group.lines.get(source_bom_line_id_snapshot=line.pk).pk)

    def test_submit_supplier_batch_confirms_only_its_rows_and_reuses_the_request(self):
        partial_id = self.extra_set_component("分批买")
        other_id = self.extra_set_component("另一供应商")
        payload = self.batch_payload("100")
        payload["lines"].append({**payload["lines"][0], "purchase_group_line_id": partial_id, "actual_purchase_quantity": "60"})
        url = f"/api/v1/purchase-groups/{self.group_id}/submit-supplier-batch/"
        original_etag = self.detail()["ETag"]

        response = self.client.post(url, payload, format="json", HTTP_IF_MATCH=original_etag)
        self.assertEqual(response.status_code, 201, response.data)
        result = response.data["data"]
        order = PurchaseOrder.objects.get(pk=result["order_id"])
        self.assertEqual(order.status, "SUBMITTED")
        self.assertEqual(set(map(str, order.lines.values_list("purchase_group_line_id", flat=True))), {self.line_id, partial_id})
        sheet = SupplierPurchaseSheet.objects.get(purchase_order=order)
        self.assertEqual(sheet.status, "DRAFT")
        self.assertEqual(sheet.supplier_id, self.supplier.pk)
        rows = {row["id"]: row["remaining_purchase_quantity"] for row in result["group"]["progress"]["lines"]}
        self.assertEqual(rows, {self.line_id: "0.0000", partial_id: "40.0000", other_id: "100.0000"})
        self.assertEqual(response["ETag"], self.detail()["ETag"])

        retry = self.client.post(url, payload, format="json", HTTP_IF_MATCH=original_etag)
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(retry.data["data"]["order_id"], result["order_id"])
        self.assertEqual(SupplierPurchaseSheet.objects.filter(purchase_order=order).count(), 1)
        self.assertEqual(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).count(), 1)

    def test_supplier_submissions_share_the_page_batch_and_group_sheets_include_all_batches(self):
        legacy = self.batch("10")
        other_line = self.extra_set_component("同批的另一家供应商")
        another_supplier = Supplier.objects.create(
            supplier_number="GYS90003", supplier_name="同批供应商", supplier_type="MATERIAL",
            supplier_categories=["TUBE"], payment_cycle="MONTHLY", phone="13800000003",
        )
        group_url = f"/api/v1/purchase-groups/{self.group_id}/"
        submit_url = f"{group_url}submit-supplier-batch/"
        session = str(uuid4())
        fresh_page = self.client.get(group_url, {"batch_session_id": session})
        self.assertEqual(fresh_page.status_code, 200, fresh_page.data)
        self.assertEqual(fresh_page.data["data"]["batch_page"], {
            "current_batch_number": None, "next_batch_number": 2, "submitted_line_ids": [],
        })
        self.assertEqual(fresh_page["ETag"], self.detail()["ETag"])
        self.assertEqual(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).count(), 1)
        self.assertEqual(self.client.get(group_url, {"batch_session_id": "invalid"}).status_code, 400)

        first = self.client.post(submit_url, self.batch_payload("90", batch_session_id=session),
                                 format="json", HTTP_IF_MATCH=fresh_page["ETag"])
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["data"]["batch_number"], 2)
        refreshed = self.client.get(group_url, {"batch_session_id": session})
        self.assertEqual(refreshed.data["data"]["batch_page"], {
            "current_batch_number": 2, "next_batch_number": 3, "submitted_line_ids": [self.line_id],
        })

        new_session = str(uuid4())
        new_page = self.client.get(group_url, {"batch_session_id": new_session})
        self.assertEqual(new_page.data["data"]["batch_page"], {
            "current_batch_number": None, "next_batch_number": 3, "submitted_line_ids": [],
        })
        new_purchase = self.batch_payload("20", batch_session_id=new_session)
        new_purchase["lines"][0]["purchase_group_line_id"] = other_line
        third_batch = self.client.post(submit_url, new_purchase, format="json", HTTP_IF_MATCH=new_page["ETag"])
        self.assertEqual(third_batch.status_code, 201, third_batch.data)
        self.assertEqual(third_batch.data["data"]["batch_number"], 3)

        second_purchase = self.batch_payload("80", batch_session_id=session)
        second_purchase["lines"][0].update(purchase_group_line_id=other_line, supplier_id=str(another_supplier.pk))
        second = self.client.post(submit_url, second_purchase, format="json", HTTP_IF_MATCH=third_batch["ETag"])
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data["data"]["batch_number"], 2)
        self.assertNotEqual(first.data["data"]["order_id"], second.data["data"]["order_id"])
        self.assertEqual(PurchaseOrder.objects.get(pk=legacy["id"]).batch_number, 1)

        group_id = self.group_id
        self.use_another_group()
        unrelated = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/submit-supplier-batch/",
                                     self.batch_payload("10", batch_session_id=session),
                                     format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(unrelated.status_code, 201, unrelated.data)
        sheets_url = "/api/v1/supplier-purchase-sheets/"
        sheets = self.client.get(sheets_url, {"purchase_group_id": group_id})
        self.assertEqual(sheets.status_code, 200, sheets.data)
        self.assertCountEqual(
            [(row["purchase_order_id"], row["purchase_batch_number"]) for row in sheets.json()["data"]],
            [(str(result.data["data"]["order_id"]), number) for result, number in [(first, 2), (second, 2), (third_batch, 3)]],
        )
        self.assertEqual(self.client.get(sheets_url, {"purchase_group_id": "invalid"}).status_code, 400)


    @override_settings(PURCHASE_TRACKING_ENABLED=True)
    def test_supplier_submit_wakes_tracking_once_and_retry_does_not_wake_it_again(self):
        payload = self.batch_payload("20")
        url = f"/api/v1/purchase-groups/{self.group_id}/submit-supplier-batch/"
        etag = self.detail()["ETag"]
        wakeups = []

        def record_wakeup(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if sql == "SELECT pg_notify(%s, %s)":
                wakeups.append(params)
            return result

        with connection.execute_wrapper(record_wakeup), self.captureOnCommitCallbacks(execute=False) as callbacks:
            first = self.client.post(url, payload, format="json", HTTP_IF_MATCH=etag)
            self.assertEqual(first.status_code, 201, first.data)
            retry = self.client.post(url, payload, format="json", HTTP_IF_MATCH=etag)
            self.assertEqual(retry.status_code, 200, retry.data)

        self.assertEqual(wakeups, [["procurement_supplier_tracking", str(self.task.pk)]])
        self.assertEqual(callbacks, [])
        self.assertTrue(SupplierPurchaseSheet.objects.filter(purchase_order_id=first.data["data"]["order_id"], status="DRAFT").exists())

        with self.captureOnCommitCallbacks(execute=False) as regular_callbacks:
            self.batch("10", confirm=False)
        self.assertGreater(len(regular_callbacks), 0)


    def test_saved_supplier_orders_confirm_together_and_preserve_drafts_on_failure(self):
        other_line = self.extra_set_component("第二家供应商材料")
        additional_line = self.extra_set_component("确认时一同带入")
        other_supplier = Supplier.objects.create(
            supplier_number="GYS90003", supplier_name="待确认供应商", supplier_type="MATERIAL",
            supplier_categories=["TUBE"], payment_cycle="MONTHLY", phone="13800000003",
        )
        session = str(uuid4())
        group_url = f"/api/v1/purchase-groups/{self.group_id}/"
        submit_url = f"{group_url}submit-supplier-batch/"
        confirm_url = f"{group_url}confirm-batch-page/"
        first_payload = self.batch_payload("100", batch_session_id=session, save_as_draft=True)
        second_payload = self.batch_payload("60", batch_session_id=session, save_as_draft=True)
        second_payload["lines"][0].update(purchase_group_line_id=other_line, supplier_id=str(other_supplier.pk))
        additional = self.batch_payload("20")
        additional["lines"][0]["purchase_group_line_id"] = additional_line
        first = self.client.post(submit_url, first_payload, format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client.post(submit_url, second_payload, format="json", HTTP_IF_MATCH=first["ETag"])
        self.assertEqual(second.status_code, 201, second.data)

        refreshed = self.client.get(group_url, {"batch_session_id": session})
        page = refreshed.json()["data"]["batch_page"]
        self.assertEqual(page["current_batch_number"], 1)
        self.assertCountEqual(page["submitted_line_ids"], [self.line_id, other_line])
        self.assertCountEqual([row["suppliers"][0] for row in page["draft_orders"]],
                              [self.supplier.supplier_name, other_supplier.supplier_name])
        self.assertEqual(len(page["draft_orders"]), 2)
        self.assertEqual(set(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).values_list("status", flat=True)), {"DRAFT"})
        self.assertFalse(SupplierPurchaseSheet.objects.exists())
        remaining = {line["id"]: (line["remaining_purchase_quantity"], line["purchased_quantity"])
                     for line in refreshed.json()["data"]["progress"]["lines"]}
        self.assertEqual(remaining[self.line_id], ("0.0000", "0.0000"))
        self.assertEqual(remaining[other_line], ("40.0000", "0.0000"))

        payload = {"batch_session_id": session, "additional": additional}
        etag = refreshed["ETag"]
        self.assertEqual(self.client.post(confirm_url, payload, format="json").status_code, 428)
        active = list(PurchaseContractTemplate.objects.filter(status=PurchaseContractTemplateStatus.ACTIVE).values_list("pk", flat=True))
        PurchaseContractTemplate.objects.filter(pk__in=active).update(status=PurchaseContractTemplateStatus.INACTIVE)
        failed = self.client.post(confirm_url, payload, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(failed.status_code, 400, failed.data)
        self.assertEqual(PurchaseOrder.objects.filter(purchase_group_id=self.group_id, status="DRAFT").count(), 2)
        self.assertFalse(SupplierPurchaseSheet.objects.exists())
        self.assertEqual(self.detail()["ETag"], etag)
        PurchaseContractTemplate.objects.filter(pk__in=active).update(status=PurchaseContractTemplateStatus.ACTIVE)

        result = self.client.post(confirm_url, payload, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(result.status_code, 200, result.data)
        replay = self.client.post(confirm_url, payload, format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(PurchaseOrder.objects.filter(purchase_group_id=self.group_id, status="SUBMITTED", batch_number=1).count(), 3)
        self.assertEqual(SupplierPurchaseSheet.objects.filter(status="DRAFT").count(), 3)
        self.assertNotIn("draft_orders", result.json()["data"]["batch_page"])


    def test_submit_supplier_batch_requires_existing_permissions_and_valid_rows(self):
        child_id = self.extra_set_component("第二条材料")
        url = f"/api/v1/purchase-groups/{self.group_id}/submit-supplier-batch/"
        payload = self.batch_payload("20")
        etag = self.detail()["ETag"]
        for field, invalid in [("supplier_id", str(self.disabled_supplier.pk)), ("delivery_date", None), ("unit_price", "0"), ("actual_purchase_quantity", "0")]:
            invalid_payload = deepcopy(payload)
            invalid_payload["lines"].append({**payload["lines"][0], "purchase_group_line_id": child_id, field: invalid})
            result = self.client.post(url, invalid_payload, format="json", HTTP_IF_MATCH=etag)
            self.assertEqual(result.status_code, 400, result.data)
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 428)
        self.user.user_permissions.remove(Permission.objects.get(codename="submit_purchaseorder"))
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(url, payload, format="json", HTTP_IF_MATCH=etag).status_code, 403)
        self.assertFalse(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).exists())

    def test_submit_supplier_batch_rolls_back_when_no_contract_template(self):
        PurchaseContractTemplate.objects.update(status=PurchaseContractTemplateStatus.INACTIVE)
        url = f"/api/v1/purchase-groups/{self.group_id}/submit-supplier-batch/"
        etag = self.detail()["ETag"]
        response = self.client.post(url, self.batch_payload("20"), format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).exists())
        self.assertEqual(self.detail()["ETag"], etag)

    def test_set_pricing_manual_set_count_separate_receipts_and_sheet(self):
        child = self.extra_set_component("套餐织带", tape=True)
        skipped = self.extra_set_component("本批不采购")
        skipped_quantity = self.extra_set_component("本批零数量")
        payload = self.batch_payload("3200")
        anchor = payload["lines"][0]
        anchor.update(unit_price=None, set_pricing={"anchor_id": self.line_id, "quantity": 1600, "unit_price": "5"})
        payload["lines"].extend([
            {**anchor, "purchase_group_line_id": child, "actual_purchase_quantity": "1600"},
            {**anchor, "purchase_group_line_id": skipped, "unit_price": "0", "set_pricing": None},
            {**anchor, "purchase_group_line_id": skipped_quantity, "actual_purchase_quantity": "0",
             "unit_price": "7", "set_pricing": None},
        ])
        response = self.client.post(f"/api/v1/purchase-groups/{self.group_id}/batches/", payload,
                                    format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(response.status_code, 201, response.data)
        batch = response.data["data"]
        self.assertEqual(batch["total_amount"], "8000.0000")
        self.assertEqual([(r["actual_purchase_quantity"], r["unit_price"], r["amount"]) for r in batch["lines"]],
                         [("3200.0000", None, "8000.0000"), ("1600.0000", None, "0.0000")])
        url = f"/api/v1/purchase-orders/{batch['id']}/"
        update = self.client.patch(url, {"lines": [{
            "id": row["id"], "supplier_id": row["supplier_id"], "delivery_date": row["delivery_date"],
            "actual_purchase_quantity": row["actual_purchase_quantity"], "unit_price": None,
            "set_pricing": {**row["set_pricing"], "quantity": 1400},
        } for row in batch["lines"]]}, format="json", HTTP_IF_MATCH=self.client.get(url)["ETag"])
        self.assertEqual(update.status_code, 200, update.data)
        self.assertEqual(update.data["data"]["total_amount"], "7000.0000")
        confirmed = self.client.post(url + "confirm/", {}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        options = self.client.get(url + "sheet-options/").data["data"]["templates"]
        sheets = self.client.post(url + "generate-sheets/", {"assignments": [{
            "supplier_id": str(self.supplier.pk), "template_version_id": options[0]["version_id"],
        }]}, format="json")
        self.assertEqual(sheets.status_code, 201, sheets.data)
        sheet_url = f"/api/v1/supplier-purchase-sheets/{sheets.data['data'][0]['id']}/"
        sheet = self.client.get(sheet_url)
        content = sheet.data["data"]["content_snapshot"]
        first, second = content["lines"]
        self.assertEqual((first["quantity"], first["unit"], first["physical_quantity"]), ("1400", "套", "3200.0000"))
        self.assertEqual((second["physical_quantity"], second["unit_price"]), ("1600.0000", ""))
        self.assertEqual((first["physical_unit"], second["physical_unit"], second["unit"]), ("PCS", "米", "米"))
        published = self.client.post(sheet_url + "publish/", {}, format="json", HTTP_IF_MATCH=sheet["ETag"])
        self.assertEqual(published.status_code, 200, published.data)
        self.assertEqual(published.data["data"]["total_amount"], "7000.0000")
        receipt = self.receive(confirmed.data["data"], "1600", line_index=1)
        inbound_line = receipt.data["data"]["lines"][0]
        self.assertEqual(inbound_line["source_unit_text_snapshot"], "米")
        self.assertIn("material_catalog_id", inbound_line["calculation_snapshot"])
        self.assertNotIn("set_pricing", inbound_line["calculation_snapshot"])

    def test_set_pricing_rejects_unmatched_anchor_and_mixed_delivery(self):
        child = self.extra_set_component("套餐右件")
        payload = self.batch_payload()
        a = payload["lines"][0]
        a.update(unit_price=None, set_pricing={"anchor_id": self.line_id, "quantity": 2, "unit_price": "3"})
        url = f"/api/v1/purchase-groups/{self.group_id}/batches/"
        for row in [None, {**a, "purchase_group_line_id": child, "delivery_date": None},
                    {**a, "purchase_group_line_id": child, "set_pricing": {**a["set_pricing"], "anchor_id": str(uuid4())}}]:
            payload["lines"] = [a, row] if row else [a]
            response = self.client.post(url, payload, format="json", HTTP_IF_MATCH=self.detail()["ETag"])
            self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(PurchaseOrder.objects.filter(purchase_group_id=self.group_id).exists())

    def test_batch_review_metadata_does_not_relax_source_identity_check(self):
        draft = self.batch("20", confirm=False)
        line = PurchaseOrder.objects.get(pk=draft["id"]).lines.get()
        snapshot = {**line.calculation_snapshot, "set_pricing_review": "外供调整"}
        line.calculation_snapshot = {**snapshot, "raw_material_id": str(uuid4())}
        line.save(update_fields=["calculation_snapshot"])
        url = f"/api/v1/purchase-orders/{draft['id']}/confirm/"
        rejected = self.client.post(url, {}, format="json")
        self.assertEqual(rejected.status_code, 409, rejected.data)
        line.calculation_snapshot = snapshot
        line.save(update_fields=["calculation_snapshot"])
        confirmed = self.client.post(url, {}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

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

    def test_draft_batch_skips_unpurchased_line_and_releases_its_quantity(self):
        child = self.extra_set_component("后续再买")
        payload = self.batch_payload("12")
        payload["lines"].append({"purchase_group_line_id": child, "actual_purchase_quantity": "6"})
        batches_url = f"/api/v1/purchase-groups/{self.group_id}/batches/"
        response = self.client.post(batches_url, payload, format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(response.status_code, 201, response.data)
        batch = response.data["data"]
        url = f"/api/v1/purchase-orders/{batch['id']}/"
        active, skipped = batch["lines"]
        active_input = {"id": active["id"], "actual_purchase_quantity": "12", "supplier_id": active["supplier_id"],
                        "delivery_date": active["delivery_date"], "unit_price": "2"}
        etag = self.client.get(url)["ETag"]
        for invalid_ids in ([str(uuid4())], [active["id"], skipped["id"]]):
            invalid = self.client.patch(url, {"lines": [active_input], "skipped_line_ids": invalid_ids},
                                        format="json", HTTP_IF_MATCH=etag)
            self.assertEqual(invalid.status_code, 400, invalid.data)
        updated = self.client.patch(url, {"lines": [active_input], "skipped_line_ids": [skipped["id"]]},
                                    format="json", HTTP_IF_MATCH=etag)
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual([line["id"] for line in updated.data["data"]["lines"]], [active["id"]])
        self.assertEqual(updated.data["data"]["total_amount"], "24.0000")
        confirmed = self.client.post(url + "confirm/", {}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        blocked = self.client.patch(url, {"lines": [active_input], "skipped_line_ids": [skipped["id"]]},
                                    format="json", HTTP_IF_MATCH=self.client.get(url)["ETag"])
        self.assertEqual(blocked.status_code, 409, blocked.data)
        next_payload = self.batch_payload("6")
        next_payload["lines"][0]["purchase_group_line_id"] = child
        next_batch = self.client.post(batches_url, next_payload, format="json", HTTP_IF_MATCH=self.detail()["ETag"])
        self.assertEqual(next_batch.status_code, 201, next_batch.data)

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
        original, = before.data["data"]["progress"]["lines"]
        self.assertEqual((original["planned_purchase_quantity"], original["remaining_purchase_quantity"]),
                         ("20.0000", "80.0000"))
        self.assertEqual(after.data["data"]["progress"]["lines"], [
            {**original, "planned_purchase_quantity": "0.0000", "remaining_purchase_quantity": "100.0000"},
        ])
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
        self.assertEqual(self.detail().data["data"]["progress"]["lines"], after.data["data"]["progress"]["lines"])
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
