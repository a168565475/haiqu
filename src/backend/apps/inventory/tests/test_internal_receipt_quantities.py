"""数量内核测试，不创建业务库，不把计算通过当作库存事务通过。"""

import unittest
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import product

from apps.inventory.internal_receipt_quantities import (
    ComponentDemand, InputPool, ReceivedOutput, ReceiptQuantityError,
    calculate_receipt, fabric_input_per_set, net_component_demand, validate_receipt,
)


D = Decimal


class InternalReceiptQuantityTests(unittest.TestCase):
    def setUp(self):
        self.pipe = ComponentDemand('order-a', 'product-a:leg:metal', 'leg-input', '支', '支', D('4000'), D('1'))
        self.pool = InputPool('order-a', 'leg-input', '支', D('1000'))
        self.seat = ComponentDemand('order-a', 'product-a:seat:sewing', 'fabric-input', '米', '套', D('1000'), D('0.6'))
        self.back = ComponentDemand('order-a', 'product-a:back:sewing', 'fabric-input', '米', '套', D('1000'), D('0.4'))
        self.fabric = InputPool('order-a', 'fabric-input', '米', D('100'))

    def calculate(self, *, demands=None, inputs=None, history=(), requested=None, confirm=False):
        function = validate_receipt if confirm else calculate_receipt
        return function(scope_key='order-a', demands=demands or [self.pipe], inputs=inputs or [self.pool],
                        history=history, requested=requested)

    def assert_code(self, code, call):
        with self.assertRaises(ReceiptQuantityError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def receipt(self, demand, quantity):
        return ReceivedOutput(demand.scope_key, demand.component_key, demand.source_key,
                              demand.input_unit, demand.output_unit, D(quantity), D(quantity) * demand.input_per_output)

    def test_order_1000_usage_4_is_exactly_4000(self):
        self.assertEqual(net_component_demand(1000, 4), 4000)

    def test_two_pieces_half_meter_each_make_one_meter_per_set(self):
        self.assertEqual(fabric_input_per_set(2, '0.5'), 1)

    def test_database_decimal_trailing_zeroes_are_not_extra_precision(self):
        self.assertEqual(fabric_input_per_set(D('2.0000'), D('0.5000')), 1)
        self.assertEqual(net_component_demand(D('1000.0000'), D('4.0000')), 4000)
        self.assertEqual(fabric_input_per_set('2.00000000', '0.50000000'), 1)

    def test_calculation_output_can_be_used_as_next_receipt_history(self):
        first=self.calculate(demands=[self.seat],inputs=[self.fabric],requested={self.seat.component_key:D('100.0000')})
        row=first.components[self.seat.component_key]
        history=ReceivedOutput('order-a',self.seat.component_key,self.seat.source_key,'米','套',row.requested,row.consumes_input)
        second=self.calculate(demands=[self.seat],inputs=[self.fabric],history=[history])
        self.assertEqual(second.components[self.seat.component_key].can_receive,66)
        self.assertEqual(second.input_remaining_after['fabric-input'],40)

    def test_invalid_unit_types_raise_controlled_error(self):
        for unit in [[], {}, True, None]:
            with self.subTest(unit=unit):
                self.assert_code('IDENTITY_INVALID',lambda:self.calculate(demands=[replace(self.pipe,output_unit=unit)]))
        self.assert_code('UNIT_MISMATCH',lambda:self.calculate(inputs=[replace(self.pool,unit='根')]))

    def test_pieces_are_not_mistaken_for_sets(self):
        demand = replace(self.seat, required=net_component_demand(1000, 1), input_per_output=fabric_input_per_set(2, '0.5'))
        result = self.calculate(demands=[demand], inputs=[self.fabric])
        self.assertEqual(result.components[demand.component_key].can_receive, 100)
        self.assertEqual(result.components[demand.component_key].required, 1000)

    def test_only_issued_1000_supports_1000_even_when_order_needs_4000(self):
        self.assertEqual(self.calculate().components[self.pipe.component_key].can_receive, 1000)
        self.assert_code('INPUT_INSUFFICIENT', lambda:self.calculate(requested={self.pipe.component_key:1001}))

    def test_excess_raw_allowance_does_not_raise_order_cap(self):
        result = self.calculate(inputs=[replace(self.pool, issued=D('4040'))])
        self.assertEqual(result.components[self.pipe.component_key].can_receive, 4000)
        self.assert_code('DEMAND_EXCEEDED', lambda:self.calculate(inputs=[replace(self.pool, issued=D('4040'))], requested={self.pipe.component_key:4001}))

    def test_partial_receipt_and_later_more_input(self):
        history = [self.receipt(self.pipe, 500)]
        first = self.calculate(history=history, requested={self.pipe.component_key:300}, confirm=True)
        row = first.components[self.pipe.component_key]
        self.assertEqual((row.received_after, row.demand_remaining_after, first.input_remaining_after['leg-input']), (800,3200,200))
        later = self.calculate(history=history, inputs=[replace(self.pool, issued=D('2000'))])
        self.assertEqual(later.components[self.pipe.component_key].can_receive, 1500)

    def test_issuing_stock_does_not_reopen_production_receipt_quota(self):
        # 输入只有累计产出，不接受当前仓库余额；后续领出不能删去这4000支历史。
        result = self.calculate(inputs=[replace(self.pool, issued=D('4000'))], history=[self.receipt(self.pipe, 4000)])
        row = result.components[self.pipe.component_key]
        self.assertEqual((row.received,row.can_receive,row.complete_after), (4000,0,True))

    def test_external_handoff_and_reservation_reduce_input(self):
        result = self.calculate(inputs=[replace(self.pool, externally_committed=D('250'))], history=[self.receipt(self.pipe, 200)])
        self.assertEqual(result.components[self.pipe.component_key].can_receive, 550)

    def test_external_commitment_cannot_exceed_issued(self):
        self.assert_code('INPUT_HISTORY_CONFLICT',lambda:self.calculate(inputs=[replace(self.pool, externally_committed=D('1001'))]))

    def test_internal_and_external_total_cannot_exceed_input(self):
        self.assert_code('INPUT_HISTORY_CONFLICT',lambda:self.calculate(inputs=[replace(self.pool, externally_committed=D('501'))],history=[self.receipt(self.pipe,500)]))

    def test_shared_fabric_combined_receipt_uses_exact_100_meters(self):
        result = self.calculate(demands=[self.seat,self.back],inputs=[self.fabric],requested={self.seat.component_key:100,self.back.component_key:100},confirm=True)
        self.assertEqual(result.input_remaining_after['fabric-input'], 0)
        self.assertEqual(result.components[self.seat.component_key].consumes_input, 60)
        self.assertEqual(result.components[self.back.component_key].consumes_input, 40)

    def test_each_component_individually_fits_but_total_must_be_checked(self):
        self.assert_code('SHARED_INPUT_INSUFFICIENT',lambda:self.calculate(demands=[self.seat,self.back],inputs=[self.fabric],requested={self.seat.component_key:150,self.back.component_key:100}))

    def test_unselected_component_history_still_uses_shared_fabric(self):
        result = self.calculate(demands=[self.seat,self.back],inputs=[self.fabric],history=[self.receipt(self.back,100)],requested={self.seat.component_key:100})
        self.assertEqual(result.components[self.seat.component_key].can_receive,100)
        self.assertEqual(result.input_remaining_after['fabric-input'],0)

    def test_distinct_inputs_do_not_borrow_each_others_material(self):
        back = replace(self.back,source_key='other-fabric')
        other = replace(self.fabric,source_key='other-fabric',issued=D('0'))
        self.assert_code('INPUT_INSUFFICIENT',lambda:self.calculate(demands=[self.seat,back],inputs=[self.fabric,other],requested={back.component_key:1}))

    def test_distinct_parts_cannot_borrow_order_quota(self):
        small = replace(self.pipe,component_key='product-a:arm:metal',required=D('2'))
        self.assert_code('DEMAND_EXCEEDED',lambda:self.calculate(demands=[self.pipe,small],requested={small.component_key:3}))

    def test_no_issued_material_means_zero_receivable(self):
        row = self.calculate(inputs=[replace(self.pool,issued=D('0'))]).components[self.pipe.component_key]
        self.assertEqual(row.can_receive,0)

    def test_fractional_capacity_is_floored_not_rounded_up(self):
        result = self.calculate(demands=[replace(self.seat,input_per_output=D('0.3'))],inputs=[replace(self.fabric,issued=D('1'))])
        self.assertEqual(result.components[self.seat.component_key].can_receive,3)

    def test_decimal_calculation_does_not_depend_on_global_precision(self):
        with localcontext() as context:
            context.prec=4
            self.assertEqual(net_component_demand(123456,78),9629568)
            self.assertEqual(fabric_input_per_set(123, '0.1234'), D('15.1782'))
            result=self.calculate(demands=[self.seat],inputs=[self.fabric],requested={self.seat.component_key:123})
        self.assertEqual(result.input_remaining_after['fabric-input'],D('26.2'))

    def test_order_upper_bound_and_usage_overflow(self):
        self.assert_code('QUANTITY_OVERFLOW',lambda:net_component_demand('99999999999999',2))

    def test_reject_bad_quantities_and_fractional_outputs(self):
        for value,code in [(True,'QUANTITY_INVALID'),(1.0,'QUANTITY_INVALID'),('NaN','QUANTITY_INVALID'),('Infinity','QUANTITY_INVALID'),(-1,'QUANTITY_INVALID'),(0,'QUANTITY_INVALID'),('1.1','WHOLE_QUANTITY_REQUIRED'),(None,'QUANTITY_INVALID'),({},'QUANTITY_INVALID')]:
            with self.subTest(value=value):
                self.assert_code(code,lambda:self.calculate(requested={self.pipe.component_key:value}))

    def test_reject_excess_precision_without_rounding(self):
        self.assert_code('QUANTITY_PRECISION',lambda:fabric_input_per_set(2,'0.12345'))

    def test_meters_and_pieces_cannot_be_mixed(self):
        self.assert_code('UNIT_MISMATCH',lambda:self.calculate(inputs=[replace(self.pool,unit='米')]))
        self.assert_code('UNIT_MISMATCH',lambda:self.calculate(demands=[replace(self.pipe,output_unit='套')]))

    def test_pipe_input_cannot_be_counted_as_bars_or_multiple_pieces(self):
        self.assert_code('UNIT_MISMATCH',lambda:self.calculate(demands=[replace(self.pipe,input_unit='根')]))
        self.assert_code('UNIT_MISMATCH',lambda:self.calculate(demands=[replace(self.pipe,input_per_output=D('2'))]))

    def test_cross_order_input_demand_history_are_all_rejected(self):
        for changes in [{'inputs':[replace(self.pool,scope_key='order-b')]},{'demands':[replace(self.pipe,scope_key='order-b')]},{'history':[replace(self.receipt(self.pipe,1),scope_key='order-b')]}]:
            with self.subTest(changes=changes):
                self.assert_code('SCOPE_MISMATCH',lambda:self.calculate(**changes))

    def test_unknown_duplicate_and_missing_identities(self):
        cases=[('DUPLICATE_INPUT',{'inputs':[self.pool,self.pool]}),('DUPLICATE_COMPONENT',{'demands':[self.pipe,self.pipe]}),('INPUT_MISSING',{'demands':[replace(self.pipe,source_key='missing')]}),('COMPONENT_UNKNOWN',{'requested':{'missing':1}}),('IDENTITY_INVALID',{'inputs':[replace(self.pool,source_key='')]})]
        for code,changes in cases:
            with self.subTest(code=code):self.assert_code(code,lambda:self.calculate(**changes))

    def test_history_from_removed_component_cannot_be_silently_ignored(self):
        self.assert_code('HISTORY_UNRESOLVED',lambda:self.calculate(history=[replace(self.receipt(self.pipe,1),component_key='removed')]))

    def test_changed_consumption_and_input_source_require_reconciliation(self):
        history=self.receipt(self.seat,10)
        for change in [{'input_quantity':D('5')},{'source_key':'other-fabric'},{'input_unit':'支'},{'output_unit':'支'}]:
            with self.subTest(change=change):
                self.assert_code('SOURCE_CHANGED',lambda:self.calculate(demands=[self.seat],inputs=[self.fabric],history=[replace(history,**change)]))

    def test_reduced_demand_below_history_is_not_clamped(self):
        self.assert_code('DEMAND_HISTORY_CONFLICT',lambda:self.calculate(demands=[replace(self.pipe,required=D('100'))],history=[self.receipt(self.pipe,101)]))

    def test_empty_preview_allowed_but_empty_confirmation_rejected(self):
        self.assertEqual(self.calculate().components[self.pipe.component_key].requested,0)
        self.assert_code('EMPTY_RECEIPT',lambda:self.calculate(confirm=True))

    def test_bad_payload_containers_report_controlled_error(self):
        for changes in [{'demands':{}},{'inputs':{}},{'history':{}},{'requested':[]},{'demands':[{}]},{'inputs':[{}]},{'history':[{}]}]:
            with self.subTest(changes=changes):
                args=dict(scope_key='order-a',demands=[self.pipe],inputs=[self.pool],history=(),requested={})
                args.update(changes)
                self.assert_code('PAYLOAD_INVALID',lambda:calculate_receipt(**args))

    def test_result_and_source_data_are_not_mutated(self):
        requested={self.pipe.component_key:200}
        result=self.calculate(requested=requested)
        self.assertEqual(requested,{self.pipe.component_key:200})
        self.assertEqual(self.pool.issued,1000)
        with self.assertRaises(TypeError):result.components['fake']=None
        with self.assertRaises(TypeError):result.input_remaining_after['leg-input']=0

    def test_integer_fraction_oracle_for_shared_fabric_boundaries(self):
        # 用Fraction独立核对十进制边界，避免测试只复制实现公式。
        for meters,left,right in product(['0.7','1','2.3'],range(5),range(5)):
            fabric=replace(self.fabric,issued=D(meters))
            requested={k:q for k,q in [(self.seat.component_key,left),(self.back.component_key,right)] if q}
            enough=Fraction(left)*Fraction('0.6')+Fraction(right)*Fraction('0.4')<=Fraction(meters)
            with self.subTest(meters=meters,left=left,right=right):
                if enough:
                    result=self.calculate(demands=[self.seat,self.back],inputs=[fabric],requested=requested)
                    self.assertEqual(Fraction(result.input_remaining_after['fabric-input']),Fraction(meters)-left*Fraction('0.6')-right*Fraction('0.4'))
                else:
                    with self.assertRaises(ReceiptQuantityError) as caught:
                        self.calculate(demands=[self.seat,self.back],inputs=[fabric],requested=requested)
                    self.assertIn(caught.exception.code,{'INPUT_INSUFFICIENT','SHARED_INPUT_INSUFFICIENT'})


if __name__ == '__main__':
    unittest.main()
