from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from ..purchase_sheet_pdf import _number, _money, _one_cell_table, build_supplier_purchase_sheet_pdf


class PurchaseSheetPdfTests(SimpleTestCase):
    def test_quantity_keeps_integer_trailing_zeroes(self):
        for value, expected in [('700', '700'), (10, '10'), ('1000.00', '1000'),
                                (Decimal('20.5000'), '20.5'), ('0.0100', '0.01'), ('0', '0')]:
            with self.subTest(value=value):
                self.assertEqual(_number(value), expected)

    def test_invalid_and_missing_numbers_are_safe(self):
        for value in [None, '', 'bad', 'NaN', 'Infinity', '<b>invalid</b>']:
            with self.subTest(value=value):
                self.assertEqual(_number(value), '—')
                self.assertEqual(_money(value), '待结算')
        self.assertEqual(_money('5386'), '5,386.00')

    def test_long_clause_expands_and_splits(self):
        paragraph = Paragraph('合同条款 ' * 400, ParagraphStyle('test', fontSize=10, leading=14))
        table = _one_cell_table(paragraph, 300, min_height=40)
        _, height = table.wrap(300, A4[1])
        self.assertGreater(height, 40)
        self.assertGreater(len(table.split(300, 300)), 1)

    def test_pdf_generation_handles_empty_and_large_snapshots(self):
        sheet = SimpleNamespace(sheet_number='TEST700', version_number=1,
                                content_snapshot={}, line_images=Mock(), seal_image=None)
        sheet.line_images.select_related.return_value.all.return_value = []
        for content in [{}, {'lines': [{'quantity': '700', 'unit_price': '10', 'amount': '7000'}] * 40,
                             'special_instructions': '长条款。' * 600},
                        {'settlement_mode': 'ACTUAL_WEIGHT', 'total_amount': None}]:
            sheet.content_snapshot = content
            with self.subTest(content=bool(content)):
                self.assertTrue(build_supplier_purchase_sheet_pdf(sheet, draft=True).startswith(b'%PDF-'))

    def test_representative_image_follows_line_order(self):
        sheet = SimpleNamespace(sheet_number='TEST', version_number=1,
                                content_snapshot={'lines': [{'source_purchase_order_line_id': 'first'},
                                                            {'source_purchase_order_line_id': 'second'}]})
        with patch('apps.procurement.purchase_sheet_pdf._line_image_paths', return_value={'second': 'b', 'first': 'a'}), \
             patch('apps.procurement.purchase_sheet_pdf._safe_image', return_value=None) as image, \
             patch('apps.procurement.purchase_sheet_pdf._seal_image_path', return_value=None):
            build_supplier_purchase_sheet_pdf(sheet)
        self.assertEqual(image.call_args_list[0].args[0], 'a')
