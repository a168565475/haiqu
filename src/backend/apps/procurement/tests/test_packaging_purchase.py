from datetime import timedelta
from uuid import uuid4

from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.access_control.models import RoleActionGrant
from apps.boms.models import BomLine, BomSection, BomSectionType
from apps.organizations.models import EmployeeRoleAssignment, RoleProfile

from ..models import PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus, Supplier, SupplierCategory, SupplierPurchaseSheet
from . import test_purchase_order_api as fixtures


PACKAGING = "/api/v1/packaging-purchase-groups/"


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True)
class PackagingPurchaseTests(APITestCase):
    make_task = fixtures.PurchaseOrderApiTests.make_task
    make_product_line = fixtures.PurchaseOrderApiTests.make_product_line
    make_bom = fixtures.PurchaseOrderApiTests.make_bom
    get_source = fixtures.PurchaseOrderApiTests.get_source

    def setUp(self):
        fixtures.PurchaseOrderApiTests.setUp(self)
        self.supplier.supplier_categories = [SupplierCategory.PACKAGING]
        self.supplier.save(update_fields=["supplier_categories"])
        self.tasks = [self.make_task(f"PACK-{index}") for index in range(3)]
        for index, task in enumerate(self.tasks):
            product = self.make_product_line(task)
            bom, _ = self.make_bom(product, section_type=BomSectionType.ACCESSORY, budget_quantity="100")
            section = BomSection.objects.create(bom=bom, line_number=2, section_type=BomSectionType.ACCESSORY, title="包材类")
            for number, name in enumerate(["纸箱", "塑料袋", "外供包材"], 1):
                BomLine.objects.create(
                    section=section, line_number=number, part_name=name, category="包材", unit="PCS",
                    raw_values={"units_per_box": "1", "source_inventory_material_id": str(self.inventory_material.pk),
                                "purchase_required": number != 3},
                )
            if index < 2:
                task.followers.add(self.employee)

    def grant_packaging(self):
        self.user.user_permissions.clear()
        permission = Permission.objects.get(content_type__app_label="procurement", codename="manage_packagingpurchase")
        role = RoleProfile.objects.create(
            role_code="TEST-PACKAGING", display_name="测试跟单", auth_group=Group.objects.create(name="test-packaging"),
        )
        RoleActionGrant.objects.create(role=role, permission=permission, scope="FOLLOWED")
        role.auth_group.permissions.add(permission)
        EmployeeRoleAssignment.objects.create(employee=self.employee, role_profile=role, effective_from=timezone.now())

    def prepare(self):
        options = self.client.get(PACKAGING + "sources/")
        self.assertEqual(options.status_code, 200, options.data)
        sources = options.data["data"]
        self.assertEqual({row["production_task_id"] for row in sources}, {str(task.pk) for task in self.tasks[:2]})
        result = self.client.post(PACKAGING + "prepare/", {"sources": sources}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        return result.data["data"]

    def test_sources_and_writes_require_packaging_scope_and_followed_task(self):
        self.user.user_permissions.remove(Permission.objects.get(
            content_type__app_label="procurement", codename="manage_packagingpurchase",
        ))
        response = self.client.get(PACKAGING + "sources/")
        self.assertEqual(response.status_code, 403, response.data)
        ordinary = self.get_source(self.tasks[0])
        self.assertEqual(ordinary.status_code, 200, ordinary.data)
        self.assertEqual([line["part_name"] for line in ordinary.data["data"]["lines"]], ["采购测试物料"])
        standard = self.client.post("/api/v1/purchase-groups/", {
            "production_task_id": str(self.tasks[0].pk), "bom_id": ordinary.data["data"]["selected_bom_id"],
            "source_revision": ordinary.data["data"]["source_revision"],
        }, format="json")
        self.assertEqual(standard.status_code, 201, standard.data)
        self.grant_packaging()
        groups = self.prepare()
        self.assertEqual(len(groups), 2)
        for group in groups:
            self.assertEqual(len(group["progress"]["lines"]), 2)
        forbidden = self.client.post(PACKAGING + "prepare/", {"sources": [{
            "production_task_id": str(self.tasks[2].pk), "bom_id": str(self.tasks[2].boms.get().pk),
            "source_revision": "0" * 64,
        }]}, format="json")
        self.assertEqual(forbidden.status_code, 404, forbidden.data)
        self.assertEqual(self.get_source(self.tasks[0]).status_code, 403)
        self.assertEqual(self.client.get(PACKAGING + str(standard.data["data"]["id"]) + "/").status_code, 404)
        session = APIClient(enforce_csrf_checks=True)
        session.force_login(self.user)
        self.assertEqual(session.get(PACKAGING + "sources/").status_code, 200)
        self.assertEqual(session.post(PACKAGING + "prepare/", {"sources": []}, format="json").status_code, 403)

    def test_cross_task_drafts_resume_and_confirm_atomically(self):
        self.grant_packaging()
        groups = self.prepare()
        query = {"group_ids": [group["id"] for group in groups], "batch_session_id": str(uuid4())}
        page = self.client.get(PACKAGING + "batch-page/", query)
        self.assertEqual(page.status_code, 200, page.data)
        lines = [{
            "purchase_group_line_id": group["progress"]["lines"][0]["id"],
            "actual_purchase_quantity": quantity, "unit_price": "2", "supplier_id": str(self.supplier.pk),
            "delivery_date": (timezone.localdate() + timedelta(days=10)).isoformat(),
        } for group, quantity in zip(groups, ["500", "800"])]
        lines.append({"purchase_group_line_id": groups[0]["progress"]["lines"][1]["id"],
                      "actual_purchase_quantity": "100", "unit_price": "0"})
        batch = {"batch_type": "NORMAL", "request_id": str(uuid4()), "currency_id": str(self.cny.pk), "lines": lines}
        saved = self.client.post(PACKAGING + "save-page/", {**query, "batch": batch}, format="json",
                                 HTTP_IF_MATCH=page["ETag"])
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(PurchaseOrder.objects.filter(status=PurchaseOrderStatus.DRAFT).count(), 2)
        self.assertFalse(SupplierPurchaseSheet.objects.exists())
        resumed = self.client.get(PACKAGING + "batch-page/", query)
        self.assertEqual(resumed["ETag"], saved["ETag"])
        self.assertEqual(sum(len(row["batch_page"]["draft_orders"]) for row in resumed.data["data"]), 2)
        reopened = self.client.get(PACKAGING + "batch-page/", {"batch_session_id": query["batch_session_id"]})
        self.assertEqual(reopened["ETag"], resumed["ETag"])
        stale = self.client.post(PACKAGING + "confirm-page/", query, format="json", HTTP_IF_MATCH=page["ETag"])
        self.assertEqual(stale.status_code, 412, stale.data)
        self.assertEqual(PurchaseOrder.objects.filter(status=PurchaseOrderStatus.DRAFT).count(), 2)
        last = PurchaseOrder.objects.order_by("purchase_group_id").last()
        last_lines = PurchaseOrderLine.objects.filter(purchase_order=last)
        delivery_date = last_lines.get().delivery_date
        last_lines.update(delivery_date=None)
        failed = self.client.post(PACKAGING + "confirm-page/", query, format="json", HTTP_IF_MATCH=resumed["ETag"])
        self.assertEqual(failed.status_code, 400, failed.data)
        self.assertIn(last.production_task_number_snapshot, str(failed.data))
        self.assertEqual(PurchaseOrder.objects.filter(status=PurchaseOrderStatus.DRAFT).count(), 2)
        self.assertFalse(SupplierPurchaseSheet.objects.exists())
        last_lines.update(delivery_date=delivery_date)
        confirmed = self.client.post(PACKAGING + "confirm-page/", query, format="json", HTTP_IF_MATCH=resumed["ETag"])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(PurchaseOrder.objects.filter(status=PurchaseOrderStatus.SUBMITTED).count(), 2)
        for group, quantity in zip(groups, [500, 800]):
            order = PurchaseOrder.objects.get(purchase_group_id=group["id"])
            self.assertEqual(order.lines.get().actual_purchase_quantity, quantity)
            self.assertEqual(order.supplier_purchase_sheets.count(), 1)
        sheets = self.client.get("/api/v1/supplier-purchase-sheets/", {
            "purchase_scope": "PACKAGING", "batch_session_id": query["batch_session_id"],
        })
        self.assertEqual(sheets.status_code, 200, sheets.data)
        self.assertEqual(len(sheets.data["data"]), 2)
        self.assertTrue(all(row["purchase_scope"] == "PACKAGING" for row in sheets.data["data"]))

    def test_packaging_supplier_options_and_writes_exclude_other_categories(self):
        other = Supplier.objects.create(
            supplier_number="GYS99001", supplier_name="普通五金供应商",
            supplier_type=self.supplier.supplier_type, supplier_categories=[SupplierCategory.HARDWARE],
        )
        self.grant_packaging()
        options = self.client.get(PACKAGING + "options/")
        self.assertEqual(options.status_code, 200, options.data)
        suppliers = options.data["data"]["suppliers"]
        self.assertIn(str(self.supplier.pk), {item["id"] for item in suppliers})
        self.assertTrue(all(SupplierCategory.PACKAGING in item["supplier_categories"] for item in suppliers))

        group = self.prepare()[0]
        query = {"group_ids": [group["id"]], "batch_session_id": str(uuid4())}
        page = self.client.get(PACKAGING + "batch-page/", query)
        batch = {"batch_type": "NORMAL", "request_id": str(uuid4()), "currency_id": str(self.cny.pk), "lines": [{
            "purchase_group_line_id": group["progress"]["lines"][0]["id"],
            "actual_purchase_quantity": "1", "unit_price": "2", "supplier_id": str(other.pk),
            "delivery_date": timezone.localdate().isoformat(),
        }]}
        result = self.client.post(PACKAGING + "save-page/", {**query, "batch": batch}, format="json", HTTP_IF_MATCH=page["ETag"])
        self.assertEqual(result.status_code, 400, result.data)
        self.assertIn("包材类供应商", str(result.data))
        self.assertFalse(PurchaseOrder.objects.exists())
