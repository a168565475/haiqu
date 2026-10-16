import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.organizations.models import Employee
from apps.reference_data.models import Currency, ExchangeRate


class InitialExchangeRateImportTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'rates.json'
        self.actor = Employee.objects.create(
            employee_code='FX_IMPORT', display_name='汇率初始化',
            user=get_user_model().objects.create_superuser(username='fx_import', password='test-only'),
        )
        self.cny, _ = Currency.objects.get_or_create(code='CNY', defaults={'numeric_code': '156', 'chinese_name': '人民币', 'english_name': 'Yuan'})
        self.usd, _ = Currency.objects.get_or_create(code='USD', defaults={'numeric_code': '840', 'chinese_name': '美元', 'english_name': 'US Dollar'})
        Currency.objects.get_or_create(code='EUR', defaults={'numeric_code': '978', 'chinese_name': '欧元', 'english_name': 'Euro'})
        self.rows = [{'base_currency_code': 'USD', 'quote_currency_code': 'CNY', 'rate': '6.72530000', 'effective_date': '2026-10-15', 'source_name': 'CFETS via Frankfurter', 'source_version': '2026-10-15', 'description': 'https://api.frankfurter.dev/v2/providers/cfets/rate/usd/cny'}]

    def run_import(self, rows=None, **options):
        self.path.write_text(json.dumps({'rates': self.rows if rows is None else rows}), encoding='utf-8')
        output = StringIO()
        call_command('import_initial_exchange_rates', str(self.path), stdout=output, **options)
        return output.getvalue()

    def test_default_only_previews_without_writing(self):
        before = ExchangeRate.objects.count()
        self.run_import()
        self.assertEqual(ExchangeRate.objects.count(), before)

    def test_apply_preserves_eight_places_and_audit_and_is_idempotent(self):
        self.run_import(apply=True, employee_code=self.actor.employee_code)
        record = ExchangeRate.objects.get(base_currency=self.usd, quote_currency=self.cny)
        self.assertEqual(str(record.rate), '6.72530000')
        self.assertEqual(record.entered_by_employee, self.actor)
        self.assertTrue(AuditLog.objects.filter(object_type='EXCHANGE_RATE', object_id=record.pk, action='CREATED').exists())
        self.run_import(apply=True, employee_code=self.actor.employee_code)
        self.assertEqual(ExchangeRate.objects.filter(base_currency=self.usd, quote_currency=self.cny).count(), 1)

    def test_invalid_or_repeated_pair_rejects_whole_batch(self):
        for bad in [{**self.rows[0], 'base_currency_code': 'EUR', 'rate': 'NaN'}, {**self.rows[0], 'base_currency_code': 'EUR', 'rate': '0'}, self.rows[0]]:
            with self.subTest(bad=bad), self.assertRaises(CommandError):
                self.run_import([self.rows[0], bad], apply=True, employee_code=self.actor.employee_code)
            self.assertFalse(ExchangeRate.objects.filter(base_currency=self.usd, quote_currency=self.cny).exists())

    def test_apply_requires_active_authorized_actor(self):
        with self.assertRaises(CommandError):
            self.run_import(apply=True)
        self.actor.user.is_superuser = False
        self.actor.user.save(update_fields=['is_superuser'])
        with self.assertRaises(CommandError):
            self.run_import(apply=True, employee_code=self.actor.employee_code)
        self.assertFalse(ExchangeRate.objects.filter(base_currency=self.usd, quote_currency=self.cny).exists())
