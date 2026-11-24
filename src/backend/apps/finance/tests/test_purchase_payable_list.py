from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.inventory.models import MaterialInbound, MaterialInboundLine, Warehouse, WarehouseZone
from apps.organizations.models import Employee
from apps.procurement.models import PurchaseOrder, PurchaseOrderLine, Supplier
from apps.production_tasks.models import ProductionTask
from apps.reference_data.models import Currency
from apps.finance.purchase_payable_models import PurchasePayable, PurchasePayableLine


ROOT = "/api/v1/finance/purchase-payables/"


@override_settings(SALES_ACCESS_ENABLED=False, MODULE_ACCESS_ENABLED=False)
class PurchasePayableListTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="payable_list_test")
        cls.user.user_permissions.add(Permission.objects.get(codename="view_purchasepayable"))
        employee = Employee.objects.create(user=cls.user, employee_code="AP_LIST", display_name="应付测试")
        warehouse = Warehouse.objects.create(warehouse_number="AP_LIST", warehouse_name="测试仓", warehouse_type="MATERIAL")
        zone = WarehouseZone.objects.create(warehouse=warehouse, zone_name="测试库区")
        currency, _ = Currency.objects.get_or_create(code="CNY", defaults={"numeric_code": "156", "chinese_name": "人民币"})
        task = ProductionTask.objects.create(task_number="AP-LIST", contract_number="AP-LIST", order_number="AP-LIST",
            order_source="NEW", order_date=date(2026, 11, 1), delivery_date=date(2026, 11, 30), salesperson=employee,
            currency=currency, includes_tax=False, order_tolerance_percent=0, is_repeat_order=False,
            preproduction_sample_required=False, delivery_method="SINGLE", created_by_employee=employee)
        order = PurchaseOrder.objects.create(order_number="CGDD261119001", production_task=task, created_by_employee=employee)
        cls.payables = []
        cls.lines = []
        for index in range(2):
            supplier = Supplier.objects.create(supplier_number=f"GYS9900{index}", supplier_name=f"测试供应商{index}", supplier_type="MATERIAL")
            inbound = MaterialInbound.objects.create(inbound_number=f"AP-IN-{index}", purchase_order=order,
                inbound_date=f"2026-11-{index + 1:02}", received_by_employee=employee)
            payable = PurchasePayable.objects.create(number=f"CGYF-TEST-{index}", material_inbound=inbound,
                supplier=supplier, supplier_name_snapshot=supplier.supplier_name,
                supplier_number_snapshot=supplier.supplier_number, inbound_number_snapshot=inbound.inbound_number,
                purchase_order_number_snapshot=order.order_number,
                status="WAITING_PRICE" if index == 0 else "WAITING_FINANCE_CONFIRM")
            cls.payables.append(payable)
            for row, material in enumerate(("管材", "铆钉")):
                purchase_line = PurchaseOrderLine.objects.create(purchase_order=order, line_number=index * 2 + row + 1,
                    quantity_parse_status="READY")
                inbound_line = MaterialInboundLine.objects.create(inbound=inbound, purchase_order_line=purchase_line,
                    zone=zone, received_quantity=100, return_quantity=5, accepted_quantity=95,
                    received_weight_kg=100, return_weight_kg=5, accepted_weight_kg=95, purchased_quantity_snapshot=100)
                cls.lines.append(PurchasePayableLine.objects.create(payable=payable, material_inbound_line=inbound_line,
                    purchase_order_line=purchase_line, part_name_snapshot=material, material_snapshot="铁", specification_snapshot=f"规格-{row}",
                    source_unit_text_snapshot="KG", accepted_quantity=95, accepted_weight_kg=95,
                    reference_unit_price="2.5", currency_code_snapshot="CNY"))

    def setUp(self):
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))

    def get_lines(self, **params):
        response = self.client.get(ROOT + "lines/", params, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200, response.data)
        return response.json()

    def test_pagination_counts_material_lines_and_keeps_price_provenance(self):
        first = self.get_lines(page_size=1)
        second = self.get_lines(page_size=1, page=2)
        self.assertEqual(first["meta"]["total"], 4)
        self.assertEqual(first["meta"]["total_pages"], 4)
        self.assertNotEqual(first["data"][0]["line_id"], second["data"][0]["line_id"])
        row = first["data"][0]
        self.assertEqual(row["reference_unit_price"], "2.5000")
        self.assertIsNone(row["unit_price"])
        self.assertIsNone(row["amount"])
        self.assertEqual(row["settlement_quantity"], "95.0000")
        self.assertEqual(row["source_unit_text_snapshot"], "KG")
        self.assertIn(row["payable_id"], [str(p.pk) for p in self.payables])
        self.assertIn(row["inbound_date"], ["2026-11-01", "2026-11-02"])

    def test_material_search_matches_only_matching_lines(self):
        for term in ("铆钉", "规格-1"):
            result = self.get_lines(q=term)
            self.assertEqual(result["meta"]["total"], 2)
            self.assertTrue(all(row["part_name"] == "铆钉" for row in result["data"]))
        self.assertEqual(self.get_lines(q="CGYF-TEST-0")["meta"]["total"], 2)

    def test_supplier_date_status_filters_combine(self):
        params = dict(supplier_id=str(self.payables[1].supplier_id), status="WAITING_FINANCE_CONFIRM",
            inbound_date_from="2026-11-02", inbound_date_to="2026-11-02")
        self.assertEqual(self.get_lines(**params)["meta"]["total"], 2)
        self.assertEqual(self.get_lines(**{**params, "status": "WAITING_PRICE"})["meta"]["total"], 0)
        response = self.client.get(ROOT + "lines/", {"inbound_date_from": "2026-12-01", "inbound_date_to": "2026-11-01"}, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 400)

    def test_supplier_options_cover_all_pages_without_duplicates(self):
        response = self.client.get(ROOT + "filter-options/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertCountEqual([item["id"] for item in response.json()["data"]["suppliers"]],
            [str(item.supplier_id) for item in self.payables])

    def test_read_actions_require_finance_permission(self):
        self.user.user_permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        for action in ("lines/", "filter-options/"):
            self.assertEqual(self.client.get(ROOT + action, HTTP_HOST="localhost").status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(ROOT + "lines/", HTTP_HOST="localhost").status_code, (401, 403))

    @override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True)
    def test_read_actions_work_with_module_permission_policy(self):
        self.assertEqual(self.get_lines()["meta"]["total"], 4)
        self.assertEqual(self.client.get(ROOT + "filter-options/", HTTP_HOST="localhost").status_code, 200)
