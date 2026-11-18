from decimal import Decimal

from django.test import SimpleTestCase

from apps.inventory.internal_receipt_quantities import ComponentDemand, ReceivedOutput, calculate_receipt, validate_receipt, ReceiptQuantityError


class PartFlowQuantityTests(SimpleTestCase):
    def test_piece_and_part_units_are_independent_without_product_set_count(self):
        demands = [ComponentDemand('task', 'piece', 'piece', '片', '片', Decimal(200), None),
                   ComponentDemand('task', 'part', 'part', '片', '个', Decimal(100), None)]
        result = validate_receipt(scope_key='task', demands=demands, inputs=[], history=[],
            requested={'piece': 20, 'part': 5}, check_inputs=False)
        self.assertEqual(result.components['piece'].received_after, 20)
        self.assertEqual(result.components['part'].received_after, 5)
        self.assertIsNone(result.components['part'].consumes_input)

    def test_direct_dispatch_and_pending_receipt_share_first_output_allowance(self):
        demand = ComponentDemand('task', 'piece', 'piece', '片', '片', Decimal(100), None,
            directly_committed=Decimal(40))
        args = dict(scope_key='task', demands=[demand], inputs=[], check_inputs=False,
            history=[ReceivedOutput('task', 'piece', 'piece', '片', '片', Decimal(30), None)])
        self.assertEqual(calculate_receipt(**args).components['piece'].can_receive, 30)
        with self.assertRaises(ReceiptQuantityError):
            validate_receipt(**args, requested={'piece': 31})
