from copy import deepcopy
from uuid import uuid4

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.product_catalog.models import ProductCatalog
from apps.production_tasks.models import ProductionTask
from apps.sales_orders.models import SalesOrderLine
from . import test_catalog_product_flow as catalog_tests
from . import test_sales_order_api as sales_tests


class CatalogSalesProductionTests(APITestCase):
    setUp = catalog_tests.CatalogCommercialFlowTests.setUp
    selection = catalog_tests.CatalogCommercialFlowTests.selection
    order_payload = catalog_tests.CatalogCommercialFlowTests.order_payload

    def test_confirmed_sales_order_creates_production_with_original_product_selection(self):
        created = self.client.post("/api/v1/sales-orders/", self.order_payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        line = SalesOrderLine.objects.get(sales_order_id=created.data["data"]["id"])
        saved_selection = deepcopy(line.product_selection_snapshot)
        confirmed = self.client.post(f"/api/v1/sales-orders/{line.sales_order_id}/confirm/", {},
                                     format="json", HTTP_IF_MATCH=created["ETag"])
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        ProductCatalog.objects.filter(pk=self.catalog.pk).update(
            specification="主档以后修改", materials=["木"], archived_at=timezone.now(),
        )
        response = self.client.post("/api/v1/production-tasks/create-from-sales-order/", {
            **sales_tests.SalesOrderApiTests.production_fields(self),
            "task_number": "HT26991", "request_key": str(uuid4()),
            "delivery_batch_line_id": confirmed.data["data"]["delivery_batches"][0]["lines"][0]["id"],
            "quantity": 10, "planned_start_date": timezone.localdate().isoformat(),
            "planned_end_date": timezone.localdate().isoformat(), "production_priority": "NORMAL",
            "planner_id": str(self.planner.pk),
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        product = ProductionTask.objects.get(pk=response.data["data"]["id"]).products.get()
        self.assertIsNone(product.product_id)
        self.assertEqual(product.product_catalog_id, self.catalog.pk)
        self.assertEqual(product.product_selection_snapshot, saved_selection)
        self.assertEqual(product.specification_snapshot, "60×80")
        self.assertEqual(product.color_name_snapshot, "蓝色")
        self.assertEqual(product.material_snapshot, "铝")
        self.assertEqual(product.unit_id, self.unit.pk)
        self.assertEqual(product.quantity, 10)
