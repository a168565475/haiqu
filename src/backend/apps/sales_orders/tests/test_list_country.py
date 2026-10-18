from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.sales_orders.api.serializers import SalesOrderListSerializer


class SalesOrderListCountryTests(SimpleTestCase):
    def test_country_comes_from_customer_not_shipping_snapshot(self):
        field = SalesOrderListSerializer().fields["customer_country_code"]
        order = SimpleNamespace(
            customer_account=SimpleNamespace(primary_country_code="DE"),
            buyer_address_snapshot={"country_code": "US"},
        )
        self.assertTrue(field.read_only)
        self.assertEqual(field.to_representation(field.get_attribute(order)), "DE")

    def test_missing_customer_country_stays_empty(self):
        field = SalesOrderListSerializer().fields["customer_country_code"]
        order = SimpleNamespace(customer_account=SimpleNamespace(primary_country_code=""))
        self.assertEqual(field.to_representation(field.get_attribute(order)), "")
