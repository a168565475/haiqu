import hashlib
import io
import zipfile

from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.codex_connection.models import CodexConnection
from apps.codex_connection.serializers import EmptySerializer
from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import HasActiveEmployee
from .access import require_actor
from .models import ProductionTaskImport
from .readiness import require_schema
from .review import issue_list, rematch, save_review
from .serializers import ImportReadSerializer, ImportResponseSerializer, ReviewSerializer, SelectionSerializer, UploadSerializer
from .services import cancel_import, create_import, owned, retry_import, select_candidate
from .storage import ImportFailure, source_path


def snapshot(record):
    connection = CodexConnection.objects.first()
    blocked = ''
    if record.state == 'QUEUED' and (not connection or connection.paused or connection.status != 'READY'):
        blocked = connection.error_code or 'CODEX_NOT_READY' if connection else 'CODEX_NOT_READY'
    result = {key: getattr(record, key) for key in ('id', 'state', 'phase', 'original_name', 'scan_status',
        'expires_at', 'attempt_no', 'result_revision', 'candidates', 'selected_candidate', 'extraction',
        'matching', 'review', 'error_code', 'saved_task_id', 'saved_task_number', 'saved_at')}
    result.update(issues=issue_list(record), blocked_reason=blocked, duplicates=[
        {'id': str(item.pk), 'state': item.state, 'saved_task_number': item.saved_task_number,
         'object_id': item.object_key} for item in ProductionTaskImport.objects.filter(
            owner_id=record.owner_id, sha256=record.sha256).exclude(pk=record.pk).exclude(state='EXPIRED').order_by('-created_at')[:20]])
    return result


class ProductionTaskImportViewSet(viewsets.GenericViewSet):
    permission_classes = [HasActiveEmployee]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    serializer_class = ImportResponseSerializer
    queryset = ProductionTaskImport.objects.none()

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        require_actor(request)
        require_schema()

    def response(self, record, status_code=200, **extra):
        response = Response({'data': ImportReadSerializer(snapshot(record)).data, **extra}, status=status_code)
        response['ETag'] = etag_for_instance(record)
        response['Cache-Control'] = 'no-store'
        return response

    @extend_schema(request=UploadSerializer, responses={200: ImportResponseSerializer, 201: ImportResponseSerializer})
    def create(self, request):
        require_actor(request)
        if set(request.data) - {'file', 'client_request_id'}:
            raise ValidationError('上传包含不支持的字段。')
        serializer = UploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record, replay = create_import(request, serializer.validated_data['file'], serializer.validated_data['client_request_id'])
        return self.response(record, 200 if replay else status.HTTP_201_CREATED, replay=replay)

    def retrieve(self, request, pk=None):
        return self.response(owned(request, pk))

    @extend_schema(request=SelectionSerializer, parameters=[OpenApiParameter('If-Match', str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=['post'], url_path='select')
    def select(self, request, pk=None):
        serializer = SelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.response(select_candidate(request, pk, serializer.validated_data['object_id']))

    @extend_schema(request=ReviewSerializer, parameters=[OpenApiParameter('If-Match', str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=['patch'], url_path='review')
    def review(self, request, pk=None):
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.response(save_review(request, pk, serializer.validated_data['review']))

    @extend_schema(request=EmptySerializer, parameters=[OpenApiParameter('If-Match', str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=['post'], url_path='rematch')
    def rematch(self, request, pk=None):
        EmptySerializer(data=request.data).is_valid(raise_exception=True)
        return self.response(rematch(request, pk))

    @extend_schema(request=EmptySerializer, parameters=[OpenApiParameter('If-Match', str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        EmptySerializer(data=request.data).is_valid(raise_exception=True)
        return self.response(cancel_import(request, pk))

    @extend_schema(request=EmptySerializer, parameters=[OpenApiParameter('If-Match', str, OpenApiParameter.HEADER, required=True)])
    @action(detail=True, methods=['post'], url_path='retry')
    def retry(self, request, pk=None):
        EmptySerializer(data=request.data).is_valid(raise_exception=True)
        return self.response(retry_import(request, pk))

    def source_record(self, request, pk):
        record = owned(request, pk)
        if record.state == 'EXPIRED' or (not record.saved_at and record.expires_at <= timezone.now()) or record.scan_status != 'CLEAN':
            raise NotFound('来源尚不可用或已过期。')
        return record

    @extend_schema(responses=OpenApiTypes.OBJECT, parameters=[OpenApiParameter('download', str, enum=['1'])])
    @action(detail=True, methods=['get'], url_path='source')
    def source(self, request, pk=None):
        record = self.source_record(request, pk)
        # 来源清单只通过受控 API 展示，不返回宿主文件路径。
        if request.query_params.get('download') != '1':
            response = Response({'data': record.manifest})
            response['Cache-Control'] = 'no-store'
            return response
        response = FileResponse(source_path(record).open('rb'), as_attachment=True,
                                filename=record.original_name, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Cache-Control'] = 'no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response

    @extend_schema(responses=OpenApiTypes.BINARY)
    @action(detail=True, methods=['get'], url_path=r'images/(?P<image_id>image_\d{3})')
    def image(self, request, pk=None, image_id=None):
        record = self.source_record(request, pk)
        image = next((item for item in record.manifest.get('images', []) if item['id'] == image_id), None)
        if image is None:
            raise NotFound()
        with zipfile.ZipFile(source_path(record)) as archive:
            data = archive.read(image['part'])
        if hashlib.sha256(data).hexdigest() != image['sha256']:
            raise ImportFailure('SOURCE_CHANGED')
        response = FileResponse(io.BytesIO(data), content_type='image/png' if image['format'] == 'PNG' else 'image/jpeg')
        response['Cache-Control'] = 'no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
