from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient

from apps.inventory.tests import test_inventory_api as inventory_fixtures
from apps.organizations.models import Employee
from apps.procurement.models import PurchaseOrderStatus, PurchaseReturn
from apps.procurement.tests import test_purchase_completion_api as completion_fixtures


class PurchaseReadDetailTests(APITestCase):
    def setUp(self):
        inventory_fixtures.MaterialInventoryApiTests.setUp(self)
        # This suite exercises read-only quantities with a non-pipe material.
        self.purchase_line.section_type_snapshot = "ACCESSORY"
        self.purchase_line.section_title_snapshot = "配件类"
        self.purchase_line.save(update_fields=["section_type_snapshot", "section_title_snapshot"])
        section = self.bom_line.section
        section.section_type = "ACCESSORY"
        section.save(update_fields=["section_type"])
    payload = inventory_fixtures.MaterialInventoryApiTests.payload
    confirm_quality = inventory_fixtures.MaterialInventoryApiTests.confirm_quality
    receive = completion_fixtures.PurchaseCompletionApiTests.receive
    complete_order = completion_fixtures.PurchaseCompletionApiTests.complete_order
    advance_return = completion_fixtures.PurchaseCompletionApiTests.advance_return

    @property
    def url(self):
        return f"/api/v1/purchase-orders/{self.order.pk}/details/"

    def test_partial_completed_order_keeps_exact_readonly_records(self):
        self.purchase_line.color_snapshot = "材料黑色"
        self.purchase_line.save(update_fields=["color_snapshot"])
        receipt = self.receive("4.2500")
        self.assertEqual(self.confirm_quality(receipt, return_quantity="0.2500").status_code, 200)
        record = PurchaseReturn.objects.get()
        self.assertEqual(self.advance_return(record, "confirm").status_code, 200)
        self.assertEqual(self.advance_return(record, "complete").status_code, 200)
        self.assertEqual(self.complete_order("部分到货结单，已退货").status_code, 200)
        self.order.refresh_from_db()
        before = self.order.updated_at
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        line = data["lines"][0]
        self.assertEqual(Decimal(line["received_quantity"]), Decimal("4.25"))
        self.assertEqual(Decimal(line["accepted_quantity"]), Decimal("4"))
        self.assertEqual(Decimal(line["return_quantity"]), Decimal("0.25"))
        self.assertEqual(line["color"], "材料黑色")
        self.assertEqual(data["status"], PurchaseOrderStatus.COMPLETED)
        self.assertEqual(data["completed_by_name"], self.employee.display_name)
        self.assertEqual(data["inbounds"][0]["quality_confirmed_by_name"], self.employee.display_name)
        self.assertEqual(data["returns"][0]["lines"][0]["color"], "材料黑色")
        self.order.refresh_from_db()
        self.assertEqual(self.order.updated_at, before)

    def test_pending_quality_counts_as_arrival_but_not_accepted_or_returned(self):
        first = self.receive("4.2500")
        self.assertEqual(self.confirm_quality(first, return_quantity="0.2500").status_code, 200)
        record = PurchaseReturn.objects.get()
        self.advance_return(record, "confirm")
        self.advance_return(record, "complete")
        self.receive("2.1250", "6.5000")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]
        self.assertEqual(len(data["inbounds"]), 2)
        line = data["lines"][0]
        self.assertEqual(Decimal(line["received_quantity"]), Decimal("6.375"))
        self.assertEqual(Decimal(line["accepted_quantity"]), Decimal("4"))
        self.assertEqual(Decimal(line["return_quantity"]), Decimal("0.25"))

    def test_empty_records_and_supplier_snapshots(self):
        self.supplier.supplier_name = "新的公司名称"
        self.supplier.save(update_fields=["supplier_name"])
        data = self.client.get(self.url).data["data"]
        self.assertEqual(data["supplier_count"], 1)
        self.assertEqual(data["supplier_summary"][0]["supplier_name"], self.purchase_line.supplier_name_snapshot)
        self.assertEqual(data["inbounds"], [])
        self.assertEqual(data["returns"], [])
        self.assertEqual(Decimal(data["lines"][0]["received_quantity"]), 0)

    def test_read_permissions_do_not_grant_writes_and_scope_is_preserved(self):
        self.order.status = PurchaseOrderStatus.PURCHASING
        self.order.save(update_fields=["status"])
        for app, code in [("procurement", "view_purchaseorder"), ("inventory", "receive_material"), ("inventory", "quality_confirm_material")]:
            self.user.user_permissions.set(Permission.objects.filter(content_type__app_label=app, codename=code))
            self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
            self.assertEqual(self.client.get(self.url).status_code, 200)
            self.assertIn(self.client.post(self.url, {}, format="json").status_code, [403, 405])
            self.assertEqual(self.client.post(f"/api/v1/purchase-orders/{self.order.pk}/complete/", {}, format="json").status_code, 403)
        outsider = get_user_model().objects.create_user(username="detail_outsider")
        Employee.objects.create(user=outsider, employee_code="DET_OUT", display_name="其他查看人")
        outsider.user_permissions.set(Permission.objects.filter(content_type__app_label="procurement", codename="view_purchaseorder"))
        other = APIClient()
        other.force_authenticate(outsider)
        self.assertEqual(other.get(self.url).status_code, 404)
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_inventory_cannot_read_drafts_or_unstarted_orders(self):
        for code in ["receive_material", "quality_confirm_material"]:
            self.user.user_permissions.set(Permission.objects.filter(content_type__app_label="inventory", codename=code))
            self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
            for status in [PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.SUBMITTED]:
                self.order.status = status
                self.order.save(update_fields=["status"])
                self.assertEqual(self.client.get(self.url).status_code, 404)
        self.user.user_permissions.set(Permission.objects.filter(content_type__app_label="procurement", codename="view_purchaseorder"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_archived_order_hidden_and_bad_id_does_not_crash(self):
        self.assertIn(self.client.get("/api/v1/purchase-orders/not-a-uuid/details/").status_code, [400, 404])
        self.order.archived_at = timezone.now()
        self.order.save(update_fields=["archived_at"])
        self.assertEqual(self.client.get(self.url).status_code, 404)
