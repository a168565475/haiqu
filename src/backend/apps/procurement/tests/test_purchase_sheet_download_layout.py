"""采购合同仅导出 Excel，保留冻结内容、发布限制和历史归档数据。"""

from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4
from zipfile import ZipFile

from django.test import SimpleTestCase
from django.urls import Resolver404, resolve
from rest_framework.exceptions import ValidationError

from ..api.views import SupplierPurchaseSheetViewSet
from ..models import SupplierPurchaseSheetStatus


class PurchaseSheetExcelDownloadTests(SimpleTestCase):
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
        self.request = SimpleNamespace(query_params={}, data={"ids": [str(self.sheet.pk)]})

    def test_xlsx_download_keeps_snapshot_and_historical_pdf_reference(self):
        before = deepcopy(vars(self.sheet))
        with patch("apps.procurement.api.views.build_supplier_purchase_sheet_xlsx", return_value=b"xlsx") as build:
            response = self.view.download_xlsx(self.request)
        self.assertEqual(response.content, b"xlsx")
        self.assertIn("CGDD-test_V1.xlsx", response["Content-Disposition"])
        build.assert_called_once_with(self.sheet)
        self.assertEqual(vars(self.sheet), before)

    def test_batch_uses_same_renderer_and_scoped_published_query(self):
        self.sheet.pdf_file_id = None
        with patch("apps.procurement.api.views.build_supplier_purchase_sheet_xlsx", return_value=b"xlsx") as build:
            response = self.view.batch_download(self.request)
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual(archive.namelist(), ["CGDD-test_V1.xlsx"])
            self.assertEqual(archive.read("CGDD-test_V1.xlsx"), b"xlsx")
        build.assert_called_once_with(self.sheet)
        self.view.get_queryset.return_value.filter.assert_called_once_with(
            pk__in=[self.sheet.pk], status=SupplierPurchaseSheetStatus.PUBLISHED,
        )

    def test_pdf_routes_and_permissions_are_removed(self):
        actions = {action.__name__ for action in self.view.get_extra_actions()}
        for action_name, path in [("preview_pdf", "preview-pdf"), ("download_pdf", "download-pdf")]:
            with self.subTest(path=path):
                self.assertNotIn(action_name, actions)
                self.assertNotIn(action_name, self.view.action_permission_map)
                with self.assertRaises(Resolver404):
                    resolve(f"/api/v1/supplier-purchase-sheets/{self.sheet.pk}/{path}/")
        self.assertIn("download_xlsx", actions)
        self.assertIn("batch_download", actions)
        self.assertEqual(self.view.action_permission_map["batch_download"], "procurement.view_purchaseorder")
        self.assertFalse(hasattr(self.view, "_use_current_pdf_layout"))
        self.assertNotIn("schema", self.view.batch_download.kwargs)

    def test_batch_rejects_inaccessible_missing_and_duplicate_records(self):
        self.view.get_queryset.return_value.filter.return_value = []
        with self.assertRaises(ValidationError):
            self.view.batch_download(self.request)
        self.request.data["ids"] *= 2
        with self.assertRaises(ValidationError):
            self.view.batch_download(self.request)

    def test_batch_selection_limits_remain(self):
        for ids in [None, [], "invalid", [str(self.sheet.pk)] * 101, ["invalid"]]:
            with self.subTest(ids=ids):
                self.request.data["ids"] = ids
                with self.assertRaises(ValidationError):
                    self.view.batch_download(self.request)

    def test_xlsx_template_data_error_returns_validation_error(self):
        for code in ("FABRIC", "FOAM_CUTTING", "AUXILIARY", "PLASTIC_PART", "WEBBING_ACTUAL_WEIGHT"):
            with self.subTest(template=code):
                self.sheet.template_version = SimpleNamespace(template=SimpleNamespace(template_code=code))
                self.sheet.content_snapshot["order"] = {"source_type": "PRODUCTION", "sales_order_number": "SO-001"}
                with self.assertRaisesRegex(ValidationError, "生产任务单号"):
                    self.view.download_xlsx(self.request)
                with self.assertRaisesRegex(ValidationError, "CGDD-test 无法导出.*生产任务单号"):
                    self.view.batch_download(self.request)

    def test_xlsx_unexpected_failure_is_not_hidden(self):
        with patch("apps.procurement.api.views.build_supplier_purchase_sheet_xlsx", side_effect=RuntimeError("render failed")):
            for action in [self.view.download_xlsx, self.view.batch_download]:
                with self.assertRaisesRegex(RuntimeError, "render failed"):
                    action(self.request)
