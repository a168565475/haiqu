from drf_spectacular.utils import OpenApiRequest, extend_schema
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from .application_serializers import SampleApplicationSerializer, SampleApplicationReviewSerializer, SampleApplicationRequestSerializer
from ..application_services import submit_application, review_application


class SampleApplicationActionsMixin:
    def _submit_application(self, request, sample_id=None):
        payload = self._form_payload(request)
        serializer = SampleApplicationSerializer(data=payload, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        if set(request.FILES) - {'reference_image'} or len(request.FILES.getlist('reference_image')) > 1:
            raise ValidationError({'reference_image': '最多上传一张参考图片。'})
        sample, replayed = submit_application(data=serializer.validated_data, uploaded_file=request.FILES.get('reference_image'), request=request, sample_id=sample_id)
        return self._form_response(sample, replayed=replayed, created=not sample_id and not replayed)

    @extend_schema(request={
        'application/json': SampleApplicationRequestSerializer,
        'multipart/form-data': OpenApiRequest(SampleApplicationRequestSerializer, encoding={'payload': {'contentType': 'application/json'}}),
    })
    @action(detail=False, methods=['post'], url_path='applications')
    def application_create(self, request):
        return self._submit_application(request)

    @extend_schema(request={
        'application/json': SampleApplicationRequestSerializer,
        'multipart/form-data': OpenApiRequest(SampleApplicationRequestSerializer, encoding={'payload': {'contentType': 'application/json'}}),
    })
    @action(detail=True, methods=['post'], url_path='application-resubmit')
    def application_resubmit(self, request, pk=None):
        sample = self.get_object()
        return self._submit_application(request, sample.pk)

    @extend_schema(request=SampleApplicationReviewSerializer)
    @action(detail=True, methods=['post'], url_path='director-review')
    def director_review(self, request, pk=None):
        sample = self.get_object()
        serializer = SampleApplicationReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = review_application(sample_id=sample.pk, data=serializer.validated_data, request=request)
        return self._form_response(result)
