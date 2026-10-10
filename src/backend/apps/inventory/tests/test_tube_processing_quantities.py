"""管材加工数量纯计算测试：不连接数据库，不代替事务与并发验收。"""

import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext

from apps.inventory.tube_processing_quantities import (
    TubeQuantityError,
    assert_report_basis,
    calculate_tube_allowance,
)


class TubeProcessingQuantityTests(unittest.TestCase):
    def calculate(self, **changes):
        arguments = {
            "order_required": 200,
            "issued": 200,
            "operation_totals": {"operation-cut": 100, "operation-bend": 200},
        }
        arguments.update(changes)
        return calculate_tube_allowance(**arguments)

    def test_lowest_required_operation_controls_finished_quantity(self):
        allowance = self.calculate()
        self.assertEqual(allowance.reported_minimum, 100)
        self.assertEqual(allowance.remaining, 100)
        self.assertEqual((allowance.required, allowance.issued), (200, 200))

    def test_three_operations_do_not_sum_into_finished_quantity(self):
        allowance = self.calculate(operation_totals={"cut": 120, "bend": 80, "punch": 95})
        self.assertEqual((allowance.reported_minimum, allowance.remaining), (80, 80))

    def test_required_operation_with_no_report_contributes_zero(self):
        allowance = self.calculate(operation_totals={"cut": 200, "new-punch": 0})
        self.assertEqual((allowance.reported_minimum, allowance.remaining), (0, 0))

    def test_changed_operation_does_not_inherit_another_operation_total(self):
        before = self.calculate(operation_totals={"cut": 100, "old-bend": 200})
        after = self.calculate(operation_totals={"cut": 100, "new-bend": 0})
        self.assertEqual((before.remaining, after.remaining), (100, 0))

    def test_retired_operation_is_not_a_required_operation(self):
        # 当前适用集合由读取服务确认；纯计算只接受该集合，不拼接历代方案。
        before = self.calculate(operation_totals={"cut": 100, "retired-punch": 20})
        after = self.calculate(operation_totals={"cut": 100})
        self.assertEqual((before.remaining, after.remaining), (20, 100))

    def test_received_dispatched_and_reserved_share_one_reported_limit(self):
        allowance = self.calculate(received=40, dispatched=20, reserved=10)
        self.assertEqual((allowance.received, allowance.dispatched, allowance.reserved), (40, 20, 10))
        self.assertEqual((allowance.used, allowance.report_protected_usage, allowance.remaining), (70, 70, 30))
        assert_report_basis(allowance)

    def test_cancelling_unshipped_reservation_releases_only_reserved_quantity(self):
        before = self.calculate(received=40, dispatched=20, reserved=10)
        cancelled = self.calculate(received=40, dispatched=20, reserved=0)
        self.assertEqual((before.remaining, cancelled.remaining), (30, 40))
        self.assertEqual((cancelled.received, cancelled.dispatched), (40, 20))

    def test_reservation_becoming_actual_dispatch_does_not_double_count(self):
        reserved = self.calculate(received=40, dispatched=20, reserved=10)
        dispatched = self.calculate(received=40, dispatched=30, reserved=0)
        self.assertEqual((reserved.used, dispatched.used), (70, 70))
        self.assertEqual((reserved.report_protected_usage, dispatched.report_protected_usage), (70, 70))
        self.assertEqual((reserved.remaining, dispatched.remaining), (30, 30))

    def test_order_net_requirement_still_limits_large_report_totals(self):
        allowance = self.calculate(order_required=90, issued=300, operation_totals={"cut": 260, "bend": 250}, received=40)
        self.assertEqual(allowance.remaining, 50)

    def test_issued_material_still_limits_large_report_totals(self):
        allowance = self.calculate(order_required=300, issued=90, operation_totals={"cut": 260, "bend": 250}, received=40)
        self.assertEqual(allowance.remaining, 50)

    def test_zero_order_or_input_does_not_create_output_allowance(self):
        for changes in ({"order_required": 0}, {"issued": 0}):
            with self.subTest(changes=changes):
                self.assertEqual(self.calculate(**changes).remaining, 0)

    def test_zero_operation_total_is_a_valid_unfinished_state(self):
        allowance = self.calculate(operation_totals={"cut": 0, "bend": 0})
        self.assertEqual((allowance.reported_minimum, allowance.used, allowance.remaining), (0, 0, 0))
        assert_report_basis(allowance)

    def test_full_historical_consumption_is_not_reopened_by_stock_issues(self):
        # 库存后来被领走不改变累计首次入库；纯数量契约不接受当前库存余额。
        allowance = self.calculate(received=100)
        self.assertEqual((allowance.used, allowance.remaining), (100, 0))

    def test_report_guard_allows_exact_used_boundary(self):
        allowance = self.calculate(received=40, dispatched=20, reserved=40)
        self.assertEqual((allowance.reported_minimum, allowance.report_protected_usage, allowance.remaining), (100, 100, 0))
        assert_report_basis(allowance)

    def test_report_guard_rejects_reduction_below_all_shared_usage(self):
        allowance = self.calculate(operation_totals={"cut": 69, "bend": 200}, received=40, dispatched=20, reserved=10)
        self.assertEqual(allowance.report_protected_usage, 70)
        with self.assertRaises(TubeQuantityError):
            assert_report_basis(allowance)

    def test_unshipped_reservation_is_also_protected_from_report_reduction(self):
        allowance = self.calculate(operation_totals={"cut": 0}, reserved=1)
        with self.assertRaises(TubeQuantityError):
            assert_report_basis(allowance)

    def test_explicit_legacy_dispatch_is_exempt_only_from_report_guard(self):
        allowance = self.calculate(order_required=100, issued=100, operation_totals={"cut": 0}, dispatched=80, legacy_dispatched=80)
        self.assertEqual((allowance.used, allowance.report_protected_usage, allowance.remaining), (80, 0, 0))
        assert_report_basis(allowance)

    def test_legacy_dispatch_still_consumes_order_and_issued_input(self):
        cases = [
            (100, 200, 20),
            (200, 100, 20),
            (200, 200, 120),
        ]
        for required, issued, expected_remaining in cases:
            with self.subTest(required=required, issued=issued):
                allowance = self.calculate(order_required=required, issued=issued, operation_totals={"cut": 200},
                                           dispatched=80, legacy_dispatched=80)
                self.assertEqual((allowance.used, allowance.remaining), (80, expected_remaining))
                self.assertEqual(allowance.report_protected_usage, 0)

    def test_legacy_exemption_does_not_cover_new_received_or_reserved_usage(self):
        allowance = self.calculate(order_required=200, issued=200, operation_totals={"cut": 39},
                                   dispatched=80, legacy_dispatched=80, received=30, reserved=10)
        self.assertEqual((allowance.used, allowance.report_protected_usage), (120, 40))
        with self.assertRaises(TubeQuantityError):
            assert_report_basis(allowance)

    def test_legacy_dispatch_is_not_counted_twice_in_used_quantity(self):
        allowance = self.calculate(received=10, dispatched=80, reserved=5, legacy_dispatched=60)
        self.assertEqual((allowance.used, allowance.report_protected_usage, allowance.remaining), (95, 35, 5))

    def test_legacy_proof_does_not_release_extra_new_processing_allowance(self):
        ordinary = self.calculate(dispatched=80)
        legacy = self.calculate(dispatched=80, legacy_dispatched=80)
        self.assertEqual((ordinary.used, legacy.used, ordinary.remaining, legacy.remaining), (80, 80, 20, 20))

    def test_legacy_dispatch_cannot_exceed_total_actual_dispatch(self):
        with self.assertRaises(TubeQuantityError):
            self.calculate(dispatched=10, legacy_dispatched=11)

    def test_saved_quantity_upper_bound_is_inclusive(self):
        maximum = 99_999_999_999_999
        allowance = self.calculate(order_required=maximum, issued=maximum, operation_totals={"cut": maximum})
        self.assertEqual(allowance.remaining, maximum)
        with self.assertRaises(TubeQuantityError):
            self.calculate(order_required=maximum + 1)

    def test_combined_usage_cannot_overflow_saved_quantity_range(self):
        with self.assertRaises(TubeQuantityError):
            self.calculate(order_required=99_999_999_999_999, issued=99_999_999_999_999,
                           operation_totals={"cut": 99_999_999_999_999},
                           received=99_999_999_999_999, reserved=1)

    def test_database_decimal_trailing_zeroes_are_valid_whole_pieces(self):
        allowance = self.calculate(order_required=Decimal("200.0000"), issued="200.0000",
                                   operation_totals={"cut": Decimal("100.0000"), "bend": "200.0000"},
                                   received=Decimal("40.0000"), dispatched="20.0000", reserved=10)
        self.assertEqual((allowance.reported_minimum, allowance.used, allowance.remaining), (100, 70, 30))

    def test_integer_calculation_does_not_depend_on_global_decimal_precision(self):
        with localcontext() as context:
            context.prec = 4
            allowance = self.calculate(order_required=987654, issued=987654, operation_totals={"cut": 987654},
                                       received=123456, dispatched=234567, reserved=345678)
        self.assertEqual((allowance.used, allowance.remaining), (703701, 283953))

    def test_all_quantity_inputs_reject_invalid_or_inexact_values(self):
        invalid_values = [True, False, 1.0, 0.0, -1, "-1", Decimal("-1"), "1.5", Decimal("0.1"),
                          "NaN", "sNaN", "Infinity", "-Infinity", Decimal("NaN"), None, "", "wrong", [], {}, 10 ** 40]
        fields = ["order_required", "issued", "received", "dispatched", "reserved", "legacy_dispatched"]
        for field in fields:
            for value in invalid_values:
                with self.subTest(field=field, value=repr(value)):
                    with self.assertRaises(TubeQuantityError):
                        self.calculate(**{field: value})

    def test_operation_totals_reject_invalid_or_inexact_quantities(self):
        for value in [True, 1.0, -1, "1.5", Decimal("NaN"), "Infinity", None, {}, 10 ** 40]:
            with self.subTest(value=repr(value)):
                with self.assertRaises(TubeQuantityError):
                    self.calculate(operation_totals={"cut": value})

    def test_missing_operation_basis_is_a_controlled_error(self):
        for totals in [{}, None, [], [("cut", 100)], "cut"]:
            with self.subTest(totals=totals):
                with self.assertRaises(TubeQuantityError):
                    self.calculate(operation_totals=totals)

    def test_operation_identity_must_be_explicit_nonempty_stable_key(self):
        for key in ["", " ", " cut", "cut ", None, True, 1]:
            with self.subTest(key=key):
                with self.assertRaises(TubeQuantityError):
                    self.calculate(operation_totals={key: 100})

    def test_result_is_frozen_and_caller_operation_totals_are_unchanged(self):
        totals = {"cut": 100, "bend": 200}
        allowance = self.calculate(operation_totals=totals, received=40)
        self.assertEqual(totals, {"cut": 100, "bend": 200})
        with self.assertRaises(FrozenInstanceError):
            allowance.remaining = 999
        totals["cut"] = 0
        self.assertEqual((allowance.reported_minimum, allowance.remaining), (100, 60))


if __name__ == "__main__":
    unittest.main()
