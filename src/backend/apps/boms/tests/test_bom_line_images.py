from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory, APITestCase
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import PreconditionFailed, etag_for_instance
from apps.customers.models import CustomerAccount, CustomerAssignment
from apps.files.models import BusinessFile, FileScanStatus
from apps.organizations.models import Employee
from apps.products.models import ProductInformation, RawMaterialInformation
from apps.production_tasks.models import (
    DeliveryMethod,
    OrderSource,
    ProductionTask,
    ProductionTaskProduct,
    ProductionTaskStatus,
)
from apps.reference_data.models import Currency, ProductItemType, ReferenceStatus

from ..models import (
    Bom,
    BomCreationMethod,
    BomLine,
    BomLineImage,
    BomLineImageDraft,
    BomSection,
    BomStatus,
)
from ..services import create_bom, update_bom_lines


PNG_BYTES = b"\x89PNG\r\n\x1a\nBOM image test"


class BomLineImageApiTests(APITestCase):
    def setUp(self):
        self.media_dir = TemporaryDirectory()
        self.settings_override = self.settings(MEDIA_ROOT=self.media_dir.name)
        self.settings_override.enable()
        self.scan_patch = patch("apps.files.uploads._clamav_scan", return_value="clean")
        self.scan_patch.start()

        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="bom_image_user")
        self.employee = Employee.objects.create(
            user=self.user,
            employee_code="BOM_IMAGE_USER",
            display_name="BOM 图片测试员工",
        )
        self.user.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label="boms",
                codename__in=["view_bom", "change_bom", "add_bom"],
            )
        )
        self.customer = CustomerAccount.objects.create(
            account_code="BOM_IMAGE_CUSTOMER",
            account_name="BOM 图片测试客户",
            primary_country_code="CN",
        )
        CustomerAssignment.objects.create(
            customer_account=self.customer,
            employee=self.employee,
            assignment_role="PRIMARY_OWNER",
            effective_from=timezone.now(),
        )
        product = (
            ProductInformation.objects.filter(status="ACTIVE", archived_at__isnull=True)
            .exclude(product_code="")
            .select_related("unit")
            .first()
        )
        self.assertIsNotNone(product)
        currency = Currency.objects.filter(status="ACTIVE", archived_at__isnull=True).first()
        self.assertIsNotNone(currency)
        today = timezone.localdate()
        task = ProductionTask.objects.create(
            task_number="HT-BOM-IMAGE-001",
            contract_number="HTC-BOM-IMAGE-001",
            order_source=OrderSource.NEW,
            order_number="ORDER-BOM-IMAGE-001",
            customer_account=self.customer,
            order_date=today,
            delivery_date=today + timedelta(days=30),
            salesperson=self.employee,
            currency=currency,
            includes_tax=True,
            order_tolerance_percent=Decimal("3"),
            is_repeat_order=False,
            preproduction_sample_required=False,
            delivery_method=DeliveryMethod.SPLIT,
            status=ProductionTaskStatus.READY,
            created_by_employee=self.employee,
        )
        self.product_line = ProductionTaskProduct.objects.create(
            production_task=task,
            line_number=1,
            product=product,
            product_number_snapshot=product.product_number,
            product_code_snapshot=product.product_code,
            item_number_snapshot=product.product_item.item_number,
            product_name_snapshot=product.product_name,
            specification_snapshot=product.specification,
            quantity=10,
            unit=product.unit,
            currency=currency,
            unit_price=Decimal("1"),
            total_amount=Decimal("10"),
            exchange_rate=Decimal("1"),
        )
        self.bom = Bom.objects.create(
            bom_number="BOM-HT-BOM-IMAGE-001-V1",
            production_task=task,
            product_line=self.product_line,
            version_number=1,
            creation_method=BomCreationMethod.BLANK,
            status=BomStatus.PENDING_CONFIRMATION,
            product_number_snapshot=product.product_number,
            product_code_snapshot=product.product_code,
            product_name_snapshot=product.product_name,
            specification_snapshot=product.specification,
            product_category_snapshot=product.category.category_name,
            order_quantity=Decimal("10"),
            section_count=2,
            line_count=3,
            created_by_employee=self.employee,
            updated_by_employee=self.employee,
        )
        self.cutting_section = BomSection.objects.create(
            bom=self.bom,
            line_number=1,
            section_type="FABRIC",
            title="裁剪明细",
        )
        self.cutting_line = BomLine.objects.create(
            section=self.cutting_section,
            line_number=1,
            part_name="椅面",
        )
        self.second_cutting_line = BomLine.objects.create(
            section=self.cutting_section,
            line_number=2,
            part_name="外袋",
        )
        self.profile_section = BomSection.objects.create(
            bom=self.bom,
            line_number=2,
            section_type="PROFILE",
            title="管材类",
        )
        self.profile_line = BomLine.objects.create(
            section=self.profile_section,
            line_number=1,
            part_name="横管",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def tearDown(self):
        self.scan_patch.stop()
        self.settings_override.disable()
        self.media_dir.cleanup()

    def collection_url(self, line=None):
        return reverse(
            "bom-line-image-list",
            kwargs={"bom_id": self.bom.pk, "line_id": (line or self.cutting_line).pk},
        )

    def detail_url(self, image, line=None):
        return reverse(
            "bom-line-image-detail",
            kwargs={
                "bom_id": self.bom.pk,
                "line_id": (line or self.cutting_line).pk,
                "image_id": image.pk,
            },
        )

    def content_url(self, image, line=None):
        return reverse(
            "bom-line-image-content",
            kwargs={
                "bom_id": self.bom.pk,
                "line_id": (line or self.cutting_line).pk,
                "image_id": image.pk,
            },
        )

    def draft_collection_url(self, bom=None):
        return reverse("bom-line-image-draft-list", kwargs={"bom_id": (bom or self.bom).pk})

    def draft_detail_url(self, draft):
        return reverse(
            "bom-line-image-draft-detail",
            kwargs={"bom_id": self.bom.pk, "draft_id": draft.pk},
        )

    def draft_content_url(self, draft):
        return reverse(
            "bom-line-image-draft-content",
            kwargs={"bom_id": self.bom.pk, "draft_id": draft.pk},
        )

    @staticmethod
    def upload(name="cutting.png", body=PNG_BYTES, content_type="image/png"):
        return SimpleUploadedFile(name, body, content_type=content_type)

    def stored_file(self, *, name="stored.png", suffix="stored"):
        storage_key = f"tests/boms/{suffix}.png"
        path = Path(self.media_dir.name) / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG_BYTES)
        return BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name=name,
            storage_key=storage_key,
            content_type="image/png",
            size_bytes=len(PNG_BYTES),
            content_hash=suffix,
            scan_status=FileScanStatus.CLEAN,
            scanned_at=timezone.now(),
        )

    def post_images(self, files, *, etag=None, line=None):
        return self.client.post(
            self.collection_url(line),
            {"files": files},
            format="multipart",
            HTTP_IF_MATCH=etag or etag_for_instance(self.bom),
        )

    def post_draft_images(self, files, *, draft_key=None, etag=None, bom=None):
        target_bom = bom or self.bom
        return self.client.post(
            self.draft_collection_url(target_bom),
            {"draft_key": str(draft_key or uuid4()), "files": files},
            format="multipart",
            HTTP_IF_MATCH=etag or etag_for_instance(target_bom),
        )

    def service_sections(self, *extra_cutting_lines, profile_draft_ids=None):
        profile_line = {"id": self.profile_line.pk, "part_name": "横管"}
        if profile_draft_ids:
            profile_line["draft_image_ids"] = profile_draft_ids
        return [
            {
                "id": self.cutting_section.pk,
                "section_type": "FABRIC",
                "title": "裁剪明细",
                "lines": [
                    {"id": self.cutting_line.pk, "part_name": "椅面"},
                    {"id": self.second_cutting_line.pk, "part_name": "外袋"},
                    *extra_cutting_lines,
                ],
            },
            {
                "id": self.profile_section.pk,
                "section_type": "PROFILE",
                "title": "管材类",
                "lines": [profile_line],
            },
        ]

    def update_request(self, *, etag=None, user=None, employee=None):
        request = APIRequestFactory().patch(
            "/",
            {},
            format="json",
            HTTP_IF_MATCH=etag or etag_for_instance(self.bom),
        )
        request.user = user or self.user
        request.employee = employee or self.employee
        return request

    @staticmethod
    def fixed_sections(source_sections):
        definitions = (
            ("管材类", "PROFILE"),
            ("五金件", "ACCESSORY"),
            ("塑料件类", "ACCESSORY"),
            ("辅料类", "FABRIC"),
            ("面料类", "FABRIC"),
            ("包材类", "ACCESSORY"),
            ("裁剪明细", "FABRIC"),
        )
        expected_types = dict(definitions)
        used_titles = set()
        normalized = []
        keyword_groups = (
            ("裁剪明细", ("裁剪", "裁片")),
            ("塑料件类", ("塑料",)),
            ("包材类", ("包材", "包装")),
            ("五金件", ("五金", "配件")),
            ("面料类", ("面辅料", "面料")),
            ("辅料类", ("辅料",)),
        )
        for section in source_sections:
            section = dict(section)
            if section["section_type"] == "PROFILE":
                fixed_title = "管材类"
            else:
                compact_title = "".join(section["title"].split())
                fixed_title = next(
                    (
                        title
                        for title, keywords in keyword_groups
                        if title not in used_titles and any(keyword in compact_title for keyword in keywords)
                    ),
                    "",
                )
                if not fixed_title:
                    candidates = (
                        ("面料类", "辅料类", "裁剪明细")
                        if section["section_type"] == "FABRIC"
                        else ("五金件", "塑料件类", "包材类")
                    )
                    fixed_title = next(title for title in candidates if title not in used_titles)
            section["title"] = fixed_title
            used_titles.add(fixed_title)
            normalized.append(section)
        for title, section_type in definitions:
            if title not in used_titles:
                normalized.append({"title": title, "section_type": section_type, "lines": []})
        return sorted(normalized, key=lambda section: list(expected_types).index(section["title"]))

    def test_upload_list_and_content_use_ordered_private_images(self):
        self.bom.status = BomStatus.VERIFIED
        self.bom.confirmed_by_employee = self.employee
        self.bom.confirmed_at = timezone.now()
        self.bom.confirmation_reason = "生产前确认"
        self.bom.save(
            update_fields=["status", "confirmed_by_employee", "confirmed_at", "confirmation_reason", "updated_at"]
        )
        response = self.post_images([self.upload("first.png"), self.upload("second.png")])

        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response["ETag"], etag_for_instance(self.bom))
        self.assertEqual([item["position"] for item in response.data["data"]], [1, 2])
        self.assertEqual([item["name"] for item in response.data["data"]], ["first.png", "second.png"])
        self.assertTrue(all(item["content_url"].endswith("/content/") for item in response.data["data"]))
        self.bom.refresh_from_db()
        self.assertEqual(self.bom.status, BomStatus.PENDING_CONFIRMATION)
        self.assertEqual(self.bom.updated_by_employee, self.employee)
        self.assertIsNone(self.bom.confirmed_by_employee)
        self.assertIsNone(self.bom.confirmed_at)
        self.assertEqual(self.bom.confirmation_reason, "")

        list_response = self.client.get(self.collection_url())
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data["data"]), 2)
        image = BomLineImage.objects.get(position=1)
        content_response = self.client.get(self.content_url(image))
        self.assertEqual(content_response.status_code, 200)
        self.assertEqual(content_response["Cache-Control"], "private, max-age=300")
        self.assertEqual(b"".join(content_response.streaming_content), PNG_BYTES)

    def test_write_requires_permission_and_matching_etag(self):
        missing = self.client.post(
            self.collection_url(),
            {"files": [self.upload()]},
            format="multipart",
        )
        self.assertEqual(missing.status_code, 428)
        stale = self.post_images([self.upload()], etag='"stale"')
        self.assertEqual(stale.status_code, 412)

        user_model = get_user_model()
        viewer = user_model.objects.create_user(username="bom_image_viewer")
        viewer_employee = Employee.objects.create(
            user=viewer,
            employee_code="BOM_IMAGE_VIEWER",
            display_name="BOM 图片查看员",
        )
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label="boms", codename="view_bom"))
        CustomerAssignment.objects.create(
            customer_account=self.customer,
            employee=viewer_employee,
            assignment_role="SECONDARY_OWNER",
            effective_from=timezone.now(),
        )
        self.client.force_authenticate(viewer)
        self.assertEqual(self.client.get(self.collection_url()).status_code, 200)
        denied = self.client.post(
            self.collection_url(),
            {"files": [self.upload()]},
            format="multipart",
            HTTP_IF_MATCH=etag_for_instance(self.bom),
        )
        self.assertEqual(denied.status_code, 403)

    def test_allows_images_on_every_bom_line_and_enforces_upload_limits(self):
        profile_upload = self.post_images([self.upload("profile.png")], line=self.profile_line)
        self.assertEqual(profile_upload.status_code, 201, profile_upload.data)
        self.assertEqual(profile_upload.data["data"][0]["name"], "profile.png")
        self.assertTrue(BomLineImage.objects.filter(bom_line=self.profile_line).exists())
        self.bom.refresh_from_db()

        too_many = self.post_images([self.upload(f"{index}.png") for index in range(11)])
        self.assertEqual(too_many.status_code, 400)

        for position in range(1, 21):
            BomLineImage.objects.create(
                bom_line=self.cutting_line,
                business_file=self.stored_file(suffix=f"existing-{position}"),
                position=position,
            )
        over_total = self.post_images([self.upload("overflow.png")])
        self.assertEqual(over_total.status_code, 400)

    def test_rejects_bad_format_size_and_cleans_partial_batch(self):
        unsupported = self.post_images([self.upload("cutting.txt", b"text", "text/plain")])
        self.assertEqual(unsupported.status_code, 400)
        oversized = self.post_images([self.upload("large.png", PNG_BYTES + b"x" * (5 * 1024 * 1024))])
        self.assertEqual(oversized.status_code, 400)

        before_count = BusinessFile.objects.count()
        partial_failure = self.post_images(
            [
                self.upload("valid.png"),
                self.upload("invalid.png", b"not a png", "image/png"),
            ]
        )
        self.assertEqual(partial_failure.status_code, 400)
        self.assertEqual(BusinessFile.objects.count(), before_count)
        self.assertFalse(any(Path(self.media_dir.name).glob("boms/**/*.png")))

    def test_business_file_create_failure_removes_already_moved_image(self):
        before_files = {path for path in Path(self.media_dir.name).rglob("*") if path.is_file()}
        before_count = BusinessFile.objects.count()

        with patch("apps.files.uploads.BusinessFile.objects.create", side_effect=RuntimeError("db failure")):
            with self.assertRaises(RuntimeError):
                self.post_images([self.upload("db-failure.png")])

        after_files = {path for path in Path(self.media_dir.name).rglob("*") if path.is_file()}
        self.assertEqual(after_files, before_files)
        self.assertEqual(BusinessFile.objects.count(), before_count)

    def test_content_cannot_be_read_outside_bom_scope(self):
        business_file = self.stored_file()
        image = BomLineImage.objects.create(
            bom_line=self.cutting_line,
            business_file=business_file,
            position=1,
        )
        user_model = get_user_model()
        outsider = user_model.objects.create_user(username="bom_image_outsider")
        Employee.objects.create(
            user=outsider,
            employee_code="BOM_IMAGE_OUTSIDER",
            display_name="BOM 图片外部员工",
        )
        outsider.user_permissions.add(Permission.objects.get(content_type__app_label="boms", codename="view_bom"))
        self.client.force_authenticate(outsider)

        self.assertEqual(self.client.get(self.content_url(image)).status_code, 404)

    def test_delete_compacts_order_and_removes_only_unreferenced_file(self):
        first_file = self.stored_file(name="first.png", suffix="first")
        second_file = self.stored_file(name="second.png", suffix="second")
        first = BomLineImage.objects.create(
            bom_line=self.cutting_line,
            business_file=first_file,
            position=1,
        )
        second = BomLineImage.objects.create(
            bom_line=self.cutting_line,
            business_file=second_file,
            position=2,
        )
        shared = BomLineImage.objects.create(
            bom_line=self.second_cutting_line,
            business_file=second_file,
            position=1,
        )
        first_path = Path(self.media_dir.name) / first_file.storage_key

        response = self.client.delete(
            self.detail_url(first),
            HTTP_IF_MATCH=etag_for_instance(self.bom),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(BusinessFile.objects.filter(pk=first_file.pk).exists())
        self.assertFalse(first_path.exists())
        second.refresh_from_db()
        self.assertEqual(second.position, 1)

        self.bom.refresh_from_db()
        response = self.client.delete(
            self.detail_url(second),
            HTTP_IF_MATCH=etag_for_instance(self.bom),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(BusinessFile.objects.filter(pk=second_file.pk).exists())
        self.assertTrue(BomLineImage.objects.filter(pk=shared.pk).exists())

    def test_copy_reuses_business_file_and_preserves_position(self):
        business_file = self.stored_file()
        BomLineImage.objects.create(
            bom_line=self.cutting_line,
            business_file=business_file,
            position=3,
        )

        copied = create_bom(
            product_line=self.product_line,
            creation_method=BomCreationMethod.COPY,
            source_bom=self.bom,
            actor_employee=self.employee,
        )

        copied_image = BomLineImage.objects.get(bom_line__section__bom=copied)
        self.assertEqual(copied_image.business_file_id, business_file.pk)
        self.assertEqual(copied_image.position, 3)

    def test_removing_line_cleans_its_unreferenced_business_file_after_commit(self):
        business_file = self.stored_file(suffix="removed-line")
        storage_path = Path(self.media_dir.name) / business_file.storage_key
        BomLineImage.objects.create(
            bom_line=self.cutting_line,
            business_file=business_file,
            position=1,
        )
        request = APIRequestFactory().patch(
            "/",
            {},
            format="json",
            HTTP_IF_MATCH=etag_for_instance(self.bom),
        )
        request.user = self.user
        request.employee = self.employee
        sections = [
            {
                "id": self.cutting_section.pk,
                "section_type": "FABRIC",
                "title": "裁剪明细",
                "lines": [{"id": self.second_cutting_line.pk, "part_name": "外袋"}],
            },
            {
                "id": self.profile_section.pk,
                "section_type": "PROFILE",
                "title": "管材类",
                "lines": [{"id": self.profile_line.pk, "part_name": "横管"}],
            },
        ]

        with self.captureOnCommitCallbacks(execute=True):
            update_bom_lines(
                bom=self.bom,
                sections=sections,
                actor_employee=self.employee,
                request=request,
            )

        self.assertFalse(BomLine.objects.filter(pk=self.cutting_line.pk).exists())
        self.assertFalse(BusinessFile.objects.filter(pk=business_file.pk).exists())
        self.assertFalse(storage_path.exists())

    def test_draft_images_upload_before_line_exists_and_content_is_private(self):
        initial_etag = etag_for_instance(self.bom)
        draft_key = uuid4()
        response = self.post_draft_images(
            [self.upload("first-draft.png"), self.upload("second-draft.png")],
            draft_key=draft_key,
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response["ETag"], initial_etag)
        self.assertEqual([item["position"] for item in response.data["data"]], [1, 2])
        self.assertEqual([item["name"] for item in response.data["data"]], ["first-draft.png", "second-draft.png"])
        self.assertTrue(all(item["draft_key"] == str(draft_key) for item in response.data["data"]))
        self.assertEqual(BomLineImage.objects.count(), 0)

        draft = BomLineImageDraft.objects.get(position=1)
        content = self.client.get(self.draft_content_url(draft))
        self.assertEqual(content.status_code, 200)
        self.assertEqual(content["Cache-Control"], "private, no-store")
        self.assertEqual(b"".join(content.streaming_content), PNG_BYTES)

    def test_draft_upload_enforces_etag_owner_scope_and_per_line_limit(self):
        missing_etag = self.client.post(
            self.draft_collection_url(),
            {"draft_key": str(uuid4()), "files": [self.upload()]},
            format="multipart",
        )
        self.assertEqual(missing_etag.status_code, 428)
        stale = self.post_draft_images([self.upload()], etag='"stale"')
        self.assertEqual(stale.status_code, 412)

        draft_key = uuid4()
        first_batch = self.post_draft_images(
            [self.upload(f"draft-limit-{position}.png") for position in range(1, 11)],
            draft_key=draft_key,
        )
        self.assertEqual(first_batch.status_code, 201, first_batch.data)
        first_draft = BomLineImageDraft.objects.get(pk=first_batch.data["data"][0]["id"])
        first_draft.expires_at = timezone.now() + timedelta(minutes=1)
        first_draft.save(update_fields=["expires_at", "updated_at"])
        second_batch = self.post_draft_images(
            [self.upload(f"draft-limit-{position}.png") for position in range(11, 21)],
            draft_key=draft_key,
        )
        self.assertEqual(second_batch.status_code, 201, second_batch.data)
        first_draft.refresh_from_db()
        self.assertGreater(first_draft.expires_at, timezone.now() + timedelta(hours=23))
        over_limit = self.post_draft_images([self.upload("overflow.png")], draft_key=draft_key)
        self.assertEqual(over_limit.status_code, 400)

        user_model = get_user_model()
        other_user = user_model.objects.create_user(username="bom_draft_other_editor")
        other_employee = Employee.objects.create(
            user=other_user,
            employee_code="BOM_DRAFT_OTHER",
            display_name="BOM 草稿图片其他编辑员",
        )
        other_user.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label="boms",
                codename__in=["view_bom", "change_bom"],
            )
        )
        CustomerAssignment.objects.create(
            customer_account=self.customer,
            employee=other_employee,
            assignment_role="SECONDARY_OWNER",
            effective_from=timezone.now(),
        )
        owned_draft = BomLineImageDraft.objects.filter(owner_user=self.user).first()
        self.client.force_authenticate(other_user)
        self.assertEqual(self.client.get(self.draft_content_url(owned_draft)).status_code, 404)

    def test_saving_bom_binds_draft_images_to_new_cutting_line_in_order(self):
        draft_key = uuid4()
        uploaded = self.post_draft_images(
            [self.upload("first.png"), self.upload("second.png")],
            draft_key=draft_key,
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.data)
        draft_ids = [item["id"] for item in reversed(uploaded.data["data"])]
        request = APIRequestFactory().patch(
            "/",
            {},
            format="json",
            HTTP_IF_MATCH=etag_for_instance(self.bom),
        )
        request.user = self.user
        request.employee = self.employee
        sections = [
            {
                "id": self.cutting_section.pk,
                "section_type": "FABRIC",
                "title": "裁剪明细",
                "lines": [
                    {"id": self.cutting_line.pk, "part_name": "椅面"},
                    {"id": self.second_cutting_line.pk, "part_name": "外袋"},
                    {
                        "part_name": "未保存裁片",
                        "draft_image_ids": draft_ids,
                    },
                ],
            },
            {
                "id": self.profile_section.pk,
                "section_type": "PROFILE",
                "title": "管材类",
                "lines": [{"id": self.profile_line.pk, "part_name": "横管"}],
            },
        ]

        update_bom_lines(
            bom=self.bom,
            sections=sections,
            actor_employee=self.employee,
            request=request,
        )

        new_line = BomLine.objects.get(section=self.cutting_section, part_name="未保存裁片")
        self.assertEqual(
            list(new_line.images.values_list("business_file__original_name", flat=True)),
            ["second.png", "first.png"],
        )
        self.assertFalse(BomLineImageDraft.objects.filter(pk__in=draft_ids).exists())
        self.assertEqual(BusinessFile.objects.filter(original_name__in=["first.png", "second.png"]).count(), 2)

    def test_stale_etag_does_not_consume_drafts_and_failed_save_is_retryable(self):
        uploaded = self.post_draft_images([self.upload("retry.png")], draft_key=uuid4())
        self.assertEqual(uploaded.status_code, 201, uploaded.data)
        draft_id = uploaded.data["data"][0]["id"]
        draft = BomLineImageDraft.objects.select_related("business_file").get(pk=draft_id)
        storage_path = Path(self.media_dir.name) / draft.business_file.storage_key
        sections = self.service_sections({"part_name": "可重试裁片", "draft_image_ids": [draft_id]})

        with self.assertRaisesMessage(PreconditionFailed, "数据已被其他人修改"):
            update_bom_lines(
                bom=self.bom,
                sections=sections,
                actor_employee=self.employee,
                request=self.update_request(etag='"stale"'),
            )
        self.assertTrue(BomLineImageDraft.objects.filter(pk=draft_id).exists())
        self.assertFalse(BomLine.objects.filter(part_name="可重试裁片").exists())

        with patch("apps.boms.services.write_audit_log", side_effect=RuntimeError("audit failure")):
            with self.assertRaisesMessage(RuntimeError, "audit failure"):
                update_bom_lines(
                    bom=self.bom,
                    sections=sections,
                    actor_employee=self.employee,
                    request=self.update_request(),
                )
        self.assertTrue(BomLineImageDraft.objects.filter(pk=draft_id).exists())
        self.assertFalse(BomLine.objects.filter(part_name="可重试裁片").exists())
        self.assertFalse(BomLineImage.objects.filter(business_file_id=draft.business_file_id).exists())
        self.assertTrue(BusinessFile.objects.filter(pk=draft.business_file_id).exists())
        self.assertTrue(storage_path.exists())

        updated = update_bom_lines(
            bom=self.bom,
            sections=sections,
            actor_employee=self.employee,
            request=self.update_request(),
        )
        self.assertEqual(updated.line_count, 4)
        self.assertFalse(BomLineImageDraft.objects.filter(pk=draft_id).exists())
        self.assertTrue(BomLineImage.objects.filter(business_file_id=draft.business_file_id).exists())

    def test_binding_requires_complete_single_group_and_rejects_owner_or_bom_mismatch(self):
        draft_key = uuid4()
        uploaded = self.post_draft_images(
            [self.upload("group-first.png"), self.upload("group-second.png")],
            draft_key=draft_key,
        )
        draft_ids = [item["id"] for item in uploaded.data["data"]]

        partial_group = self.service_sections(
            {"part_name": "第一行", "draft_image_ids": [draft_ids[0]]},
            {"part_name": "第二行", "draft_image_ids": [draft_ids[1]]},
        )
        with self.assertRaisesMessage(ValidationError, "必须一次完整绑定"):
            update_bom_lines(
                bom=self.bom,
                sections=partial_group,
                actor_employee=self.employee,
                request=self.update_request(),
            )
        self.assertEqual(BomLineImageDraft.objects.filter(pk__in=draft_ids).count(), 2)

        duplicate = self.service_sections(
            {"part_name": "重复图片", "draft_image_ids": [draft_ids[0], draft_ids[0]]}
        )
        with self.assertRaisesMessage(ValidationError, "不能重复绑定"):
            update_bom_lines(
                bom=self.bom,
                sections=duplicate,
                actor_employee=self.employee,
                request=self.update_request(),
            )

        user_model = get_user_model()
        other_user = user_model.objects.create_user(username="bom_draft_bind_other")
        other_employee = Employee.objects.create(
            user=other_user,
            employee_code="BOM_DRAFT_BIND_OTHER",
            display_name="BOM 草稿绑定其他员工",
        )
        other_owner = self.service_sections(
            {"part_name": "他人草稿", "draft_image_ids": draft_ids}
        )
        with self.assertRaisesMessage(ValidationError, "不属于当前账号和 BOM"):
            update_bom_lines(
                bom=self.bom,
                sections=other_owner,
                actor_employee=other_employee,
                request=self.update_request(user=other_user, employee=other_employee),
            )

        other_bom = create_bom(
            product_line=self.product_line,
            creation_method=BomCreationMethod.COPY,
            source_bom=self.bom,
            actor_employee=self.employee,
        )
        other_cutting = other_bom.sections.get(title="裁剪明细")
        other_profile = other_bom.sections.get(title="管材类")
        other_request = APIRequestFactory().patch(
            "/",
            {},
            format="json",
            HTTP_IF_MATCH=etag_for_instance(other_bom),
        )
        other_request.user = self.user
        other_request.employee = self.employee
        other_sections = [
            {
                "id": other_cutting.pk,
                "section_type": "FABRIC",
                "title": "裁剪明细",
                "lines": [
                    *[
                        {"id": line.pk, "part_name": line.part_name}
                        for line in other_cutting.lines.all()
                    ],
                    {"part_name": "跨 BOM 草稿", "draft_image_ids": draft_ids},
                ],
            },
            {
                "id": other_profile.pk,
                "section_type": "PROFILE",
                "title": "管材类",
                "lines": [
                    {"id": line.pk, "part_name": line.part_name}
                    for line in other_profile.lines.all()
                ],
            },
        ]
        with self.assertRaisesMessage(ValidationError, "不属于当前账号和 BOM"):
            update_bom_lines(
                bom=other_bom,
                sections=other_sections,
                actor_employee=self.employee,
                request=other_request,
            )

    def test_api_save_returns_bound_drafts_as_formal_images(self):
        blank_bom = create_bom(
            product_line=self.product_line,
            creation_method=BomCreationMethod.BLANK,
            actor_employee=self.employee,
        )
        source = RawMaterialInformation.objects.filter(
            item_type=ProductItemType.SEMI_FINISHED,
            category__item_type=ProductItemType.SEMI_FINISHED,
            category__status=ReferenceStatus.ACTIVE,
            category__archived_at__isnull=True,
            archived_at__isnull=True,
        ).first()
        self.assertIsNotNone(source)
        uploaded = self.post_draft_images(
            [self.upload("before-save.png")],
            draft_key=uuid4(),
            bom=blank_bom,
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.data)
        draft_id = uploaded.data["data"][0]["id"]

        detail = self.client.get(f"/api/v1/boms/{blank_bom.pk}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        sections = self.fixed_sections(detail.data["data"]["sections"])
        cutting_section = next(section for section in sections if section["title"] == "裁剪明细")
        cutting_section["lines"] = [
            {
                "part_name": source.material_name,
                "source_cutting_material_id": str(source.pk),
                "cut_piece_quantity": "2",
                "draft_image_ids": [draft_id],
            }
        ]
        saved = self.client.patch(
            f"/api/v1/boms/{blank_bom.pk}/",
            {"sections": sections},
            format="json",
            HTTP_IF_MATCH=detail["ETag"],
        )

        self.assertEqual(saved.status_code, 200, saved.data)
        saved_cutting = next(
            section for section in saved.data["data"]["sections"] if section["title"] == "裁剪明细"
        )
        self.assertEqual(len(saved_cutting["lines"][0]["images"]), 1)
        self.assertEqual(saved_cutting["lines"][0]["images"][0]["name"], "before-save.png")
        self.assertNotIn("draft_image_ids", saved_cutting["lines"][0])
        self.assertFalse(BomLineImageDraft.objects.filter(pk=draft_id).exists())

    def test_saving_bom_binds_draft_images_to_existing_profile_line(self):
        uploaded = self.post_draft_images([self.upload("profile-draft.png")], draft_key=uuid4())
        draft_id = uploaded.data["data"][0]["id"]
        request = self.update_request(etag=etag_for_instance(self.bom))

        updated = update_bom_lines(
            bom=self.bom,
            sections=self.service_sections(profile_draft_ids=[draft_id]),
            actor_employee=self.employee,
            request=request,
        )

        saved_profile = updated.sections.get(title="管材类").lines.get(pk=self.profile_line.pk)
        self.assertEqual(saved_profile.images.count(), 1)
        self.assertEqual(saved_profile.images.get().business_file.original_name, "profile-draft.png")
        self.assertFalse(BomLineImageDraft.objects.filter(pk=draft_id).exists())

    def test_existing_legacy_line_can_move_to_a_new_explicit_category_section(self):
        legacy_section = BomSection.objects.create(
            bom=self.bom,
            line_number=3,
            section_type="ACCESSORY",
            title="配件清单",
        )
        legacy_hardware_line = BomLine.objects.create(
            section=legacy_section,
            line_number=1,
            part_name="铆钉",
        )
        legacy_plastic_line = BomLine.objects.create(
            section=legacy_section,
            line_number=2,
            part_name="塑料堵头",
            raw_values={"plastic_material_number": "PL-OLD"},
        )
        original_line_id = legacy_plastic_line.pk
        image_file = BusinessFile.objects.create(
            uploaded_by_employee=self.employee,
            original_name="legacy-plastic.png",
            storage_key="boms/legacy-plastic.png",
            content_type="image/png",
            size_bytes=1,
            scan_status=FileScanStatus.CLEAN,
        )
        line_image = BomLineImage.objects.create(
            bom_line=legacy_plastic_line,
            business_file=image_file,
            position=1,
        )
        sections = [
            {
                "id": legacy_section.pk,
                "section_type": "ACCESSORY",
                "title": "五金件",
                "lines": [{"id": legacy_hardware_line.pk, "part_name": "铆钉"}],
            },
            {
                "section_type": "ACCESSORY",
                "title": "塑料件类",
                "lines": [
                    {
                        "id": original_line_id,
                        "part_name": "塑料堵头",
                        "plastic_material_number": "PL-001",
                        "plastic_color": "黑色",
                    }
                ],
            },
            {
                "id": self.profile_section.pk,
                "section_type": "PROFILE",
                "title": "管材类",
                "lines": [{"id": self.profile_line.pk, "part_name": "横管"}],
            },
            {"section_type": "FABRIC", "title": "辅料类", "lines": []},
            {"section_type": "FABRIC", "title": "面料类", "lines": []},
            {"section_type": "ACCESSORY", "title": "包材类", "lines": []},
            {
                "id": self.cutting_section.pk,
                "section_type": "FABRIC",
                "title": "裁剪明细",
                "lines": [
                    {"id": self.cutting_line.pk, "part_name": "椅面"},
                    {"id": self.second_cutting_line.pk, "part_name": "外袋"},
                ],
            },
        ]

        saved = self.client.patch(
            f"/api/v1/boms/{self.bom.pk}/",
            {"sections": sections},
            format="json",
            HTTP_IF_MATCH=etag_for_instance(self.bom),
        )

        self.assertEqual(saved.status_code, 200, saved.data)
        moved_line = BomLine.objects.select_related("section").get(pk=original_line_id)
        self.assertEqual(moved_line.section.title, "塑料件类")
        self.assertEqual(moved_line.raw_values["plastic_material_number"], "PL-001")
        self.assertTrue(moved_line.images.filter(pk=line_image.pk).exists())
        self.assertEqual(self.bom.sections.count(), 7)

    def test_binding_rejects_expired_draft(self):
        uploaded = self.post_draft_images([self.upload("owned.png")], draft_key=uuid4())
        draft_id = uploaded.data["data"][0]["id"]
        request = APIRequestFactory().patch(
            "/",
            {},
            format="json",
            HTTP_IF_MATCH=etag_for_instance(self.bom),
        )
        request.user = self.user
        request.employee = self.employee
        draft = BomLineImageDraft.objects.get(pk=draft_id)
        draft.expires_at = timezone.now() - timedelta(seconds=1)
        draft.save(update_fields=["expires_at", "updated_at"])
        expired_sections = [
            {
                "id": self.cutting_section.pk,
                "section_type": "FABRIC",
                "title": "裁剪明细",
                "lines": [
                    {"id": self.cutting_line.pk, "part_name": "椅面"},
                    {"id": self.second_cutting_line.pk, "part_name": "外袋"},
                    {"part_name": "过期图片行", "draft_image_ids": [draft_id]},
                ],
            },
            {
                "id": self.profile_section.pk,
                "section_type": "PROFILE",
                "title": "管材类",
                "lines": [{"id": self.profile_line.pk, "part_name": "横管"}],
            },
        ]
        with self.assertRaisesMessage(ValidationError, "不存在、已过期"):
            update_bom_lines(
                bom=self.bom,
                sections=expired_sections,
                actor_employee=self.employee,
                request=request,
            )

    def test_draft_delete_expiry_command_and_bom_cascade_remove_orphan_files(self):
        first = self.post_draft_images([self.upload("delete-me.png")], draft_key=uuid4())
        draft = BomLineImageDraft.objects.get(pk=first.data["data"][0]["id"])
        file_id = draft.business_file_id
        storage_path = Path(self.media_dir.name) / draft.business_file.storage_key
        with self.captureOnCommitCallbacks(execute=True):
            deleted = self.client.delete(
                self.draft_detail_url(draft),
                HTTP_IF_MATCH=etag_for_instance(self.bom),
            )
        self.assertEqual(deleted.status_code, 200, deleted.data)
        self.assertFalse(BusinessFile.objects.filter(pk=file_id).exists())
        self.assertFalse(storage_path.exists())

        expired = self.post_draft_images([self.upload("expired.png")], draft_key=uuid4())
        expired_draft = BomLineImageDraft.objects.get(pk=expired.data["data"][0]["id"])
        expired_file_id = expired_draft.business_file_id
        expired_draft.expires_at = timezone.now() - timedelta(seconds=1)
        expired_draft.save(update_fields=["expires_at", "updated_at"])
        with self.captureOnCommitCallbacks(execute=True):
            call_command("purge_expired_bom_line_image_drafts")
        self.assertFalse(BomLineImageDraft.objects.filter(pk=expired_draft.pk).exists())
        self.assertFalse(BusinessFile.objects.filter(pk=expired_file_id).exists())

        cascading = self.post_draft_images([self.upload("cascade.png")], draft_key=uuid4())
        cascading_draft = BomLineImageDraft.objects.get(pk=cascading.data["data"][0]["id"])
        cascading_file_id = cascading_draft.business_file_id
        with self.captureOnCommitCallbacks(execute=True):
            self.bom.delete()
        self.assertFalse(BusinessFile.objects.filter(pk=cascading_file_id).exists())
