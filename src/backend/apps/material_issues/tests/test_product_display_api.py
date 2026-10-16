import copy
import uuid
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.files.models import FileScanStatus
from apps.organizations.models import Employee
from apps.production_scheduling.tests import test_production_scheduling_api as scheduling_fixtures
from apps.production_tasks.models import ProductionTaskProductImage

from ..models import MaterialIssue
from ..selectors import material_issues_with_context
from ..api.serializers import MaterialIssueReadSerializer


class MaterialIssueProductDisplayTests(APITestCase):
    def setUp(self):
        super().setUp()
        # 仅复用创建任务及其明确销售来源的 fixture，不继承排产业务测试。
        self.source = scheduling_fixtures.ProductionSchedulingApiTests(methodName="test_user_without_schedule_permission_is_denied")
        self.source.setUp()
        self.user = self.source.user
        self.user.user_permissions.set(Permission.objects.filter(
            content_type__app_label="material_issues", codename="view_materialissue",
        ))
        self.client = self.source.client
        self.task = self.source.task
        self.product = self.source.line
        self.issue = MaterialIssue.objects.create(
            issue_number="LL-DISPLAY-001", client_request_id=uuid.uuid4(), request_payload_hash="display",
            production_task=self.task, product_line=self.product,
            created_by_employee=self.source.employee, updated_by_employee=self.source.employee,
        )

    def eligible(self):
        response = self.client.get("/api/v1/material-issues/eligible-products/", {
            "production_task_id": str(self.task.pk),
        })
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["data"][0]

    def products(self):
        listing = self.client.get("/api/v1/material-issues/")
        detail = self.client.get(f"/api/v1/material-issues/{self.issue.pk}/")
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(detail.status_code, 200, detail.data)
        return [self.eligible(), listing.data["data"][0]["product"], detail.data["data"]["product"]]

    def image_url(self, image):
        return f"/api/v1/material-issues/product-images/{self.task.pk}/{image.pk}/"

    def test_separate_product_fields_preserve_raw_snapshot(self):
        raw = "47*55*79；颜色：酒红色；材质：PE"
        self.product.specification_snapshot = raw
        self.product.color_name_snapshot = "酒红色"
        self.product.material_snapshot = "PE"
        self.product.save(update_fields=["specification_snapshot", "color_name_snapshot", "material_snapshot"])
        for row in self.products():
            self.assertEqual(row["specification"], raw)
            self.assertEqual(row["specification_display"], "47*55*79")
            self.assertEqual(row["material"], "PE")
            self.assertEqual(row["color"], "酒红色")
        self.product.refresh_from_db()
        self.assertEqual(self.product.specification_snapshot, raw)

    def test_unverified_specification_suffix_is_not_removed(self):
        self.product.specification_snapshot = "47*55*79；颜色：其他颜色"
        self.product.material_snapshot = ""
        self.product.save(update_fields=["specification_snapshot", "material_snapshot"])
        for row in self.products():
            self.assertEqual(row["specification_display"], self.product.specification_snapshot)
            self.assertEqual(row["material"], "")

    def test_source_image_is_available_with_only_material_issue_permission(self):
        self.assertFalse(self.user.has_perm("production_scheduling.view_productionschedule"))
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder):
            image = self.source._product_image(folder, "source.png")
            self.source._source_order_image(image)
            for row in self.products():
                self.assertEqual(row["image_file_id"], str(image.pk))
            response = self.client.get(self.image_url(image))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"source.png")
            self.product.refresh_from_db()
            self.assertIsNone(self.product.image_file_id)

    def test_task_primary_and_ordered_gallery_take_priority(self):
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder):
            source_image = self.source._product_image(folder, "source.png")
            self.source._source_order_image(source_image)
            primary = self.source._product_image(folder, "primary.png")
            first = self.source._product_image(folder, "first.png")
            second = self.source._product_image(folder, "second.png")
            ProductionTaskProductImage.objects.create(product_line=self.product, image_file=second, line_number=2)
            ProductionTaskProductImage.objects.create(product_line=self.product, image_file=first, line_number=1)
            self.product.image_file = primary
            self.product.save(update_fields=["image_file"])
            self.assertEqual(self.eligible()["image_file_id"], str(primary.pk))
            self.product.image_file = None
            self.product.save(update_fields=["image_file"])
            self.assertEqual(self.eligible()["image_file_id"], str(first.pk))
            loaded = material_issues_with_context().get(pk=self.issue.pk)
            with self.assertNumQueries(0):
                self.assertEqual(MaterialIssueReadSerializer(loaded).data["product"]["image_file_id"], str(first.pk))

    def test_unrelated_and_mismatched_source_images_are_rejected(self):
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder):
            image = self.source._product_image(folder, "unrelated.png")
            other_task, other_line = self.source.create_task_with_product()
            self.source._source_order_image(image, other_task, other_line)
            self.assertIsNone(self.eligible()["image_file_id"])
            self.assertEqual(self.client.get(self.image_url(image)).status_code, 404)
            self.product.sales_order_delivery_batch_line = other_line.sales_order_delivery_batch_line
            self.product.save(update_fields=["sales_order_delivery_batch_line"])
            self.assertIsNone(self.eligible()["image_file_id"])
            self.assertEqual(self.client.get(self.image_url(image)).status_code, 404)

    def test_picture_requires_permission_and_task_data_scope(self):
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder):
            image = self.source._product_image(folder, "source.png")
            self.source._source_order_image(image)
            outsider = get_user_model().objects.create_user(username="issue-display-outsider")
            Employee.objects.create(user=outsider, employee_code="ISSUE-DISPLAY-OUT", display_name="其他领料员工")
            client = APIClient()
            client.force_authenticate(outsider)
            self.assertEqual(client.get(self.image_url(image)).status_code, 403)
            outsider.user_permissions.add(Permission.objects.get(
                content_type__app_label="material_issues", codename="view_materialissue",
            ))
            client.force_authenticate(get_user_model().objects.get(pk=outsider.pk))
            self.assertEqual(client.get(self.image_url(image)).status_code, 404)
            self.assertEqual(client.get("/api/v1/material-issues/eligible-products/", {
                "production_task_id": str(self.task.pk),
            }).status_code, 404)

    def test_source_image_keeps_scan_archive_and_storage_guards(self):
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder):
            image = self.source._product_image(folder, "source.png")
            self.source._source_order_image(image)
            image.scan_status = FileScanStatus.INFECTED
            image.save(update_fields=["scan_status"])
            self.assertIsNone(self.eligible()["image_file_id"])
            self.assertEqual(self.client.get(self.image_url(image)).status_code, 400)
            image.scan_status = FileScanStatus.CLEAN
            image.archived_at = timezone.now()
            image.save(update_fields=["scan_status", "archived_at"])
            self.assertEqual(self.client.get(self.image_url(image)).status_code, 404)
            image.archived_at = None
            image.storage_key = "../outside.png"
            image.save(update_fields=["archived_at", "storage_key"])
            self.assertEqual(self.client.get(self.image_url(image)).status_code, 404)
            image.storage_key = "missing.png"
            image.save(update_fields=["storage_key"])
            self.assertEqual(self.client.get(self.image_url(image)).status_code, 404)

    def test_invalid_image_ids_return_validation_error(self):
        response = self.client.get(f"/api/v1/material-issues/product-images/{self.task.pk}/invalid/")
        self.assertEqual(response.status_code, 400)

    def test_view_all_issue_user_reads_only_explicit_issue_product_images(self):
        with TemporaryDirectory() as folder, self.settings(MEDIA_ROOT=folder, MODULE_ACCESS_ENABLED=False):
            image = self.source._product_image(folder, "source.png")
            self.source._source_order_image(image)
            outsider = get_user_model().objects.create_user(username="issue-display-reviewer")
            Employee.objects.create(user=outsider, employee_code="ISSUE-DISPLAY-REVIEW", display_name="领料审核员工")
            outsider.user_permissions.set(Permission.objects.filter(
                content_type__app_label="material_issues",
                codename__in=["view_materialissue", "view_all_materialissue"],
            ))
            client = APIClient()
            client.force_authenticate(outsider)
            self.assertEqual(client.get(f"/api/v1/material-issues/{self.issue.pk}/").status_code, 200)
            self.assertEqual(client.get("/api/v1/material-issues/eligible-products/", {
                "production_task_id": str(self.task.pk),
            }).status_code, 404)
            response = client.get(self.image_url(image))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"source.png")

            unlinked = copy.copy(self.product)
            unlinked.pk = None
            unlinked.line_number = 2
            unlinked.sales_order_delivery_batch_line = None
            unlinked.image_file = self.source._product_image(folder, "unlinked-primary.png")
            unlinked.save()
            self.assertEqual(client.get(self.image_url(unlinked.image_file)).status_code, 404)
            gallery = self.source._product_image(folder, "unlinked-gallery.png")
            ProductionTaskProductImage.objects.create(product_line=unlinked, image_file=gallery, line_number=1)
            self.assertEqual(client.get(self.image_url(gallery)).status_code, 404)

            other_task, other_line = self.source.create_task_with_product()
            other_image = self.source._product_image(folder, "other-task.png")
            self.source._source_order_image(other_image, other_task, other_line)
            self.assertEqual(client.get(
                f"/api/v1/material-issues/product-images/{other_task.pk}/{other_image.pk}/",
            ).status_code, 404)
