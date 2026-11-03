from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.outsourcing.plan_purchase_reference import purchase_reference


def bom_line(**values):
    return SimpleNamespace(**{
        'pk': 'bom-line', 'component_identity': 'component', 'fabric_source_line': None,
        'pieces_per_bar': 10, 'cutting_sets_per_product': 2,
        'section': SimpleNamespace(section_type='FABRIC', title='面料类',
                                   bom=SimpleNamespace(order_quantity=Decimal('100'))),
        'material_catalog_id': None, 'unit': '米', 'total_purchase_quantity': '1000',
        'total_consumption': '', 'purchase_consumption': '', **values,
    })


def inbound_line(**values):
    return SimpleNamespace(**{
        'inbound': SimpleNamespace(status='CONFIRMED', purchase_order_id='purchase'),
        'source_unit_text_snapshot': '米', 'material_catalog_id': None,
        'material_selection_snapshot': {}, 'raw_material_information_id': 'raw',
        'accepted_bar_count': 20, 'accepted_quantity': Decimal('1201'),
        'return_quantity': Decimal('10'), **values,
    })


def purchase_line(**values):
    inbounds = values.pop('inbounds', [inbound_line()])
    return SimpleNamespace(**{
        'calculation_snapshot': {'component_identity': 'component', 'raw_material_id': 'raw'},
        'source_bom_line_id_snapshot': None, 'bom_line_id': None, 'bom_line': None,
        'actual_bar_count': 2000, 'actual_purchase_quantity': Decimal('9999'),
        'purchase_order_id': 'purchase', 'material_catalog_id': None, 'material_selection_snapshot': {},
        'material_inbound_lines': SimpleNamespace(all=lambda: inbounds),
        'source_unit_text': '米', **values,
    })


class PlanPurchaseReferenceTests(SimpleTestCase):
    def test_tube_combines_purchase_batches_by_component_and_old_bom_reference(self):
        line = bom_line()
        purchases = [purchase_line(), purchase_line(calculation_snapshot={'raw_material_id': 'raw'},
            bom_line_id='older-bom-line', bom_line=line, inbounds=[inbound_line(accepted_bar_count=5)]),
            purchase_line(calculation_snapshot={'component_identity': 'different'})]
        result = purchase_reference(line, purchases, cutting=False)
        self.assertEqual((result['purchased_quantity'], result['quantity'], result['unit']), ('25', '250', '支'))

    def test_only_confirmed_net_inbound_counts_instead_of_ordered_quantity(self):
        purchases = [purchase_line(inbounds=[
            inbound_line(accepted_bar_count=600), inbound_line(accepted_bar_count=400),
            inbound_line(inbound=SimpleNamespace(status='DRAFT', purchase_order_id='purchase'), accepted_bar_count=900),
        ])]
        result = purchase_reference(bom_line(), purchases, cutting=False)
        self.assertEqual((result['purchased_quantity'], result['quantity']), ('1000', '10000'))
        self.assertIn('采购入库1000根', result['conversion_note'])

    def test_cutting_uses_whole_fabric_per_product_quantity_and_rounds_down(self):
        fabric = bom_line()
        cutting = bom_line(pk='cutting', component_identity='cutting', fabric_source_line=fabric)
        result = purchase_reference(cutting, [purchase_line()], cutting=True)
        self.assertEqual((result['purchased_quantity'], result['quantity'], result['unit']), ('1201', '240', '套'))
        cutting.cutting_sets_per_product = 1
        self.assertEqual(purchase_reference(cutting, [purchase_line()], cutting=True)['quantity'], '120')

    def test_missing_conversion_or_incompatible_purchase_stays_unknown(self):
        fabric = bom_line()
        cutting = bom_line(fabric_source_line=fabric)
        for line, purchases, is_cutting in [
            (fabric, [purchase_line(inbounds=[inbound_line(accepted_bar_count=None)])], False),
            (bom_line(pieces_per_bar=None), [purchase_line()], False),
            (cutting, [purchase_line(source_unit_text='码')], True),
            (fabric, [purchase_line(source_unit_text='箱', inbounds=[inbound_line(source_unit_text_snapshot='箱')])], False),
            (fabric, [purchase_line(inbounds=[inbound_line(raw_material_information_id='different')])], False),
            (bom_line(fabric_source_line=bom_line(total_purchase_quantity='')), [], True),
        ]:
            with self.subTest(cutting=is_cutting, purchases=purchases):
                result = purchase_reference(line, purchases, cutting=is_cutting)
                self.assertIsNone(result['quantity'])
                self.assertTrue(result['conversion_note'])

    def test_complete_source_without_matching_purchase_is_zero(self):
        result = purchase_reference(bom_line(), [], cutting=False)
        self.assertEqual((result['quantity'], result['purchased_quantity']), ('0', '0'))
        result = purchase_reference(bom_line(), [purchase_line(inbounds=[])], cutting=False)
        self.assertEqual(result['quantity'], '0')
        result = purchase_reference(bom_line(), [purchase_line(calculation_snapshot={},
            source_bom_line_id_snapshot='bom-line')], cutting=False)
        self.assertEqual(result['quantity'], '200')
        result = purchase_reference(bom_line(fabric_source_line=bom_line()), [purchase_line(
            calculation_snapshot={}, source_bom_line_id_snapshot='bom-line')], cutting=True)
        self.assertEqual((result['purchased_quantity'], result['quantity']), ('1201', '240'))
