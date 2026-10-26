"""不连接数据库，验证发布与 PDF 输出解耦且保留历史归档引用。"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.db.models import Q
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from .. import purchase_sheet_services as services
from ..models import SupplierPurchaseSheet, SupplierPurchaseSheetStatus


class PurchaseSheetExcelPublishTests(SimpleTestCase):
    def make_sheet(self, **values):
        return SimpleNamespace(**{
            "pk": uuid4(), "sheet_number": "CGDD-test", "version_number": 1,
            "is_current": True, "status": SupplierPurchaseSheetStatus.DRAFT,
            "purchase_order_id": uuid4(), "purchase_request_id": None,
            "supplier_id": uuid4(), "template_version_id": uuid4(),
            "pdf_file_id": None, "total_amount": None,
            "content_snapshot": {"lines": []}, "save": Mock(), **values,
        })

    def test_preparation_validates_and_freezes_without_generating_files(self):
        sheet = self.make_sheet()
        original = sheet.content_snapshot
        normalized = {"lines": [{"amount": "10.0000"}], "total_amount": "10.0000"}
        with patch("apps.procurement.pipe_purchase.validate_pipe_sheet_source") as validate_source, patch.object(
            services, "normalize_sheet_content", return_value=(normalized, Decimal("10.0000")),
        ) as normalize, patch(
            "apps.procurement.purchase_sheet_pdf.build_supplier_purchase_sheet_pdf",
            side_effect=AssertionError("发布不能生成 PDF"),
        ):
            services._prepare_sheet_for_publish(sheet)
        validate_source.assert_called_once_with(sheet)
        normalize.assert_called_once_with(sheet, original, for_publish=True)
        self.assertIs(sheet.content_snapshot, normalized)
        self.assertEqual(sheet.total_amount, Decimal("10.0000"))
        sheet.save.assert_not_called()

    def test_publish_preserves_missing_and_historical_pdf_references(self):
        for legacy_file_id in [None, uuid4()]:
            with self.subTest(legacy_file_id=legacy_file_id):
                sheet = self.make_sheet(pdf_file_id=legacy_file_id, total_amount=Decimal("10"))
                actor, request = object(), object()
                with patch.object(services, "_start_purchasing_if_all_published") as advance, patch.object(
                    services, "write_audit_log",
                ) as audit:
                    result = services._publish_prepared_sheet(sheet, actor, request)
                self.assertIs(result, sheet)
                self.assertEqual(sheet.status, SupplierPurchaseSheetStatus.PUBLISHED)
                self.assertEqual(sheet.pdf_file_id, legacy_file_id)
                self.assertFalse(hasattr(sheet, "pdf_file"))
                self.assertNotIn("pdf_file", sheet.save.call_args.kwargs["update_fields"])
                self.assertIs(sheet.published_by_employee, actor)
                self.assertIsNotNone(sheet.published_at)
                advance.assert_called_once_with(sheet, actor, request)
                self.assertEqual(audit.call_args.kwargs["action"], "PUBLISHED")
                self.assertEqual(audit.call_args.kwargs["after_data"]["pdf_file_id"],
                                 str(legacy_file_id) if legacy_file_id else None)

    def test_batch_validates_all_sheets_before_publishing_any(self):
        sheets = [self.make_sheet(), self.make_sheet(sheet_number="CGDD-invalid")]
        with patch.object(services, "_lock_sheet_purchase_orders"), patch.object(
            services, "_sheet_access_filter", return_value=Q(),
        ), patch.object(SupplierPurchaseSheet.objects, "select_for_update") as select, patch.object(
            services, "_prepare_sheet_for_publish", side_effect=[None, ValidationError("缺少单价")],
        ) as prepare, patch.object(services, "_publish_prepared_sheet") as publish:
            select.return_value.select_related.return_value.filter.return_value.order_by.return_value = sheets
            # 这里只验证批次编排；事务和数据库锁由现有 API 数据库测试覆盖。
            with self.assertRaisesRegex(ValidationError, "缺少单价"):
                services.publish_supplier_purchase_sheets.__wrapped__(
                    sheet_ids=[sheet.pk for sheet in sheets], allowed_task_ids=[],
                    actor_employee=None, request=None,
                )
        self.assertEqual(prepare.call_count, 2)
        publish.assert_not_called()
        self.assertTrue(all(sheet.status == SupplierPurchaseSheetStatus.DRAFT for sheet in sheets))
