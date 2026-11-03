import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.http import Http404
from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.access_control.module_policy import action_permission
from apps.core.api.exceptions import Conflict
from apps.inventory.models import Warehouse, WarehouseLocation, WarehouseZone
from apps.workshop_mobile import selectors
from apps.workshop_mobile.finished_receipts import FINISHED_RECEIPT_ADD, finished_receipt_options, finished_receipt_products
from apps.workshop_mobile.serializers import MobileFinishedReceiptLocationSerializer
from apps.workshop_mobile.views import MobileFinishedReceiptOptionsView, require_mobile_access


class FinishedReceiptEntryTests(SimpleTestCase):
    def test_receipt_source_uses_independent_real_erp_action_without_reusing_scope_cache(self):
        original_view = SimpleNamespace(action='list', action_permission_map={'list': selectors.ISSUE_VIEW})
        snapshot = {'active': True, 'actions': {selectors.ISSUE_VIEW: {'scopes': ['MODULE']}}}
        request = SimpleNamespace(method='GET', user=object(), employee=object(),
                                  parser_context={'view': original_view}, _sales_access_snapshot=snapshot)
        with patch('apps.workshop_mobile.finished_receipts.receipt_plans_for_category') as sources:
            result = finished_receipt_products(request)
        scoped, category = sources.call_args.args
        self.assertIs(result, sources.return_value)
        self.assertEqual(category, 'ASSEMBLY')
        self.assertIsNot(scoped, request)
        self.assertIs(scoped.user, request.user)
        self.assertIs(scoped.employee, request.employee)
        self.assertEqual(action_permission(scoped, scoped.parser_context['view']), FINISHED_RECEIPT_ADD)
        self.assertFalse(hasattr(scoped, '_sales_access_snapshot'))
        self.assertIs(request.parser_context['view'], original_view)
        self.assertIs(request._sales_access_snapshot, snapshot)

    def test_issue_and_report_permissions_never_grant_finished_receipt_access(self):
        request, queryset = SimpleNamespace(), Mock()
        with patch.object(selectors.module_policy, 'has_permission', return_value=False), \
                patch.object(selectors, 'finished_receipt_products') as products:
            result = selectors.links_for_permission(queryset, request, FINISHED_RECEIPT_ADD)
        self.assertIs(result, queryset.none.return_value)
        products.assert_not_called()

    def test_receipt_links_require_both_erp_visible_assembly_sources_and_receipt_workshop_scope(self):
        queryset = Mock()
        scoped = queryset.filter.return_value
        product_sources = object()
        with patch.object(selectors.module_policy, 'has_permission', return_value=True), \
                patch.object(selectors, 'finished_receipt_products', return_value=product_sources), \
                patch.object(selectors.resource_scopes, 'enforcing', return_value=True), \
                patch.object(selectors.resource_scopes, 'resource_ids', return_value={'assembly-workshop'}) as resource_ids, \
                patch.object(selectors.resource_scopes, 'has_legacy_permission', return_value=False):
            result = selectors.links_for_permission(queryset, SimpleNamespace(), FINISHED_RECEIPT_ADD)
        queryset.filter.assert_called_once_with(plan_category='ASSEMBLY', schedule_product__in=product_sources)
        resource_ids.assert_called_once()
        self.assertEqual(resource_ids.call_args.args[1:], (FINISHED_RECEIPT_ADD, 'WORKSHOP'))
        self.assertEqual(scoped.filter.call_args.args[0].children, [('craft__workshop_id__in', {'assembly-workshop'})])
        self.assertIs(result, scoped.filter.return_value)

    def test_mobile_visibility_includes_receipt_sources_without_granting_other_actions(self):
        base = Mock()
        allowed = {code: Mock() for code in (selectors.ISSUE_VIEW, selectors.REPORT_VIEW, FINISHED_RECEIPT_ADD, selectors.SEMI_RECEIPT_ADD)}
        with patch.object(selectors, 'plan_links', return_value=base), \
                patch.object(selectors, 'links_for_permission', side_effect=lambda _base, _request, code: allowed[code]):
            selectors.visible_plan_links(SimpleNamespace())
        selected = base.filter.call_args.args[0]
        self.assertEqual(selected.connector, 'OR')
        self.assertEqual({id(value) for field, value in selected.children if field == 'pk__in'},
                         {id(row.values.return_value) for row in allowed.values()})

    def card(self, *, category='ASSEMBLY', task_status='IN_PRODUCTION', receipt_permission=True, semi_permission=False):
        workshop = SimpleNamespace(pk=uuid.uuid4(), name='装配车间')
        product = SimpleNamespace(pk=uuid.uuid4(), product_name_snapshot='产品', product_number_snapshot='P001',
            specification_snapshot='', color_name_snapshot='', material_snapshot='')
        task = SimpleNamespace(pk=uuid.uuid4(), task_number='TASK-UNIT', status=task_status,
                               get_status_display=lambda: task_status)
        source = SimpleNamespace(pk=uuid.uuid4(), schedule_id=uuid.uuid4(), product_line_id=product.pk,
            schedule=SimpleNamespace(production_task=task, schedule_number='PLAN-UNIT'), product_line=product,
            product_snapshot={}, planned_quantity=Decimal('100'), source_quantity_snapshot=Decimal('100'),
            unit_name_snapshot='件', metal_return_date=None, sewing_return_date=None, finished_inbound_date=None)
        link = SimpleNamespace(pk=uuid.uuid4(), schedule_product_id=source.pk, schedule_product=source,
            plan_category=category, craft=SimpleNamespace(workshop=workshop, workshop_id=workshop.pk))
        queryset = Mock()
        queryset.filter.return_value = queryset
        queryset.select_related.return_value.prefetch_related.return_value.order_by.return_value = [link]

        def permission_links(_queryset, _request, code):
            rows = Mock()
            permitted = (receipt_permission and code == FINISHED_RECEIPT_ADD) or (semi_permission and code == selectors.SEMI_RECEIPT_ADD)
            rows.values_list.return_value = [link.pk] if permitted else []
            return rows

        key = {'schedule_product_id': source.pk, 'plan_category': category, 'craft__workshop_id': workshop.pk}
        with patch.object(selectors, 'visible_plan_links', return_value=queryset), \
                patch.object(selectors, 'links_for_permission', side_effect=permission_links), \
                patch.object(selectors, 'production_task_product_image', return_value=SimpleNamespace(content_type='image/png')):
            return selectors.mobile_plan_data(SimpleNamespace(), [key], production_date=date(2026, 11, 2))[0]

    def test_receipt_only_card_does_not_reveal_report_details_or_unusable_image_urls(self):
        row = self.card()
        self.assertTrue(row['can_receive_finished'])
        self.assertEqual(row['finished_receipt_reason'], '')
        self.assertFalse(row['can_issue'])
        self.assertFalse(row['can_report'])
        self.assertFalse(row['can_view_reports'])
        self.assertEqual(row['reporting_crafts'], [])
        self.assertIsNone(row['progress'])
        self.assertIsNone(row['product']['image_url'])

    def test_receipt_entry_requires_assembly_permission_and_in_production_task(self):
        for fields in ({'category': 'CUTTING'}, {'category': 'SEWING'}, {'receipt_permission': False},
                       {'task_status': 'COMPLETED'}, {'task_status': 'CANCELLED'}):
            with self.subTest(fields=fields):
                row = self.card(**fields)
                self.assertFalse(row['can_receive_finished'])
                self.assertTrue(row['finished_receipt_reason'])

    def test_receipt_only_permission_can_enter_mobile_but_write_permissions_from_other_modules_cannot(self):
        for granted in (FINISHED_RECEIPT_ADD, selectors.ISSUE_ADD, selectors.REPORT_ADD):
            with self.subTest(granted=granted), patch('apps.workshop_mobile.views.has_permission',
                                                     side_effect=lambda _request, code: code == granted):
                if granted == FINISHED_RECEIPT_ADD:
                    require_mobile_access(SimpleNamespace())
                else:
                    with self.assertRaises(PermissionDenied):
                        require_mobile_access(SimpleNamespace())


class FinishedReceiptOptionsTests(SimpleTestCase):
    def request(self, **query):
        return SimpleNamespace(query_params=query)

    def test_options_reject_missing_add_permission_before_accessing_sources_or_locations(self):
        with patch('apps.workshop_mobile.views.has_permission', return_value=False), \
                patch('apps.workshop_mobile.views.finished_receipt_products') as sources, \
                patch('apps.workshop_mobile.views.finished_receipt_options') as options:
            with self.assertRaises(PermissionDenied):
                MobileFinishedReceiptOptionsView().get(self.request(schedule_product_id=str(uuid.uuid4())))
        sources.assert_not_called()
        options.assert_not_called()

    def test_options_validate_source_id_before_reading_business_data(self):
        with patch('apps.workshop_mobile.views.has_permission', return_value=True), \
                patch('apps.workshop_mobile.views.finished_receipt_products') as sources:
            for query in ({}, {'schedule_product_id': 'invalid'}):
                with self.subTest(query=query), self.assertRaises(ValidationError):
                    MobileFinishedReceiptOptionsView().get(self.request(**query))
        sources.assert_not_called()

    def test_inaccessible_and_non_production_sources_do_not_reveal_location_options(self):
        with patch('apps.workshop_mobile.views.has_permission', return_value=True), \
                patch('apps.workshop_mobile.views.finished_receipt_products'), \
                patch('apps.workshop_mobile.views.get_object_or_404') as get_plan, \
                patch('apps.workshop_mobile.views.finished_receipt_options') as options:
            get_plan.side_effect = Http404
            with self.assertRaises(Http404):
                MobileFinishedReceiptOptionsView().get(self.request(schedule_product_id=str(uuid.uuid4())))
            get_plan.side_effect = None
            get_plan.return_value = SimpleNamespace(schedule=SimpleNamespace(production_task=SimpleNamespace(status='COMPLETED')))
            with self.assertRaises(Conflict):
                MobileFinishedReceiptOptionsView().get(self.request(schedule_product_id=str(uuid.uuid4())))
        options.assert_not_called()

    def test_authorized_source_returns_only_receiving_options_without_inventory_view_permission(self):
        selected = uuid.uuid4()
        request = self.request(schedule_product_id=str(selected))
        data = {'warehouses': [], 'zones': [], 'locations': []}
        with patch('apps.workshop_mobile.views.has_permission', side_effect=lambda _request, code: code == FINISHED_RECEIPT_ADD), \
                patch('apps.workshop_mobile.views.finished_receipt_products') as sources, \
                patch('apps.workshop_mobile.views.get_object_or_404', return_value=SimpleNamespace(
                    schedule=SimpleNamespace(production_task=SimpleNamespace(status='IN_PRODUCTION')))) as get_plan, \
                patch('apps.workshop_mobile.views.finished_receipt_options', return_value=data):
            response = MobileFinishedReceiptOptionsView().get(request)
        get_plan.assert_called_once_with(sources.return_value, pk=selected)
        self.assertEqual(response.data, {'data': data})

    def test_options_filter_every_location_parent_to_active_finished_goods_warehouses(self):
        with patch('apps.workshop_mobile.finished_receipts.Warehouse.objects.filter') as warehouses, \
                patch('apps.workshop_mobile.finished_receipts.WarehouseZone.objects.filter') as zones, \
                patch('apps.workshop_mobile.finished_receipts.WarehouseLocation.objects.filter') as locations, \
                patch('apps.workshop_mobile.finished_receipts.locations_with_usage') as with_usage, \
                patch('apps.workshop_mobile.finished_receipts.MobileFinishedReceiptLocationSerializer') as serializer:
            warehouses.return_value.order_by.return_value.values.return_value = []
            zones.return_value.order_by.return_value.values.return_value = []
            serializer.return_value.data = []
            self.assertEqual(finished_receipt_options(), {'warehouses': [], 'zones': [], 'locations': []})
        warehouses.assert_called_once_with(status='ACTIVE', warehouse_type='FINISHED')
        zones.assert_called_once_with(status='ACTIVE', warehouse__status='ACTIVE', warehouse__warehouse_type='FINISHED')
        locations.assert_called_once_with(status='ACTIVE', zone__status='ACTIVE',
            zone__warehouse__status='ACTIVE', zone__warehouse__warehouse_type='FINISHED')
        with_usage.assert_called_once_with(locations.return_value)

    def test_location_remaining_capacity_reuses_erp_rules_and_has_no_inventory_detail(self):
        warehouse = Warehouse(warehouse_number='FIN', warehouse_name='成品仓', warehouse_type='FINISHED', status='ACTIVE')
        zone = WarehouseZone(warehouse=warehouse, zone_name='一区', status='ACTIVE')
        for capacity, occupied, remaining in ((None, 10, None), (20, 7, 13), (10, 15, 0)):
            with self.subTest(capacity=capacity, occupied=occupied):
                location = WarehouseLocation(zone=zone, location_number='A01', status='ACTIVE', capacity_box_slots=capacity)
                location.occupied_box_slots = occupied
                data = MobileFinishedReceiptLocationSerializer(location).data
                self.assertEqual(set(data), {'id', 'zone', 'warehouse_id', 'location_number', 'status', 'remaining_box_slots'})
                self.assertEqual(data['remaining_box_slots'], remaining)
