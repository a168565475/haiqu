import uuid

from django.utils import timezone

from ..models import OutsourcingOrder
from .test_outsourcing_source_bom_api import OutsourcingSourceBomApiTests


class RetiredOutsourcingCreateApiTests(OutsourcingSourceBomApiTests):
    def test_collection_post_is_denied_without_creating_order(self):
        before = OutsourcingOrder.objects.count()
        response = self.client.post("/api/v1/outsourcing-orders/", {
            "client_request_id": str(uuid.uuid4()),
            "schedule_id": str(self.schedule_product.schedule_id),
            "craft_id": str(self.sewing.pk),
            "delivery_date": timezone.localdate().isoformat(),
            "products": [],
        }, format="json")

        # 退役后没有 create 权限映射，现有权限边界先于方法分派拒绝请求。
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(OutsourcingOrder.objects.count(), before)

    def test_retired_source_endpoints_return_not_found_without_creating_order(self):
        before = OutsourcingOrder.objects.count()
        paths = (
            "/api/v1/outsourcing-orders/source-plans/",
            f"/api/v1/outsourcing-orders/source-products/{self.schedule_product.pk}/bom/",
        )
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path, {"craft_id": str(self.sewing.pk)})
                self.assertEqual(response.status_code, 404)
                self.assertEqual(OutsourcingOrder.objects.count(), before)

    def test_historical_detail_list_and_options_remain_readable(self):
        order = OutsourcingOrder.objects.create(
            order_number="WF-RETIRED-CREATE-001",
            schedule=self.schedule_product.schedule,
            craft=self.sewing,
            craft_name_snapshot=self.sewing.name,
            craft_code_snapshot=self.sewing.outsourcing_code,
            delivery_date=timezone.localdate(),
            source_revision_hash="a" * 64,
            client_request_id=uuid.uuid4(),
            request_payload_hash="b" * 64,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        before = OutsourcingOrder.objects.count()

        detail = self.client.get(f"/api/v1/outsourcing-orders/{order.pk}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["data"]["id"], str(order.pk))
        self.assertIn("ETag", detail)

        for path in ("/api/v1/outsourcing-orders/", "/api/v1/outsourcing-orders/options/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(OutsourcingOrder.objects.count(), before)
