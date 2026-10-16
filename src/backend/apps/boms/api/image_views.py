from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.http import FileResponse, Http404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.files.models import USABLE_FILE_SCAN_STATUSES
from apps.files.uploads import DEFAULT_MAX_IMAGE_BYTES, save_scanned_image

from ..image_files import (
    delete_business_file_if_unreferenced,
    discard_uploaded_files,
    purge_expired_bom_line_image_drafts,
    safe_storage_path,
)
from ..models import Bom, BomLine, BomLineImage, BomLineImageDraft, BomStatus
from ..selectors import accessible_boms
from .image_serializers import (
    BomLineImageDeleteResponseSerializer,
    BomLineImageDraftListResponseSerializer,
    BomLineImageDraftSerializer,
    BomLineImageDraftUploadSerializer,
    BomLineImageListResponseSerializer,
    BomLineImageSerializer,
    BomLineImageUploadSerializer,
)


MAX_IMAGES_PER_UPLOAD = 10
MAX_IMAGES_PER_LINE = 20
DRAFT_IMAGE_TTL = timedelta(hours=24)


class BomLineImageViewSet(viewsets.ViewSet):
    serializer_class = BomLineImageSerializer
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    parser_classes = [MultiPartParser, FormParser]
    action_permission_map = {
        "list": "boms.view_bom",
        "create": "boms.change_bom",
        "destroy": "boms.change_bom",
        "content": "boms.view_bom",
    }

    @staticmethod
    def _accessible_bom(request, bom_id, *, for_update=False):
        queryset = accessible_boms(request)
        if for_update:
            queryset = queryset.select_for_update()
        try:
            return queryset.get(pk=bom_id)
        except Bom.DoesNotExist as exc:
            raise NotFound("未找到可访问的 BOM。") from exc

    @staticmethod
    def _bom_line(bom, line_id):
        try:
            line = BomLine.objects.select_related("section", "section__bom").get(
                pk=line_id,
                section__bom=bom,
            )
        except BomLine.DoesNotExist as exc:
            raise NotFound("未找到当前 BOM 的用料明细。") from exc
        return line

    @staticmethod
    def _images(line):
        return BomLineImage.objects.filter(bom_line=line).select_related(
            "bom_line__section",
            "business_file",
        ).order_by("position", "id")

    @staticmethod
    def _touch_bom(bom, actor_employee):
        bom.status = BomStatus.PENDING_CONFIRMATION
        bom.updated_by_employee = actor_employee
        bom.confirmed_by_employee = None
        bom.confirmed_at = None
        bom.confirmation_reason = ""
        bom.save(
            update_fields=[
                "status",
                "updated_by_employee",
                "confirmed_by_employee",
                "confirmed_at",
                "confirmation_reason",
                "updated_at",
            ]
        )

    @staticmethod
    def _response(images, bom, *, response_status=status.HTTP_200_OK):
        response = Response(
            {"data": BomLineImageSerializer(images, many=True).data},
            status=response_status,
        )
        response["ETag"] = etag_for_instance(bom)
        return response

    @extend_schema(responses={status.HTTP_200_OK: BomLineImageListResponseSerializer})
    def list(self, request, bom_id=None, line_id=None):
        bom = self._accessible_bom(request, bom_id)
        line = self._bom_line(bom, line_id)
        return self._response(self._images(line), bom)

    @extend_schema(
        request={"multipart/form-data": BomLineImageUploadSerializer},
        responses={status.HTTP_201_CREATED: BomLineImageListResponseSerializer},
    )
    def create(self, request, bom_id=None, line_id=None):
        uploads = request.FILES.getlist("files")
        serializer = BomLineImageUploadSerializer(data={"files": uploads})
        serializer.is_valid(raise_exception=True)
        uploads = serializer.validated_data["files"]
        if len(uploads) > MAX_IMAGES_PER_UPLOAD:
            raise ValidationError({"files": f"单次最多上传 {MAX_IMAGES_PER_UPLOAD} 张图片。"})

        saved_files = []
        try:
            with transaction.atomic():
                bom = self._accessible_bom(request, bom_id, for_update=True)
                require_matching_etag(request, bom)
                line = self._bom_line(bom, line_id)
                existing_count = BomLineImage.objects.filter(bom_line=line).count()
                if existing_count + len(uploads) > MAX_IMAGES_PER_LINE:
                    raise ValidationError({"files": f"每条用料明细最多保留 {MAX_IMAGES_PER_LINE} 张图片。"})

                last_position = (
                    BomLineImage.objects.filter(bom_line=line).aggregate(value=Max("position"))["value"] or 0
                )
                for offset, upload in enumerate(uploads, start=1):
                    business_file = save_scanned_image(
                        upload,
                        getattr(request, "employee", None),
                        storage_folder=f"boms/{bom.pk}/lines/{line.pk}",
                        field_label="BOM 用料明细图片",
                        max_bytes=DEFAULT_MAX_IMAGE_BYTES,
                    )
                    saved_files.append(business_file)
                    BomLineImage.objects.create(
                        bom_line=line,
                        business_file=business_file,
                        position=last_position + offset,
                    )
                self._touch_bom(bom, getattr(request, "employee", None))
                images = list(self._images(line))
        except Exception:
            discard_uploaded_files(saved_files)
            raise

        return self._response(images, bom, response_status=status.HTTP_201_CREATED)

    @extend_schema(
        request=None,
        responses={status.HTTP_200_OK: BomLineImageDeleteResponseSerializer},
    )
    def destroy(self, request, bom_id=None, line_id=None, image_id=None):
        with transaction.atomic():
            bom = self._accessible_bom(request, bom_id, for_update=True)
            require_matching_etag(request, bom)
            line = self._bom_line(bom, line_id)
            try:
                image = BomLineImage.objects.select_related("business_file").get(
                    pk=image_id,
                    bom_line=line,
                )
            except BomLineImage.DoesNotExist as exc:
                raise NotFound("未找到当前用料明细的图片。") from exc

            business_file_id = image.business_file_id
            image.delete()
            remaining = list(self._images(line))
            for offset, item in enumerate(remaining, start=1):
                item.position = 1_000_000 + offset
            BomLineImage.objects.bulk_update(remaining, ["position"])
            for position, item in enumerate(remaining, start=1):
                item.position = position
            BomLineImage.objects.bulk_update(remaining, ["position"])
            self._touch_bom(bom, getattr(request, "employee", None))

        delete_business_file_if_unreferenced(business_file_id)
        response = Response({"data": {"deleted_id": str(image_id)}})
        response["ETag"] = etag_for_instance(bom)
        return response

    @extend_schema(responses={(status.HTTP_200_OK, "image/*"): OpenApiTypes.BINARY})
    def content(self, request, bom_id=None, line_id=None, image_id=None):
        bom = self._accessible_bom(request, bom_id)
        line = self._bom_line(bom, line_id)
        try:
            image = BomLineImage.objects.select_related("business_file").get(
                pk=image_id,
                bom_line=line,
                business_file__archived_at__isnull=True,
                business_file__scan_status__in=USABLE_FILE_SCAN_STATUSES,
                business_file__content_type__startswith="image/",
            )
        except BomLineImage.DoesNotExist as exc:
            raise Http404("未找到可访问的用料明细图片。") from exc

        storage_path = safe_storage_path(image.business_file.storage_key)
        if storage_path is None or not storage_path.is_file():
            raise Http404("用料明细图片文件不存在。")
        response = FileResponse(
            storage_path.open("rb"),
            as_attachment=request.query_params.get("download") == "1",
            filename=image.business_file.original_name,
            content_type=image.business_file.content_type,
        )
        response["Cache-Control"] = "private, max-age=300"
        return response


class BomLineImageDraftViewSet(viewsets.ViewSet):
    serializer_class = BomLineImageDraftSerializer
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    parser_classes = [MultiPartParser, FormParser]
    action_permission_map = {
        "create": "boms.change_bom",
        "destroy": "boms.change_bom",
        "content": "boms.change_bom",
    }

    @staticmethod
    def _accessible_bom(request, bom_id, *, for_update=False):
        queryset = accessible_boms(request)
        if for_update:
            queryset = queryset.select_for_update()
        try:
            return queryset.get(pk=bom_id)
        except Bom.DoesNotExist as exc:
            raise NotFound("未找到可访问的 BOM。") from exc

    @staticmethod
    def _drafts(bom, request, draft_key):
        return BomLineImageDraft.objects.filter(
            bom=bom,
            owner_user=request.user,
            draft_key=draft_key,
            expires_at__gt=timezone.now(),
        ).select_related("business_file").order_by("position", "id")

    @staticmethod
    def _response(drafts, bom, *, response_status=status.HTTP_200_OK):
        response = Response(
            {"data": BomLineImageDraftSerializer(drafts, many=True).data},
            status=response_status,
        )
        response["ETag"] = etag_for_instance(bom)
        return response

    @extend_schema(
        request={"multipart/form-data": BomLineImageDraftUploadSerializer},
        responses={status.HTTP_201_CREATED: BomLineImageDraftListResponseSerializer},
    )
    def create(self, request, bom_id=None):
        uploads = request.FILES.getlist("files")
        serializer = BomLineImageDraftUploadSerializer(
            data={"draft_key": request.data.get("draft_key"), "files": uploads}
        )
        serializer.is_valid(raise_exception=True)
        draft_key = serializer.validated_data["draft_key"]
        uploads = serializer.validated_data["files"]

        saved_files = []
        try:
            with transaction.atomic():
                bom = self._accessible_bom(request, bom_id, for_update=True)
                require_matching_etag(request, bom)
                purge_expired_bom_line_image_drafts(
                    bom_id=bom.pk,
                    owner_user_id=request.user.pk,
                )
                current_drafts = BomLineImageDraft.objects.select_for_update().filter(
                    bom=bom,
                    owner_user=request.user,
                    draft_key=draft_key,
                    expires_at__gt=timezone.now(),
                )
                current_count = current_drafts.count()
                if current_count + len(uploads) > MAX_IMAGES_PER_LINE:
                    raise ValidationError({"files": f"每条用料明细最多保留 {MAX_IMAGES_PER_LINE} 张图片。"})
                last_position = current_drafts.aggregate(value=Max("position"))["value"] or 0
                expires_at = timezone.now() + DRAFT_IMAGE_TTL
                current_drafts.update(expires_at=expires_at)
                for offset, upload in enumerate(uploads, start=1):
                    business_file = save_scanned_image(
                        upload,
                        getattr(request, "employee", None),
                        storage_folder=f"boms/{bom.pk}/draft-lines/{request.user.pk}/{draft_key}",
                        field_label="BOM 用料明细图片",
                        max_bytes=DEFAULT_MAX_IMAGE_BYTES,
                    )
                    saved_files.append(business_file)
                    BomLineImageDraft.objects.create(
                        bom=bom,
                        owner_user=request.user,
                        business_file=business_file,
                        draft_key=draft_key,
                        position=last_position + offset,
                        expires_at=expires_at,
                    )
                drafts = list(self._drafts(bom, request, draft_key))
        except Exception:
            discard_uploaded_files(saved_files)
            raise

        return self._response(drafts, bom, response_status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={status.HTTP_200_OK: BomLineImageDeleteResponseSerializer})
    def destroy(self, request, bom_id=None, draft_id=None):
        with transaction.atomic():
            bom = self._accessible_bom(request, bom_id, for_update=True)
            require_matching_etag(request, bom)
            purge_expired_bom_line_image_drafts(
                bom_id=bom.pk,
                owner_user_id=request.user.pk,
            )
            try:
                draft = BomLineImageDraft.objects.select_for_update().get(
                    pk=draft_id,
                    bom=bom,
                    owner_user=request.user,
                    expires_at__gt=timezone.now(),
                )
            except BomLineImageDraft.DoesNotExist as exc:
                raise NotFound("未找到当前用料明细的草稿图片。") from exc
            draft_key = draft.draft_key
            draft.delete()
            remaining = list(
                BomLineImageDraft.objects.select_for_update()
                .filter(
                    bom=bom,
                    owner_user=request.user,
                    draft_key=draft_key,
                    expires_at__gt=timezone.now(),
                )
                .order_by("position", "id")
            )
            for offset, item in enumerate(remaining, start=1):
                item.position = 1_000_000 + offset
            BomLineImageDraft.objects.bulk_update(remaining, ["position"])
            for position, item in enumerate(remaining, start=1):
                item.position = position
            BomLineImageDraft.objects.bulk_update(remaining, ["position"])

        response = Response({"data": {"deleted_id": str(draft_id)}})
        response["ETag"] = etag_for_instance(bom)
        return response

    @extend_schema(responses={(status.HTTP_200_OK, "image/*"): OpenApiTypes.BINARY})
    def content(self, request, bom_id=None, draft_id=None):
        bom = self._accessible_bom(request, bom_id)
        purge_expired_bom_line_image_drafts(
            bom_id=bom.pk,
            owner_user_id=request.user.pk,
        )
        try:
            draft = BomLineImageDraft.objects.select_related("business_file").get(
                pk=draft_id,
                bom=bom,
                owner_user=request.user,
                expires_at__gt=timezone.now(),
                business_file__archived_at__isnull=True,
                business_file__scan_status__in=USABLE_FILE_SCAN_STATUSES,
                business_file__content_type__startswith="image/",
            )
        except BomLineImageDraft.DoesNotExist as exc:
            raise Http404("未找到可访问的用料明细草稿图片。") from exc

        storage_path = safe_storage_path(draft.business_file.storage_key)
        if storage_path is None or not storage_path.is_file():
            raise Http404("用料明细草稿图片文件不存在。")
        response = FileResponse(
            storage_path.open("rb"),
            as_attachment=request.query_params.get("download") == "1",
            filename=draft.business_file.original_name,
            content_type=draft.business_file.content_type,
        )
        response["Cache-Control"] = "private, no-store"
        return response
