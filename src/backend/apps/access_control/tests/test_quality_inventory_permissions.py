from django.test import override_settings
from rest_framework.test import APITestCase

from apps.access_control.production_role_templates import DIRECTORS, templates
from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.workshop_config.models import Workshop


@override_settings(ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True,
                   ACCESS_RESOURCE_SCOPES_ENABLED=True)
class QualityInventoryPermissionsTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        self.scoped_actor()
        workshops = {name: Workshop.objects.get_or_create(name=name)[0].pk for name in DIRECTORS.values()}
        for row in templates(workshops)['QUALITY']:
            self.grant(row['permission'], row['scope'])

    def test_quality_can_read_material_inventory_and_filter_options(self):
        for path in ('/api/v1/material-inventory/', '/api/v1/material-inventory/options/'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.data)

    def test_quality_inventory_read_does_not_allow_receiving_or_purchase_management(self):
        for path in ('/api/v1/material-inventory/manual-receipts/', '/api/v1/material-inventory/batch-receipts/'):
            with self.subTest(path=path):
                response = self.client.post(path, {}, format='json')
                self.assertEqual(response.status_code, 403, response.data)
        response = self.client.get('/api/v1/purchase-orders/')
        self.assertEqual(response.status_code, 403, response.data)
