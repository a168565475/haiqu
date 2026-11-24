from uuid import uuid4

from django.test import SimpleTestCase
from django.urls import Resolver404, resolve

from apps.finance.supplier_payment_application_serializers import SupplierApplicationCreateSerializer


class SupplierPaymentRouteTests(SimpleTestCase):
    def test_independent_finance_routes_are_registered(self):
        for segment, view_name in (
            ("supplier-payments", "SupplierPaymentViewSet"),
            ("supplier-payment-applications", "SupplierPaymentApplicationViewSet"),
        ):
            with self.subTest(segment=segment):
                try:
                    match = resolve(f"/api/v1/finance/{segment}/")
                except Resolver404:
                    self.fail(f"Route is not registered: {segment}")
                self.assertEqual(match.func.cls.__name__, view_name)

    def test_application_accepts_more_than_one_hundred_distinct_payables(self):
        serializer = SupplierApplicationCreateSerializer(data={
            "supplier_id": str(uuid4()), "payee": "测试收款抬头",
            "lines": [{"payable_id": str(uuid4()), "amount": "0.01"} for _ in range(101)],
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(str(serializer.validated_data["amount"]), "1.01")
