from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied

from apps.access_control.module_policy import action_permission
from apps.workshop_mobile import selectors
from apps.workshop_mobile.semi_receipts import SEMI_RECEIPT_ADD, SEMI_RECEIPT_VIEW, semi_receipt_products
from apps.workshop_mobile.views import require_mobile_access

from . import test_finished_receipt_entry as fixtures


class SemiReceiptEntryTests(SimpleTestCase):
    card = fixtures.FinishedReceiptEntryTests.card

    def test_erp_preview_and_create_sources_are_intersected_without_changing_original_context(self):
        original_view = SimpleNamespace(action='list', action_permission_map={'list': selectors.REPORT_VIEW})
        snapshot = {'active': True, 'actions': {selectors.REPORT_VIEW: {'scopes': ['MODULE']}}}
        request = SimpleNamespace(method='GET', user=object(), employee=object(),
                                  parser_context={'view': original_view}, _sales_access_snapshot=snapshot)
        for category in ('METAL', 'SEWING'):
            with self.subTest(category=category):
                read_sources, write_sources = Mock(), Mock()
                with patch('apps.workshop_mobile.semi_receipts.receipt_plans_for_category',
                           side_effect=[read_sources, write_sources]) as sources:
                    result = semi_receipt_products(request, category)
                read_request, read_category = sources.call_args_list[0].args
                write_request, write_category = sources.call_args_list[1].args
                self.assertEqual((read_category, write_category), (category, category))
                self.assertEqual(action_permission(read_request, read_request.parser_context['view']), SEMI_RECEIPT_VIEW)
                self.assertEqual(action_permission(write_request, write_request.parser_context['view']), SEMI_RECEIPT_ADD)
                for scoped in (read_request, write_request):
                    self.assertIsNot(scoped, request)
                    self.assertIs(scoped.user, request.user)
                    self.assertIs(scoped.employee, request.employee)
                    self.assertFalse(hasattr(scoped, '_sales_access_snapshot'))
                self.assertIs(request.parser_context['view'], original_view)
                self.assertIs(request._sales_access_snapshot, snapshot)
                read_sources.values.assert_called_once_with('pk')
                write_sources.filter.assert_called_once_with(pk__in=read_sources.values.return_value)
                self.assertIs(result, write_sources.filter.return_value)

    def test_neither_add_nor_view_can_be_borrowed_from_other_permissions(self):
        for grants in ({SEMI_RECEIPT_VIEW}, {SEMI_RECEIPT_ADD}, {selectors.ISSUE_VIEW, selectors.REPORT_ADD},
                       {selectors.FINISHED_RECEIPT_ADD}):
            with self.subTest(grants=grants):
                queryset = Mock()
                with patch.object(selectors.module_policy, 'has_permission', side_effect=lambda _request, code: code in grants), \
                        patch.object(selectors, 'semi_receipt_products') as sources:
                    result = selectors.links_for_permission(queryset, SimpleNamespace(), SEMI_RECEIPT_ADD)
                self.assertIs(result, queryset.none.return_value)
                sources.assert_not_called()

    def test_links_bind_category_to_its_own_source_and_keep_add_workshop_scope(self):
        queryset = Mock()
        metal, sewing = object(), object()
        with patch.object(selectors.module_policy, 'has_permission', return_value=True), \
                patch.object(selectors, 'semi_receipt_products', side_effect=[metal, sewing]) as sources, \
                patch.object(selectors.resource_scopes, 'enforcing', return_value=True), \
                patch.object(selectors.resource_scopes, 'resource_ids', return_value={'metal-workshop'}) as resource_ids, \
                patch.object(selectors.resource_scopes, 'has_legacy_permission', return_value=False):
            result = selectors.links_for_permission(queryset, SimpleNamespace(), SEMI_RECEIPT_ADD)
        self.assertEqual([call.args[1] for call in sources.call_args_list], ['METAL', 'SEWING'])
        category_filter = queryset.filter.call_args.args[0]
        self.assertEqual(category_filter.connector, 'OR')
        self.assertEqual(category_filter.children[0].children, [('plan_category', 'METAL'), ('schedule_product__in', metal)])
        self.assertEqual(category_filter.children[1].children, [('plan_category', 'SEWING'), ('schedule_product__in', sewing)])
        self.assertEqual(resource_ids.call_args.args[1:], (SEMI_RECEIPT_ADD, 'WORKSHOP'))
        self.assertEqual(queryset.filter.return_value.filter.call_args.args[0].children,
                         [('craft__workshop_id__in', {'metal-workshop'})])
        self.assertIs(result, queryset.filter.return_value.filter.return_value)

    def test_receipt_only_mobile_access_requires_the_two_permissions_used_by_erp(self):
        for grants in ({SEMI_RECEIPT_VIEW}, {SEMI_RECEIPT_ADD}, {SEMI_RECEIPT_VIEW, SEMI_RECEIPT_ADD}):
            with self.subTest(grants=grants), patch('apps.workshop_mobile.views.has_permission',
                                                   side_effect=lambda _request, code: code in grants):
                if len(grants) == 2:
                    require_mobile_access(SimpleNamespace())
                else:
                    with self.assertRaises(PermissionDenied):
                        require_mobile_access(SimpleNamespace())

    def test_metal_and_sewing_receipt_cards_do_not_grant_issue_reporting_or_finished_receipt(self):
        for category in ('METAL', 'SEWING'):
            with self.subTest(category=category):
                row = self.card(category=category, receipt_permission=False, semi_permission=True)
                self.assertTrue(row['can_receive_semi'])
                self.assertEqual(row['semi_receipt_reason'], '')
                self.assertFalse(row['can_receive_finished'])
                self.assertFalse(row['can_issue'])
                self.assertFalse(row['can_report'])
                self.assertFalse(row['can_view_reports'])
                self.assertEqual(row['reporting_crafts'], [])
                self.assertIsNone(row['progress'])
                self.assertIsNone(row['product']['image_url'])

    def test_cutting_assembly_ineligible_task_and_missing_source_are_not_semi_receipt_entries(self):
        for fields in ({'category': 'CUTTING'}, {'category': 'ASSEMBLY'}, {'semi_permission': False},
                       {'task_status': 'COMPLETED'}, {'task_status': 'CANCELLED'}):
            with self.subTest(fields=fields):
                parameters = {'category': 'METAL', 'receipt_permission': False, 'semi_permission': True, **fields}
                row = self.card(**parameters)
                self.assertFalse(row['can_receive_semi'])
                self.assertTrue(row['semi_receipt_reason'])
