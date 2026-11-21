from decimal import Decimal

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.inventory.selectors import material_receipt_progress
from apps.inventory.tests import test_pipe_root_receiving as fixtures
from apps.procurement.tracking_selectors import arrival_rows


@override_settings(PUBLIC_STOCK_FLOW_ENABLED=True)
class RootArrivalTests(APITestCase):
    make_order = fixtures.PipeRootReceivingTests.make_order
    setUp = fixtures.PipeRootReceivingTests.setUp
    receive = fixtures.PipeRootReceivingTests.receive
    inspect = fixtures.PipeRootReceivingTests.inspect

    def test_batch_roots_drive_tracking_and_rejected_roots_reopen_progress(self):
        def row():
            return arrival_rows(task_ids=[self.order.production_task_id])[0]

        first = row()
        self.assertEqual((first['ordered_quantity'], first['unit']), ('5', '根'))
        result = self.receive(3, 5)
        self.assertEqual(result.status_code, 201, result.data)
        pending = row()
        self.assertEqual([Decimal(pending[key]) for key in ('pending_quality_quantity', 'unreceived_quantity')], [3, 2])
        self.inspect(result, 1)
        tracked = row()
        self.assertEqual([Decimal(tracked[key]) for key in
            ('received_quantity', 'accepted_quantity', 'return_quantity', 'unreceived_quantity')], [3, 2, 1, 3])
        self.assertEqual(material_receipt_progress([self.line])[self.order.pk], '40.0')
