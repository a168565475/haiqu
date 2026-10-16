from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.core.api.permissions import BusinessActionPermission
from apps.files.models import FileScanStatus
from apps.sales_orders.api.views import SalesOrderViewSet


@override_settings(SALES_ACCESS_ENABLED=True, MODULE_ACCESS_ENABLED=False)
class SalesOrderProductImagePermissionTests(SimpleTestCase):
    def image_view(self, method, permissions=(), *, active=True):
        request = SimpleNamespace(
            method=method,
            _sales_access_snapshot={
                "active": active,
                "is_superuser": False,
                "actions": {permission: {"scopes": ["OWN"]} for permission in permissions},
                "legacy_sources": [],
            },
        )
        view = SalesOrderViewSet()
        view.action = "product_image"
        view.request = request
        return request, view

    def test_read_permission_allows_get_and_head_with_read_scope(self):
        for method in ("GET", "HEAD"):
            with self.subTest(method=method):
                request, view = self.image_view(method, ["sales_orders.view_salesorder"])
                self.assertTrue(BusinessActionPermission().has_permission(request, view))
                self.assertEqual(view.scope_permission(), "sales_orders.view_salesorder")

    def test_read_permission_does_not_allow_image_changes(self):
        for method in ("POST", "DELETE"):
            with self.subTest(method=method):
                request, view = self.image_view(method, ["sales_orders.view_salesorder"])
                self.assertFalse(BusinessActionPermission().has_permission(request, view))
                self.assertEqual(view.scope_permission(), "sales_orders.change_salesorder")

    def test_change_permission_still_allows_upload_and_delete(self):
        for method in ("POST", "DELETE"):
            with self.subTest(method=method):
                request, view = self.image_view(method, ["sales_orders.change_salesorder"])
                self.assertTrue(BusinessActionPermission().has_permission(request, view))

    def test_missing_permission_or_inactive_employee_cannot_read_image(self):
        for method in ("GET", "HEAD"):
            for permissions, active in (([], True), (["sales_orders.view_salesorder"], False)):
                with self.subTest(method=method, active=active):
                    request, view = self.image_view(method, permissions, active=active)
                    self.assertFalse(BusinessActionPermission().has_permission(request, view))

    def test_head_reads_image_without_requiring_write_preconditions(self):
        request, view = self.image_view("HEAD", ["sales_orders.view_salesorder"])
        image = SimpleNamespace(
            scan_status=FileScanStatus.CLEAN,
            storage_key="tests/product.png",
            content_type="image/png",
        )
        order = SimpleNamespace(lines=SimpleNamespace(select_related=lambda *args: object()))
        with (
            patch.object(view, "get_object", return_value=order),
            patch("apps.sales_orders.api.views.get_object_or_404", return_value=SimpleNamespace(product_image=image)),
            patch("apps.sales_orders.api.views.Path.is_file", return_value=True),
            patch("apps.sales_orders.api.views.Path.open", return_value=BytesIO(b"image bytes")),
            patch(
                "apps.sales_orders.api.views.require_matching_etag",
                side_effect=AssertionError("读取图片不应进入写入并发校验"),
            ) as require_etag,
        ):
            response = view.product_image(request, pk="order", line_id="line")
            try:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "image/png")
                require_etag.assert_not_called()
            finally:
                response.close()
