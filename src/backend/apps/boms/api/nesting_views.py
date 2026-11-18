import json

from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from ..nesting_services import (ACTION_PERMISSIONS, calculate_job, cancel_job, create_job, get_bom, get_job, scoped_jobs)
from ..nesting_storage import open_artifact, source_path
from .nesting_serializers import (BomNestingJobSerializer, BomNestingListResponseSerializer,
    BomNestingResponseSerializer, NestingParametersSerializer, NestingTargetSerializer, NestingUploadSerializer)


class BomNestingJobViewSet(viewsets.ViewSet):
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    action_permission_map = ACTION_PERMISSIONS
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    serializer_class = BomNestingJobSerializer

    @staticmethod
    def response(job, *, status=200):
        response = Response({"data": BomNestingJobSerializer(job).data}, status=status)
        response["ETag"] = etag_for_instance(job)
        response["Cache-Control"] = "private, no-store"
        return response

    @extend_schema(request={"multipart/form-data": NestingUploadSerializer}, responses={201: BomNestingResponseSerializer})
    def create(self, request, bom_id=None):
        data = {key: request.data.get(key) for key in ["file", "source_unit", "target_snapshot"] if key in request.data}
        data.update({key: request.data[key] for key in ["line_id", "draft_key"] if request.data.get(key)})
        if isinstance(data.get("target_snapshot"), str):
            try:
                data["target_snapshot"] = json.loads(data["target_snapshot"])
            except (ValueError, TypeError) as exc:
                raise ValidationError({"target_snapshot": "面料身份快照不是有效 JSON。"}) from exc
        serializer = NestingUploadSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return self.response(create_job(request, bom_id, serializer.validated_data), status=201)

    @extend_schema(parameters=[NestingTargetSerializer], responses=BomNestingListResponseSerializer)
    def list(self, request, bom_id=None):
        target = NestingTargetSerializer(data=request.query_params)
        target.is_valid(raise_exception=True)
        bom = get_bom(request, bom_id)
        jobs = scoped_jobs(request, bom).filter(**target.validated_data).order_by("-created_at", "-id")[:30]
        response = Response({"data": BomNestingJobSerializer(jobs, many=True).data})
        response["Cache-Control"] = "private, no-store"
        return response

    @extend_schema(responses=BomNestingResponseSerializer)
    def retrieve(self, request, bom_id=None, job_id=None):
        return self.response(get_job(request, get_bom(request, bom_id), job_id))

    @extend_schema(request=NestingParametersSerializer, responses=BomNestingResponseSerializer)
    def calculate(self, request, bom_id=None, job_id=None):
        serializer = NestingParametersSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.response(calculate_job(request, bom_id, job_id, serializer.validated_data))

    @extend_schema(request=None, responses=BomNestingResponseSerializer)
    def cancel(self, request, bom_id=None, job_id=None):
        return self.response(cancel_job(request, bom_id, job_id))

    @extend_schema(responses={(200, "application/dxf"): OpenApiTypes.BINARY})
    def source(self, request, bom_id=None, job_id=None):
        job = get_job(request, get_bom(request, bom_id), job_id)
        response = FileResponse(source_path(job).open("rb"), as_attachment=True,
                                filename=job.original_name, content_type="application/dxf")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    def _artifact(self, request, bom_id, job_id, *, dxf=False):
        job = get_job(request, get_bom(request, bom_id), job_id)
        if job.status != "SUCCEEDED" or not job.result or job.execution.get('engine') != 'CODEX_TOOLS':
            raise Conflict("只有 Codex 执行端已完成的成果可以预览或下载；旧记录请重新提交。")
        name = 'layout.dxf' if dxf else 'layout.svg'
        response = FileResponse(open_artifact(job, name), as_attachment=dxf,
                                filename=f'nesting-{job.pk}.{"dxf" if dxf else "svg"}',
                                content_type="application/dxf" if dxf else "image/svg+xml")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        response["Content-Disposition"] = f'{"attachment" if dxf else "inline"}; filename="nesting-{job.pk}.{ "dxf" if dxf else "svg"}"'
        return response

    @extend_schema(responses={(200, "image/svg+xml"): OpenApiTypes.BINARY})
    def preview(self, request, bom_id=None, job_id=None):
        return self._artifact(request, bom_id, job_id)

    @extend_schema(responses={(200, "application/dxf"): OpenApiTypes.BINARY})
    def dxf(self, request, bom_id=None, job_id=None):
        return self._artifact(request, bom_id, job_id, dxf=True)
