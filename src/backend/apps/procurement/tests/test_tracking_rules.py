from datetime import date, timedelta
from decimal import Decimal

from django.test import SimpleTestCase

from apps.procurement.tracking_rules import arrival_risks, coverage_risks, issue_candidates
from apps.procurement.tracking_selectors import _identity, _materials


class TrackingRulesTests(SimpleTestCase):
    def test_malformed_saved_material_number_stays_unknown_without_query_or_error(self):
        for value in [[], {}, [1], {'invalid': 1}, 123]:
            snapshot = {'raw_material_snapshot': value, 'source_unit_text': 'PCS',
                'section_type_snapshot': 'ACCESSORY', 'calculation_snapshot': {}}
            with self.subTest(value=value):
                materials = _materials([snapshot])
                identity, notes = _identity(snapshot, materials)
                self.assertIsNone(identity)
                self.assertTrue(notes)

    def test_saved_root_count_must_be_a_bounded_positive_integer(self):
        from apps.procurement.tracking_rules import root_count_value
        for value in ['abc', -1, 0, '1.5', None, '1e50', True]:
            self.assertIsNone(root_count_value(value), value)
        self.assertEqual(root_count_value('12'), 12)

    def test_arrival_calendar_boundaries_use_material_category(self):
        today = date(2026, 11, 5)
        for pipe, days, expected in [(True, 6, 'OUTSIDE_WINDOW'), (True, 5, 'NEAR_DUE'),
                                     (False, 4, 'OUTSIDE_WINDOW'), (False, 3, 'NEAR_DUE'),
                                     (False, 0, 'DUE_TODAY'), (True, -1, 'OVERDUE')]:
            with self.subTest(pipe=pipe, days=days):
                risks = arrival_risks(status='SUBMITTED', archived=False, unreceived=Decimal('1'),
                    delivery_date=today + timedelta(days=days), is_pipe=pipe, today=today,
                    return_pending=False, source_reliable=True)
                self.assertEqual([risk['code'] for risk in risks], [expected])

    def test_raw_completion_stops_delivery_but_keeps_return_risk(self):
        risks = arrival_risks(status='COMPLETED', archived=False, unreceived=Decimal('40'),
            delivery_date=date(2026, 10, 1), is_pipe=False, today=date(2026, 11, 5),
            return_pending=True, source_reliable=True)
        self.assertEqual({risk['code'] for risk in risks}, {'ENDED', 'RETURN_PENDING'})

    def test_returns_do_not_reopen_physical_arrival(self):
        risks = arrival_risks(status='PURCHASING', archived=False, unreceived=Decimal('0'),
            delivery_date=date(2026, 10, 1), is_pipe=False, today=date(2026, 11, 5),
            return_pending=True, source_reliable=True)
        self.assertEqual({risk['code'] for risk in risks}, {'ARRIVED', 'RETURN_PENDING'})

    def test_unknown_source_does_not_hide_reliable_overdue_date(self):
        risks = arrival_risks(status='SUBMITTED', archived=False, unreceived=Decimal('5'),
            delivery_date=date(2026, 11, 4), is_pipe=None, today=date(2026, 11, 5),
            return_pending=False, source_reliable=False)
        self.assertEqual({risk['code'] for risk in risks}, {'OVERDUE', 'CLASSIFICATION_UNKNOWN', 'ARRIVAL_UNKNOWN'})

    def test_partial_ordering_keeps_scheduled_risk_at_same_rank(self):
        absent = coverage_risks(required=Decimal('100'), purchased=Decimal('0'), scheduled=True,
                                reliable=True, changed=False, history=False)
        partial = coverage_risks(required=Decimal('100'), purchased=Decimal('20'), scheduled=True,
                                 reliable=True, changed=False, history=False)
        self.assertEqual(absent[0]['code'], 'SCHEDULED_UNPURCHASED')
        self.assertEqual(partial[0]['code'], 'SCHEDULED_SHORT')
        self.assertEqual(absent[0]['rank'], partial[0]['rank'])

    def test_verified_scheduled_shortage_escalates_the_verification_warning(self):
        confirmed = coverage_risks(required=Decimal('100'), purchased=Decimal('10'), scheduled=True,
            reliable=True, changed=False, history=False)[0]
        for changed in [False, True]:
            warning = coverage_risks(required=Decimal('100'), purchased=None, scheduled=True,
                reliable=False, changed=changed, history=False)[0]
            self.assertEqual((warning['level'], warning['rank']), ('warning', 85))
            self.assertEqual((confirmed['level'], confirmed['rank']), ('danger', 90))
            self.assertGreater(confirmed['rank'], warning['rank'])

    def test_issue_candidates_separate_return_and_delivery_and_exclude_ordinary_demand(self):
        row = {'row_key': 'line-1', 'purchase_order_line_id': 'line-1', 'production_task_id': 'task-1',
               'is_history': False, 'risks': [
                   {'code': 'OVERDUE', 'rank': 80}, {'code': 'ARRIVAL_UNKNOWN', 'rank': 65},
                   {'code': 'RETURN_PENDING', 'rank': 75}]}
        issues = issue_candidates([row], 'arrival')
        self.assertEqual({item['source_key'] for item in issues}, {'arrival:line-1', 'return:line-1'})
        self.assertEqual(next(item for item in issues if item['source_key'] == 'arrival:line-1')['code'], 'OVERDUE')
        for scheduled, history in [(False, False), (True, True)]:
            row = {'row_key': 'product-1', 'production_task_id': 'task-1', 'scheduled': scheduled,
                   'is_history': history, 'risks': [{'code': 'DEMAND_UNKNOWN', 'rank': 90}]}
            self.assertEqual(issue_candidates([row], 'coverage'), [])
