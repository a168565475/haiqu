"""库存采购追溯的重量与未知值契约；不访问数据库。"""
from contextlib import ExitStack
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

from django.db.models import Q
from django.test import SimpleTestCase

from apps.inventory.api.views import MaterialInventoryViewSet
from apps.inventory.selectors import accepted_material_inbound_totals


class AcceptedMaterialInboundTotalsTests(SimpleTestCase):
    def test_partial_missing_weight_is_unknown_only_for_affected_purchase_line(self):
        known, missing, ordinary = uuid4(), uuid4(), uuid4()
        queryset = MagicMock()
        grouped = queryset.filter.return_value.order_by.return_value.values.return_value
        grouped.annotate.return_value = [
            {'purchase_order_line_id': known, 'total': Decimal('4.1'), 'missing_weight': 0},
            {'purchase_order_line_id': missing, 'total': Decimal('3.2'), 'missing_weight': 1},
            {'purchase_order_line_id': ordinary, 'total': Decimal('6'), 'missing_weight': 0},
        ]
        self.assertEqual(accepted_material_inbound_totals(queryset),
                         {known: Decimal('4.1'), missing: None, ordinary: Decimal('6')})
        queryset.filter.assert_called_once_with(inbound__status='CONFIRMED')
        annotations = grouped.annotate.call_args.kwargs
        roots = Q(calculation_snapshot__contains={"receipt_quantity_mode": "ROOTS"})
        condition = (Q(measurement_kind='PIPE') | Q(calculation_snapshot__measurement_kind='HARDWARE_WEIGHT')) & Q(
            purchase_order_line__source_unit_text__in=['KG', 'kg', '千克'])
        case = annotations['total'].get_source_expressions()[0]
        self.assertEqual(case.cases[0].condition, roots)
        self.assertEqual(case.cases[0].result.get_source_expressions()[0].key_name, 'settlement_weight_kg')
        self.assertEqual(case.cases[1].condition, condition)
        self.assertEqual(case.cases[1].result.name, 'accepted_weight_kg')
        self.assertEqual(case.default.name, 'accepted_quantity')
        self.assertEqual(annotations['missing_weight'].filter, (condition & ~roots & Q(accepted_weight_kg__isnull=True))
            | (roots & ~Q(calculation_snapshot__has_key="settlement_weight_kg")))

    def test_empty_history_has_no_unknown_or_fabricated_totals(self):
        queryset = MagicMock()
        queryset.filter.return_value.order_by.return_value.values.return_value.annotate.return_value = []
        self.assertEqual(accepted_material_inbound_totals(queryset), {})


class OrderPurchaseUnknownWeightResponseTests(SimpleTestCase):
    def rows(self, catalog_mode, total):
        catalog_id, unit_id, line_id = uuid4(), uuid4(), uuid4()
        line = SimpleNamespace(pk=line_id, purchase_order_id=uuid4(), material_catalog_id=catalog_id,
            material_selection_snapshot={}, raw_bar_length_m=Decimal('6'), actual_bar_count=None, actual_purchase_quantity=Decimal('10'),
            source_unit_text='KG', purchase_order=SimpleNamespace(order_number='CG-KG',
                production_task_id=None, production_task_number_snapshot=''))
        catalog = SimpleNamespace(material_catalog_id=catalog_id, unit_id=unit_id, identity_key='identity')
        material = SimpleNamespace(pk=uuid4())
        view = MaterialInventoryViewSet()
        view._catalog_stock = Mock(return_value=catalog if catalog_mode else None)
        view._stock_material = Mock(return_value=material)
        view._accessible_task_ids = Mock(return_value=[])
        request = SimpleNamespace(user=SimpleNamespace(has_perm=lambda permission: True))
        with ExitStack() as stack:
            purchases = stack.enter_context(patch('apps.inventory.api.views.PurchaseOrderLine.objects'))
            if catalog_mode:
                purchases.filter.return_value.select_related.return_value.order_by.return_value = [line]
            else:
                purchases.annotate.return_value.filter.return_value.select_related.return_value.distinct.return_value.order_by.return_value = [line]
            inbounds = stack.enter_context(patch('apps.inventory.api.views.MaterialInboundLine.objects'))
            inbounds.filter.return_value.values.return_value.annotate.return_value.filter.return_value.exists.return_value = False
            stack.enter_context(patch('apps.inventory.api.views.FabricMaterial.objects.filter')).return_value.values_list.return_value = []
            stack.enter_context(patch('apps.inventory.api.views.AccessoryMaterial.objects.filter')).return_value.values_list.return_value = []
            stack.enter_context(patch('apps.inventory.api.views.Exists', return_value=True))
            stack.enter_context(patch('apps.inventory.api.views.purchase_order_access', return_value=Q()))
            stack.enter_context(patch('apps.inventory.catalog_stock_identity.build_catalog_stock_identity',
                                      return_value={'identity_key': 'identity'}))
            stack.enter_context(patch('apps.inventory.api.views.accepted_material_inbound_totals',
                                      return_value={} if total == 'no_history' else {line_id: total}))
            return view.order_purchases(request, pk=str(material.pk)).data['data']

    def test_both_identity_paths_preserve_unknown_weight(self):
        for catalog_mode in (True, False):
            with self.subTest(catalog_mode=catalog_mode):
                row = self.rows(catalog_mode, None)[0]
                self.assertIsNone(row['actual_inbound_quantity'])
                self.assertIsNone(row['pending_inbound_quantity'])
                self.assertEqual(row['purchase_quantity'], '10')

    def test_both_identity_paths_preserve_known_weight_and_empty_history(self):
        for catalog_mode in (True, False):
            for total, actual, pending in ((Decimal('4.1'), '4.1', '5.9'), ('no_history', '0', '10')):
                with self.subTest(catalog_mode=catalog_mode, total=total):
                    row = self.rows(catalog_mode, total)[0]
                    self.assertEqual(row['actual_inbound_quantity'], actual)
                    self.assertEqual(row['pending_inbound_quantity'], pending)

