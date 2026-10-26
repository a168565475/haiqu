"""导出当前版式必须保留冻结数据、发布限制和原归档入口。"""

from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4
from zipfile import ZipFile

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from ..api.views import SupplierPurchaseSheetViewSet
from ..models import SupplierPurchaseSheetStatus


class PurchaseSheetDownloadLayoutTests(SimpleTestCase):
    def setUp(self):
        self.sheet = SimpleNamespace(
            pk=uuid4(), sheet_number="CGDD-test", version_number=1,
            status=SupplierPurchaseSheetStatus.PUBLISHED, pdf_file_id=uuid4(),
            content_snapshot={"lines": [{"part_name": "半通", "quantity": "48.0000"}]},
        )
        self.view = SupplierPurchaseSheetViewSet()
        self.view.get_object = Mock(return_value=self.sheet)
        self.view.get_queryset = Mock()
        self.view.get_queryset.return_value.filter.return_value = [self.sheet]
        self.request = SimpleNamespace(query_params={"layout": "current"}, data={"ids": [str(self.sheet.pk)]})

    def test_current_download_renders_snapshot_without_reading_or_replacing_archive(self):
        before = deepcopy(vars(self.sheet))
        with patch("apps.procurement.api.views.build_supplier_purchase_sheet_pdf", return_value=b"%PDF-current") as build:
            response = self.view.download_pdf(self.request)
        self.assertEqual(response.content, b"%PDF-current")
        self.assertIn("CGDD-test_V1.pdf", response["Content-Disposition"])
        build.assert_called_once_with(self.sheet)
        self.assertEqual(vars(self.sheet), before)

    def test_batch_uses_same_renderer_and_scoped_published_query(self):
        with patch("apps.procurement.api.views.build_supplier_purchase_sheet_pdf", return_value=b"%PDF-current") as build:
            response = self.view.batch_download(self.request)
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual(archive.namelist(), ["CGDD-test_V1.pdf"])
            self.assertEqual(archive.read("CGDD-test_V1.pdf"), b"%PDF-current")
        build.assert_called_once_with(self.sheet)
        self.view.get_queryset.return_value.filter.assert_called_once_with(
            pk__in=[self.sheet.pk], status=SupplierPurchaseSheetStatus.PUBLISHED, pdf_file__isnull=False,
        )

    def test_unpublished_or_unready_sheet_cannot_download_current_pdf(self):
        for status, file_id in [(SupplierPurchaseSheetStatus.DRAFT, self.sheet.pdf_file_id),
                                (SupplierPurchaseSheetStatus.PUBLISHED, None)]:
            with self.subTest(status=status, file_id=file_id):
                self.sheet.status, self.sheet.pdf_file_id = status, file_id
                with self.assertRaises(ValidationError), patch("apps.procurement.api.views.build_supplier_purchase_sheet_pdf") as build:
                    self.view.download_pdf(self.request)
                build.assert_not_called()

    def test_invalid_layout_fails_and_default_stays_archived(self):
        self.assertFalse(self.view._use_current_pdf_layout(SimpleNamespace(query_params={})))
        self.assertFalse(self.view._use_current_pdf_layout(SimpleNamespace(query_params={"layout": "archived"})))
        self.request.query_params["layout"] = "invalid"
        for action in [self.view.download_pdf, self.view.batch_download]:
            with self.assertRaises(ValidationError):
                action(self.request)

    def test_batch_rejects_inaccessible_missing_and_duplicate_records(self):
        self.view.get_queryset.return_value.filter.return_value = []
        with self.assertRaises(ValidationError):
            self.view.batch_download(self.request)
        self.request.data["ids"] *= 2
        with self.assertRaises(ValidationError):
            self.view.batch_download(self.request)

    def test_generation_failure_is_not_replaced_with_old_archive(self):
        with patch("apps.procurement.api.views.build_supplier_purchase_sheet_pdf", side_effect=RuntimeError("render failed")):
            with self.assertRaisesRegex(RuntimeError, "render failed"):
                self.view.download_pdf(self.request)
