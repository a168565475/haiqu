from django.test import override_settings
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.inventory.tests import test_followed_record_access as inventory_fixture


@override_settings(MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True, ACCESS_RESOURCE_SCOPES_ENABLED=True)
class ProductionDashboardReceiptScopeTests(ScopedActorMixin, APITestCase):
    def setUp(self):
        inventory_fixture.FollowedInventoryRecordAccessTests.setUp(self)

    def test_receipt_summary_follows_current_task_and_revocation(self):
        self.grant('inventory.view_finishedgoodsreceipt', 'FOLLOWED')
        response = self.client.get('/api/v1/production-dashboard/')
        self.assertEqual(response.status_code, 200, response.data)
        sections = response.data['data']['sections']
        self.assertEqual(sections['tasks']['state'], 'FORBIDDEN')
        receipts = sections['receipts']['data']
        self.assertEqual(receipts['today_count'], 1)
        self.assertEqual([row['id'] for row in receipts['items']], [str(self.own_receipt.pk)])
        self.assertEqual([row['quantity'] for row in receipts['today_quantities']], ['6'])
        self.assertEqual(receipts['pending_state'], 'FORBIDDEN')
        self.assertEqual(receipts['pending_products'], [])

        self.task.followers.clear()
        revoked = self.client.get('/api/v1/production-dashboard/')
        self.assertEqual(revoked.status_code, 200, revoked.data)
        receipts = revoked.data['data']['sections']['receipts']['data']
        self.assertEqual(receipts['today_count'], 0)
        self.assertEqual(receipts['today_quantities'], [])
        self.assertEqual(receipts['items'], [])
