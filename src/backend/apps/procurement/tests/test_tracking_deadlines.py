from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.procurement.tracking_deadlines import coverage_timing
from apps.procurement.tracking_rules import issue_candidates, risk


BEIJING = ZoneInfo('Asia/Shanghai')


class TrackingDeadlinesTests(SimpleTestCase):
    def timing(self, **overrides):
        values = {
            'now': datetime(2026, 11, 6, 10, tzinfo=BEIJING),
            'bom_confirmed_at': datetime(2026, 11, 5, 10, tzinfo=BEIJING),
            'bom_verified': True,
            'scheduled': False,
            'material_inbound_date': None,
            'order_delivery_date': date(2026, 11, 20),
            'category_key': 'TUBE',
            'policy': {'bom_timeout_days': 2, 'category_lead_days': {'TUBE': 2, 'FABRIC': 4}},
        }
        values.update(overrides)
        return coverage_timing(**values)

    def codes(self, result):
        return [item['code'] for item in result['timing_risks']]

    def test_bom_timeout_starts_at_exact_full_days(self):
        due = datetime(2026, 11, 7, 10, tzinfo=BEIJING)
        for offset, expected in [(-1, []), (0, ['BOM_PURCHASE_TIMEOUT']), (1, ['BOM_PURCHASE_TIMEOUT'])]:
            with self.subTest(seconds=offset):
                result = self.timing(now=due + timedelta(seconds=offset))
                self.assertEqual(result['bom_purchase_due_at'], due.isoformat())
                self.assertEqual(self.codes(result), expected)

    def test_unverified_bom_does_not_start_timeout(self):
        result = self.timing(bom_verified=False, bom_confirmed_at=datetime(2026, 1, 1, tzinfo=BEIJING))
        self.assertIsNone(result['bom_purchase_due_at'])
        self.assertEqual(self.codes(result), [])

    def test_verified_bom_without_aware_confirmation_time_is_unknown(self):
        for confirmed_at in [None, datetime(2026, 11, 5, 10)]:
            with self.subTest(confirmed_at=confirmed_at):
                result = self.timing(bom_confirmed_at=confirmed_at)
                self.assertIsNone(result['bom_purchase_due_at'])
                self.assertEqual(self.codes(result), ['BOM_CONFIRMATION_UNKNOWN'])

    def test_unscheduled_demand_needs_no_schedule_date_or_category_lead(self):
        result = self.timing(category_key=None, policy={'bom_timeout_days': 2, 'category_lead_days': {}})
        self.assertIsNone(result['latest_purchase_date'])
        self.assertIsNone(result['purchase_days_remaining'])
        self.assertEqual(self.codes(result), [])

    def test_scheduled_deadline_uses_category_lead_days(self):
        for category, expected_date, expected_days in [('TUBE', '2026-11-09', 3), ('FABRIC', '2026-11-07', 1)]:
            with self.subTest(category=category):
                result = self.timing(scheduled=True, material_inbound_date=date(2026, 11, 11), category_key=category)
                self.assertEqual(result['latest_purchase_date'], expected_date)
                self.assertEqual(result['purchase_days_remaining'], expected_days)
                self.assertEqual(result['timing_risks'], [risk('PURCHASE_UPCOMING', f'还剩{expected_days}天采购')])

    def test_scheduled_deadline_boundary_levels(self):
        for inbound, code, level, rank, remaining in [
            (date(2026, 11, 7), 'PURCHASE_OVERDUE', 'danger', 110, -1),
            (date(2026, 11, 8), 'PURCHASE_DUE_TODAY', 'danger', 100, 0),
            (date(2026, 11, 9), 'PURCHASE_UPCOMING', 'info', 40, 1),
        ]:
            with self.subTest(code=code):
                result = self.timing(scheduled=True, material_inbound_date=inbound)
                self.assertEqual(self.codes(result), [code])
                self.assertEqual(result['purchase_days_remaining'], remaining)
                self.assertEqual((result['timing_risks'][0]['level'], result['timing_risks'][0]['rank']), (level, rank))

    def test_purchase_days_use_beijing_date_even_when_clock_is_utc(self):
        result = self.timing(now=datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc), scheduled=True,
            material_inbound_date=date(2026, 11, 8))
        self.assertEqual(result['purchase_days_remaining'], 0)
        self.assertEqual(self.codes(result), ['PURCHASE_DUE_TODAY'])

    def test_bom_elapsed_days_remain_24_hours_across_timezone_changes(self):
        confirmed = datetime(2026, 10, 31, 12, tzinfo=ZoneInfo('America/New_York'))
        due = datetime(2026, 11, 2, 0, tzinfo=BEIJING)
        result = self.timing(bom_confirmed_at=confirmed, now=due,
            policy={'bom_timeout_days': 1, 'category_lead_days': {'TUBE': 2}})
        self.assertEqual(datetime.fromisoformat(result['bom_purchase_due_at']), due)
        self.assertEqual(self.codes(result), ['BOM_PURCHASE_TIMEOUT'])

    def test_zero_days_is_configured_and_effective_immediately(self):
        now = datetime(2026, 11, 6, 10, tzinfo=BEIJING)
        result = self.timing(now=now, bom_confirmed_at=now, scheduled=True,
            material_inbound_date=now.date(), policy={'bom_timeout_days': 0, 'category_lead_days': {'TUBE': 0}})
        self.assertEqual(result['bom_purchase_due_at'], now.isoformat())
        self.assertEqual(result['latest_purchase_date'], '2026-11-06')
        self.assertEqual(self.codes(result), ['PURCHASE_DUE_TODAY', 'BOM_PURCHASE_TIMEOUT'])

    def test_missing_schedule_and_order_dates_are_separate_warnings(self):
        result = self.timing(scheduled=True, order_delivery_date=None)
        self.assertCountEqual(self.codes(result), ['SCHEDULE_DATE_UNKNOWN', 'ORDER_DELIVERY_UNKNOWN'])
        self.assertIsNone(result['latest_purchase_date'])
        self.assertTrue(all(item['level'] == 'warning' and item['rank'] == 95 for item in result['timing_risks']))

    def test_unscheduled_missing_order_delivery_still_warns(self):
        result = self.timing(order_delivery_date=None)
        self.assertEqual(self.codes(result), ['ORDER_DELIVERY_UNKNOWN'])

    def test_missing_or_invalid_bom_timeout_is_not_guessed(self):
        for value in [None, -1, 366, True, '2', 1.5]:
            with self.subTest(days=value):
                result = self.timing(policy={'bom_timeout_days': value, 'category_lead_days': {'TUBE': 2}})
                self.assertEqual(self.codes(result), ['PURCHASE_RULE_UNKNOWN'])
                self.assertIsNone(result['bom_purchase_due_at'])

    def test_missing_or_invalid_category_rule_keeps_latest_date_unknown(self):
        for category, lead_days in [(None, {'TUBE': 2}), ('TUBE', {}), ('TUBE', {'TUBE': None}),
                                   ('TUBE', {'TUBE': True}), ('TUBE', {'TUBE': -1}), ('TUBE', {'TUBE': 366}),
                                   ('UNKNOWN', {'UNKNOWN': 2})]:
            with self.subTest(category=category, lead_days=lead_days):
                result = self.timing(scheduled=True, material_inbound_date=date(2026, 11, 8),
                    category_key=category, policy={'bom_timeout_days': 2, 'category_lead_days': lead_days})
                self.assertEqual(self.codes(result), ['PURCHASE_RULE_UNKNOWN'])
                self.assertIsNone(result['latest_purchase_date'])
                self.assertIsNone(result['purchase_days_remaining'])

    def test_missing_rules_are_deduplicated_without_hiding_other_warnings(self):
        result = self.timing(scheduled=True, bom_confirmed_at=None, order_delivery_date=None,
            policy={'bom_timeout_days': None, 'category_lead_days': {}})
        self.assertCountEqual(self.codes(result), ['BOM_CONFIRMATION_UNKNOWN', 'PURCHASE_RULE_UNKNOWN',
            'SCHEDULE_DATE_UNKNOWN', 'ORDER_DELIVERY_UNKNOWN'])
        self.assertEqual(len(self.codes(result)), len(set(self.codes(result))))

    def test_multiple_risks_keep_overdue_above_unknown_and_bom_timeout(self):
        result = self.timing(scheduled=True, bom_confirmed_at=datetime(2026, 11, 1, tzinfo=BEIJING),
            material_inbound_date=date(2026, 11, 5), order_delivery_date=None)
        self.assertEqual(self.codes(result), ['PURCHASE_OVERDUE', 'ORDER_DELIVERY_UNKNOWN', 'BOM_PURCHASE_TIMEOUT'])

    def test_naive_now_is_rejected_instead_of_using_server_timezone(self):
        with self.assertRaises(ValueError):
            self.timing(now=datetime(2026, 11, 6, 10))


class TrackingDeadlineCandidateTests(SimpleTestCase):
    def candidates(self, risks, *, scheduled=False, history=False):
        return issue_candidates([{'row_key': 'product-1:material-1', 'production_task_id': 'task-1',
            'scheduled': scheduled, 'is_history': history, 'risks': risks}], 'coverage')

    def test_unscheduled_bom_timeout_can_remind(self):
        candidates = self.candidates([risk('PENDING_PURCHASE'), risk('BOM_PURCHASE_TIMEOUT')])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['code'], 'BOM_PURCHASE_TIMEOUT')
        self.assertEqual(candidates[0]['rank'], 90)

    def test_future_purchase_deadline_does_not_send_notification(self):
        self.assertEqual(self.candidates([risk('PURCHASE_UPCOMING')], scheduled=True), [])

    def test_new_mode_scheduled_status_does_not_send_notification_before_deadline(self):
        status = {**risk('SCHEDULED_UNPURCHASED'), 'level': 'info', 'rank': 30}
        self.assertEqual(self.candidates([status, risk('PURCHASE_UPCOMING')], scheduled=True), [])

    def test_missing_timing_data_can_remind_without_schedule(self):
        for code in ['BOM_CONFIRMATION_UNKNOWN', 'PURCHASE_RULE_UNKNOWN', 'ORDER_DELIVERY_UNKNOWN']:
            with self.subTest(code=code):
                candidates = self.candidates([risk(code)])
                self.assertEqual(candidates[0]['code'], code)

    def test_timing_candidates_keep_history_excluded_and_choose_highest_rank(self):
        risks = [risk('BOM_PURCHASE_TIMEOUT'), risk('PURCHASE_OVERDUE')]
        self.assertEqual(self.candidates(risks, scheduled=True, history=True), [])
        self.assertEqual(self.candidates(risks, scheduled=True)[0]['code'], 'PURCHASE_OVERDUE')

    def test_legacy_scheduled_rules_still_require_schedule(self):
        for code in ['SCHEDULED_UNPURCHASED', 'SCHEDULED_SHORT', 'DEMAND_UNKNOWN', 'DEMAND_CHANGED']:
            with self.subTest(code=code):
                self.assertEqual(self.candidates([risk(code)]), [])
                self.assertEqual(self.candidates([risk(code)], scheduled=True)[0]['code'], code)
