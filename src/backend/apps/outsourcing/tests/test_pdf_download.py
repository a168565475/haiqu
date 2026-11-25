from urllib.parse import unquote

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin

from .test_material_flow import MaterialFlowFixture
from .test_unified_tube_orders import UnifiedTubeFixture
from .test_warehouse_orders import SCOPES


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True, **SCOPES)
class TubePdfDownloadTests(ScopedActorMixin, UnifiedTubeFixture, APITestCase):
    def test_download_both_formats_with_the_existing_view_scope(self):
        order = self.saved_order('METAL')
        self.scoped_actor()
        self.grant('outsourcing.view_outsourcingorder', 'CRAFT', [self.spray])
        url = f"/api/v1/tube-outsourcing-orders/{order['id']}/"
        detail_before = self.client.get(url).data['data']
        for kind, label in (('processing', '委外加工单'), ('spray', '管材喷塑计划')):
            with self.subTest(kind=kind):
                response = self.client.get(url + 'print-pdf/', {'kind': kind})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], 'application/pdf')
                self.assertIn(f"{order['order_number']}_{label}.pdf", unquote(response['Content-Disposition']))
                self.assertIn('no-store', response['Cache-Control'])
                self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
        self.assertEqual(self.client.get(url).data['data'], detail_before)
        self.assertEqual(self.client.get(url + 'print-pdf/', {'kind': 'invalid'}).status_code, 400)

    def test_warehouse_download_uses_its_own_existing_read_scope(self):
        order = self.saved_order('METAL')
        self.scoped_actor()
        self.grant('outsourcing.confirm_dispatch_outsourcingorder', 'MODULE')
        url = f"/api/v1/tube-outsourcing-orders/{order['id']}/print-pdf/"
        self.assertEqual(self.client.get(url).status_code, 403)
        response = self.client.get(url, {'warehouse_stage': 'all'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))


class RegularPdfDownloadTests(MaterialFlowFixture, APITestCase):
    def test_legacy_order_downloads_as_processing_only(self):
        order_id = self.create('FABRIC', '150')
        url = f'/api/v1/outsourcing-orders/{order_id}/print-pdf/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
        self.assertEqual(self.client.get(url, {'kind': 'spray'}).status_code, 400)
