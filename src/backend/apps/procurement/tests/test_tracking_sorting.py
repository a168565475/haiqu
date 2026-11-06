"""采购提醒列表的纯排序验证；SimpleTestCase 禁止数据库访问。"""
from copy import deepcopy

from django.test import SimpleTestCase, override_settings

from apps.procurement.api.tracking_views import _sort_coverage_rows
from apps.procurement.tracking_rules import risk


@override_settings(PURCHASE_TRACKING_POLICY_ENABLED=True)
class TrackingCoverageSortingTests(SimpleTestCase):
    def row(self, task, due, *codes, suffix='1', scheduled=True, reliable=True, bom_due=None):
        return {
            'production_task_id': task, 'task_number': task, 'row_key': f'{task}:{suffix}',
            'material_name': suffix, 'scheduled': scheduled, 'source_reliable': reliable,
            'latest_purchase_date': due, 'bom_purchase_due_at': bom_due,
            'material_inbound_date': due,
            'risks': [risk(code) for code in codes],
        }

    def ordered_keys(self, rows):
        _sort_coverage_rows(rows)
        return [row['row_key'] for row in rows]

    def test_bom_timeout_does_not_put_later_scheduled_deadline_first(self):
        rows = [self.row('LATER', '2026-11-20', 'BOM_PURCHASE_TIMEOUT', 'PURCHASE_UPCOMING'),
                self.row('EARLIER', '2026-11-07', 'PURCHASE_UPCOMING')]
        self.assertEqual(self.ordered_keys(rows), ['EARLIER:1', 'LATER:1'])

    def test_same_urgency_uses_earlier_deadline_instead_of_order_number(self):
        for code in ('PURCHASE_OVERDUE', 'PURCHASE_UPCOMING'):
            with self.subTest(code=code):
                rows = [self.row('A', '2026-11-05', code), self.row('Z', '2026-11-01', code)]
                self.assertEqual(self.ordered_keys(rows), ['Z:1', 'A:1'])

    def test_deadline_urgency_stays_overdue_then_today_then_future(self):
        rows = [self.row('FUTURE', '2026-11-07', 'BOM_PURCHASE_TIMEOUT', 'PURCHASE_UPCOMING'),
                self.row('TODAY', '2026-11-06', 'PURCHASE_DUE_TODAY'),
                self.row('OVERDUE', '2026-11-05', 'PURCHASE_OVERDUE')]
        self.assertEqual(self.ordered_keys(rows), ['OVERDUE:1', 'TODAY:1', 'FUTURE:1'])

    def test_missing_dates_rules_or_source_stay_ahead_of_future_deadline(self):
        for code, due, reliable in (
            ('SCHEDULE_DATE_UNKNOWN', None, True),
            ('PURCHASE_RULE_UNKNOWN', None, True),
            ('BOM_CONFIRMATION_UNKNOWN', '2026-11-20', True),
            ('ORDER_DELIVERY_UNKNOWN', '2026-11-20', True),
            ('DEMAND_UNKNOWN', '2026-11-20', False),
            ('DEMAND_CHANGED', '2026-11-20', False),
        ):
            with self.subTest(code=code):
                rows = [self.row('FUTURE', '2026-11-07', 'PURCHASE_UPCOMING'),
                        self.row('CHECK', due, code, reliable=reliable)]
                self.assertEqual(self.ordered_keys(rows), ['CHECK:1', 'FUTURE:1'])

    def test_unscheduled_bom_timeout_keeps_existing_priority(self):
        rows = [self.row('FUTURE', '2026-11-07', 'PURCHASE_UPCOMING'),
                self.row('BOM', None, 'BOM_PURCHASE_TIMEOUT', scheduled=False, bom_due='2026-11-05T10:00:00+08:00')]
        self.assertEqual(self.ordered_keys(rows), ['BOM:1', 'FUTURE:1'])

    def test_order_rows_stay_together_before_page_slicing(self):
        urgent = [self.row('URGENT', '2026-11-05', 'PURCHASE_OVERDUE', suffix='00')]
        urgent.extend(self.row('URGENT', '2026-11-20', 'BOM_PURCHASE_TIMEOUT', 'PURCHASE_UPCOMING',
            suffix=f'{index:02d}') for index in range(1, 22))
        rows = [self.row('TODAY', '2026-11-06', 'PURCHASE_DUE_TODAY'), *reversed(urgent)]
        self.ordered_keys(rows)
        first_page, second_page = rows[:20], rows[20:40]
        self.assertEqual([row['production_task_id'] for row in first_page], ['URGENT'] * 20)
        self.assertEqual([row['production_task_id'] for row in second_page], ['URGENT', 'URGENT', 'TODAY'])
        self.assertEqual(rows[0]['row_key'], 'URGENT:00')

    def test_sorting_does_not_change_display_or_notification_risks(self):
        rows = [self.row('LATER', '2026-11-20', 'BOM_PURCHASE_TIMEOUT', 'PURCHASE_UPCOMING'),
                self.row('EARLIER', '2026-11-07', 'PURCHASE_UPCOMING')]
        before = {row['row_key']: deepcopy(row['risks']) for row in rows}
        self.ordered_keys(rows)
        self.assertEqual({row['row_key']: row['risks'] for row in rows}, before)

    @override_settings(PURCHASE_TRACKING_POLICY_ENABLED=False)
    def test_disabled_policy_keeps_legacy_order_number_sort(self):
        rows = [self.row('Z', '2026-11-01', 'PURCHASE_OVERDUE'),
                self.row('A', '2026-11-20', 'PURCHASE_UPCOMING')]
        self.assertEqual(self.ordered_keys(rows), ['A:1', 'Z:1'])
