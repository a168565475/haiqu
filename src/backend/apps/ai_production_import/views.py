from django.db.models import BooleanField, Case, Value, When
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import HasActiveEmployee
from apps.production_task_imports.access import require_actor

from .errors import AiProductionImportError
from .models import AiProductionImport
from .serializers import (BomDraftWriteSerializer, ReadSerializer, RecordListQuerySerializer,
                          RecordListSerializer, RecordSummarySerializer, ReviewDraftSerializer,
                          TaskDraftWriteSerializer, TaskSelectionSerializer, UploadSerializer)
from .services import MAPPING_WINDOW, delete_record, match_record_materials, owned, recognize_upload, remap_record, restore_previous_review, save_review, snapshot
from .writing import create_boms, create_task_draft
from .task_selection import select_task


class AiProductionImportViewSet(viewsets.GenericViewSet):
    lookup_value_regex = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    serializer_class = ReadSerializer
    queryset = AiProductionImport.objects.none()
    permission_classes = [HasActiveEmployee]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        require_actor(request)

    @extend_schema(parameters=[RecordListQuerySerializer], responses=RecordListSerializer)
    def list(self, request):
        query = RecordListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        offset, limit = query.validated_data["offset"], query.validated_data["limit"]
        records = AiProductionImport.objects.filter(owner=request.employee).annotate(is_recognizing=Case(
            When(state="REVIEW", result={}, then=Value(True)),
            When(source__mapping_started_at__gte=(timezone.now() - MAPPING_WINDOW).isoformat(), then=Value(True)),
            default=Value(False), output_field=BooleanField(),
        )).order_by("-created_at", "-id")
        fields = ("id", "original_name", "state", "task_number", "task_id", "bom_ids", "created_at", "updated_at")
        response = Response({"count": records.count(), "results": RecordSummarySerializer(
            records.only(*fields)[offset:offset + limit], many=True).data})
        response["Cache-Control"] = "no-store"
        return response

    @extend_schema(request=ReviewDraftSerializer, responses=ReadSerializer)
    def partial_update(self, request, pk=None):
        serializer = ReviewDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = save_review(employee=request.employee, record_id=pk,
                             draft=serializer.validated_data, request=request)
        response = Response({"data": ReadSerializer(snapshot(record)).data})
        response["ETag"] = etag_for_instance(record)
        response["Cache-Control"] = "no-store"
        return response

    @extend_schema(responses={204: None})
    def destroy(self, request, pk=None):
        delete_record(employee=request.employee, record_id=pk, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=ReadSerializer)
    @action(detail=True, methods=["post"], url_path="remap")
    def remap(self, request, pk=None):
        try:
            record = remap_record(employee=request.employee, record_id=pk, request=request)
        except AiProductionImportError as error:
            raise ValidationError({"detail": error.message, "code": error.code}) from error
        response = Response({"data": ReadSerializer(snapshot(record)).data})
        response["ETag"] = etag_for_instance(record)
        response["Cache-Control"] = "no-store"
        return response

    @extend_schema(request=UploadSerializer, responses=ReadSerializer)
    def create(self, request):
        serializer = UploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            record, replay = recognize_upload(
                employee=request.employee,
                request=request,
                uploaded_file=serializer.validated_data["file"],
                client_request_id=serializer.validated_data["client_request_id"],
            )
        except AiProductionImportError as error:
            # 项目异常处理器取第一个字段为提示，中文说明应优先于机器错误码。
            detail = {"detail": error.message, "code": error.code}
            if getattr(error, "record_id", None):
                detail["record_id"] = error.record_id
            raise ValidationError(detail) from error
        response = Response({"data": ReadSerializer(snapshot(record)).data, "replay": replay}, status=status.HTTP_200_OK)
        response["ETag"] = etag_for_instance(record)
        response["Cache-Control"] = "no-store"
        return response

    @extend_schema(request=None, responses=ReadSerializer)
    @action(detail=True, methods=["post"], url_path="match-materials")
    def match_materials(self, request, pk=None):
        if request.data:
            raise ValidationError({"detail": "对应材料不接受额外参数。"})
        try:
            record = match_record_materials(employee=request.employee, record_id=pk, request=request)
        except AiProductionImportError as error:
            raise ValidationError({"detail": error.message, "code": error.code}) from error
        response = Response({"data": ReadSerializer(snapshot(record)).data})
        response["ETag"] = etag_for_instance(record)
        response["Cache-Control"] = "no-store"
        return response

    @extend_schema(responses=ReadSerializer)
    def retrieve(self, request, pk=None):
        record = owned(request.employee, pk)
        response = Response({"data": ReadSerializer(snapshot(record)).data})
        response["ETag"] = etag_for_instance(record)
        response["Cache-Control"] = "no-store"
        return response

    @extend_schema(request=TaskSelectionSerializer, responses=ReadSerializer)
    @action(detail=True, methods=["post"], url_path="select-task")
    def select_recognized_task(self, request, pk=None):
        serializer = TaskSelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = select_task(employee=request.employee, record_id=pk,
                             task_key=serializer.validated_data["task_key"], request=request)
        response = Response({"data": ReadSerializer(snapshot(record)).data})
        response["ETag"] = etag_for_instance(record)
        response["Cache-Control"] = "no-store"
        return response

    @extend_schema(request=None, responses=ReadSerializer)
    @action(detail=True, methods=["post"], url_path="restore-review")
    def restore_review(self, request, pk=None):
        record = restore_previous_review(employee=request.employee, record_id=pk, request=request)
        response = Response({"data": ReadSerializer(snapshot(record)).data})
        response["ETag"] = etag_for_instance(record)
        response["Cache-Control"] = "no-store"
        return response

    @extend_schema(request=TaskDraftWriteSerializer, responses=ReadSerializer)
    @action(detail=True, methods=["post"], url_path="create-task")
    def create_task(self, request, pk=None):
        serializer = TaskDraftWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record, replay = create_task_draft(
            employee=request.employee,
            record_id=pk,
            payload=serializer.validated_data["payload"],
            task_key=serializer.validated_data.get("task_key"),
            request=request,
        )
        response = Response({"data": ReadSerializer(snapshot(record)).data, "replay": replay})
        response["ETag"] = etag_for_instance(record)
        return response

    @extend_schema(request=BomDraftWriteSerializer, responses=ReadSerializer)
    @action(detail=True, methods=["post"], url_path="create-boms")
    def create_boms_action(self, request, pk=None):
        serializer = BomDraftWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record, boms, replay = create_boms(
            employee=request.employee,
            record_id=pk,
            plans=serializer.validated_data["plans"],
            task_key=serializer.validated_data.get("task_key"),
            request=request,
        )
        response = Response({"data": ReadSerializer(snapshot(record)).data, "boms": boms, "replay": replay})
        response["ETag"] = etag_for_instance(record)
        return response
