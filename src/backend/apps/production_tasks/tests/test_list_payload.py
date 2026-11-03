"""列表摘要与完整详情分别取数；测试数据仅由隔离测试库承载。"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from apps.boms.models import Bom
from apps.customers.models import CustomerAccount
from apps.files.models import BusinessFile
from apps.organizations.models import Employee
from apps.procurement.models import PurchaseOrder, PurchaseOrderLine, PurchaseRequest
from apps.reference_data.models import Currency, ProductColor, ProductionUnit
from apps.sales_orders.models import SalesOrder, SalesOrderDeliveryBatch, SalesOrderDeliveryBatchLine, SalesOrderLine

from ..api.serializers import ProductionTaskListSerializer
from ..models import ProductionTask, ProductionTaskDetail, ProductionTaskProduct, ProductionTaskProductImage
from ..selectors import production_tasks_with_context


class ProductionTaskListPayloadTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="task-list-reader")
        cls.user.user_permissions.set(Permission.objects.filter(
            content_type__app_label="production_tasks", codename__in=("view_productiontask", "change_productiontask"),
        ))
        cls.employee = Employee.objects.create(user=cls.user, employee_code="LIST-READER", display_name="列表读取员工")
        cls.other = Employee.objects.create(employee_code="LIST-OTHER", display_name="其他员工")
        cls.currency, _ = Currency.objects.get_or_create(code="CNY", defaults={
            "numeric_code": "156", "chinese_name": "人民币", "english_name": "Yuan Renminbi",
        })
        cls.unit = ProductionUnit.objects.create(unit_code="LIST-UNIT", unit_name="件")
        cls.color = ProductColor.objects.create(color_card="LIST", color_code="BLUE", color_name="蓝")
        cls.task = cls.create_task("VISIBLE", cls.employee)
        cls.task.followers.add(cls.employee)
        cls.create_task("HIDDEN", cls.other)
        cls.first = cls.create_product(1, product_selection_snapshot={
            "unit_name": "历史箱", "unit_code": "HISTORY-BOX", "configuration": {"unused": "明细快照"},
        })
        cls.second = cls.create_product(2)
        cls.file = BusinessFile.objects.create(
            original_name="list-fixture.png", storage_key="test-list-payload/metadata-only.png",
            content_type="image/png", size_bytes=100, scan_status="CLEAN",
        )
        cls.first.image_file = cls.file
        cls.first.save(update_fields=["image_file"])
        ProductionTaskProductImage.objects.create(product_line=cls.first, line_number=1, image_file=cls.file)
        ProductionTaskDetail.objects.create(
            product_line=cls.first, line_number=1, template_key="fabric", detail_type="面料",
            description="详情保留", image_file=cls.file,
        )
        cls.bom = Bom.objects.create(
            bom_number="LIST-PAYLOAD-BOM", production_task=cls.task, product_line=cls.first,
            creation_method="BLANK", status="VERIFIED", product_name_snapshot="产品",
            order_quantity=2, source_metadata={"unused": "完整来源快照"},
        )
        PurchaseRequest.objects.create(
            request_number="LIST-PAYLOAD-REQUEST", production_task=cls.task, bom=cls.bom, status="SUBMITTED",
        )

    @classmethod
    def create_task(cls, suffix, employee):
        return ProductionTask.objects.create(
            task_number=f"LIST-{suffix}", contract_number=f"LIST-{suffix}", order_source="NEW",
            order_date=date(2026, 11, 1), delivery_date=date(2026, 11, 30), salesperson=employee,
            currency=cls.currency, includes_tax=False, order_tolerance_percent=0,
            is_repeat_order=False, preproduction_sample_required=False, delivery_method="SINGLE", status="READY",
        )

    @classmethod
    def create_product(cls, number, **overrides):
        values = dict(
            production_task=cls.task, line_number=number, product_name_snapshot=f"产品 {number}",
            specification_snapshot="尺寸；颜色：蓝；材质：金属", material_snapshot="金属",
            product_color=cls.color, color_name_snapshot="历史蓝", color_code_snapshot="BLUE",
            quantity=2, unit=cls.unit, currency=cls.currency, unit_price=Decimal("6.25"),
            total_amount=Decimal("12.50"), exchange_rate=Decimal("7"),
            exchange_rate_snapshot={"unused": "完整汇率快照"}, special_requirements="详情要求",
        )
        values.update(overrides)
        return ProductionTaskProduct.objects.create(**values)

    def setUp(self):
        self.client.force_authenticate(self.user)

    def list_tasks(self):
        response = self.client.get("/api/v1/production-tasks/", {"ordering": "-created_at"})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"]

    def test_list_returns_only_display_and_action_fields_without_image_or_detail_queries(self):
        with CaptureQueriesContext(connection) as queries:
            rows = self.list_tasks()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(set(row), {
            "id", "task_number", "source_sales_order_number", "delivery_date", "salesperson", "followers",
            "status", "status_display", "bom_status", "bom_status_display", "purchase_status",
            "purchase_status_display", "allowed_permissions", "sales_order_id", "products",
        })
        self.assertEqual(set(row["products"][0]), {
            "id", "customer_product_name", "product_name", "item_number", "specification_display",
            "customer_specification", "specification", "material", "customer_color", "color_name", "color_code",
            "quantity", "unit_id", "unit_name", "unit_code", "product_selection_snapshot", "local_total_amount",
        })
        self.assertEqual(row["salesperson"], {"display_name": "列表读取员工"})
        self.assertEqual(row["followers"], [{"display_name": "列表读取员工"}])
        self.assertEqual(row["products"][0]["product_selection_snapshot"], {"unit_name": "历史箱"})
        self.assertEqual(row["products"][0]["unit_name"], "历史箱")
        self.assertEqual(row["products"][0]["unit_code"], "HISTORY-BOX")
        self.assertEqual(row["products"][1]["unit_name"], "件")
        self.assertEqual(row["products"][0]["specification_display"], "尺寸")
        self.assertEqual(row["products"][0]["local_total_amount"], "87.5000")
        sql = "\n".join(query["sql"] for query in queries)
        for table in ("business_file", "production_task_product_image", "production_task_detail",
                      "production_delivery_batch", "production_run_batch", "sales_order_line", "sales_order_delivery_batch_line"):
            self.assertNotIn(f'"{table}"', sql)

    def test_list_keeps_progress_permissions_and_detail_contract(self):
        row = self.list_tasks()[0]
        response = self.client.get(f"/api/v1/production-tasks/{self.task.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        detail = response.data["data"]
        for field in ("status", "status_display", "bom_status", "bom_status_display", "purchase_status",
                      "purchase_status_display", "allowed_permissions"):
            self.assertEqual(row[field], detail[field])
        self.assertEqual(row["bom_status"], "PARTIAL")
        self.assertEqual(row["purchase_status"], "REQUEST_SUBMITTED")
        self.assertIn("production_tasks.change_productiontask", row["allowed_permissions"])
        product = detail["products"][0]
        self.assertEqual(product["images"][0]["name"], "list-fixture.png")
        self.assertEqual(product["details"][0]["description"], "详情保留")
        self.assertEqual(product["product_selection_snapshot"]["configuration"], {"unused": "明细快照"})
        self.assertIn("max_production_quantity", product)
        self.assertIn("deletion_blocked_reason", product)
        self.assertEqual(product["exchange_rate_snapshot"], {"unused": "完整汇率快照"})

    def test_list_prefetch_does_not_reload_deferred_fields_during_serialization(self):
        self.create_product(3, unit=None, product_color=None, product_selection_snapshot={"unit_name": "临时单位"})
        order = PurchaseOrder.objects.create(
            order_number="CGDD261101001", production_task=self.task, status="PURCHASING",
            production_task_number_snapshot=self.task.task_number, source_revision="list-payload",
        )
        PurchaseOrderLine.objects.create(
            purchase_order=order, line_number=1, product_line_id_snapshot=self.first.pk,
            quantity_parse_status="MISSING",
        )
        task = production_tasks_with_context(
            ProductionTask.objects.filter(pk=self.task.pk), include_progress=True, list_mode=True,
        ).get()
        self.assertIn("special_requirements_html", task.get_deferred_fields())
        self.assertIn("product_selection_snapshot", task.products.all()[0].get_deferred_fields())
        self.assertIn("source_metadata", task._active_boms_for_status[0].get_deferred_fields())
        with self.assertNumQueries(0):
            data = ProductionTaskListSerializer(task).data
        self.assertEqual(data["purchase_status"], "ORDER_PARTIAL")
        self.assertEqual(data["products"][2]["unit_name"], "临时单位")

    def test_sales_source_product_count_does_not_add_list_queries(self):
        customer = CustomerAccount.objects.create(account_code="LIST-SOURCE", account_name="列表来源客户")
        order = SalesOrder.objects.create(
            order_number="LIST-SALES", source_type="DIRECT", customer_account=customer, salesperson=self.employee,
            order_date=date(2026, 11, 1), currency_code="CNY",
        )
        batch = SalesOrderDeliveryBatch.objects.create(
            sales_order=order, line_number=1, batch_number="LIST-BATCH", planned_delivery_date=date(2026, 11, 30),
        )
        self.task.sales_order = order
        self.task.sales_order_delivery_batch = batch
        self.task.save(update_fields=["sales_order", "sales_order_delivery_batch"])

        def attach_source(product):
            sales_line = SalesOrderLine.objects.create(
                sales_order=order, line_number=product.line_number, product_name_snapshot=product.product_name_snapshot,
                unit_code_snapshot="LIST-UNIT", quantity=10, unit_price=1, line_total=10,
            )
            product.sales_order_delivery_batch_line = SalesOrderDeliveryBatchLine.objects.create(
                delivery_batch=batch, sales_order_line=sales_line, quantity=10,
            )
            product.save(update_fields=["sales_order_delivery_batch_line"])

        attach_source(self.first)
        with CaptureQueriesContext(connection) as baseline:
            self.list_tasks()
        for number in range(3, 9):
            attach_source(self.create_product(number))
        with CaptureQueriesContext(connection) as expanded:
            rows = self.list_tasks()
        self.assertEqual(len(rows[0]["products"]), 8)
        self.assertEqual(rows[0]["source_sales_order_number"], "LIST-SALES")
        self.assertLessEqual(len(expanded), len(baseline))
        self.assertNotIn('"sales_order_delivery_batch_line"', "\n".join(query["sql"] for query in expanded))

    def test_missing_task_permission_still_rejects_list(self):
        user = get_user_model().objects.create_user(username="task-list-denied")
        Employee.objects.create(user=user, employee_code="LIST-DENIED", display_name="无权限员工")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get("/api/v1/production-tasks/").status_code, 403)
