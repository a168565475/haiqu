from drf_spectacular.utils import OpenApiRequest, extend_schema
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from .application_serializers import SampleApplicationSerializer, SampleApplicationReviewSerializer, SampleApplicationRequestSerializer
from ..application_services import submit_application, review_application
from .application_product_serializers import SampleApplicationProductsSerializer, SampleApplicationProductQuerySerializer, SampleApplicationProductCandidateSerializer, SampleApplicationProductOptionsSerializer


class SampleApplicationActionsMixin:
    # q 用于产品检索；申请对象仍由 get_queryset 执行数据范围校验。
    @extend_schema(parameters=[SampleApplicationProductQuerySerializer], responses=SampleApplicationProductOptionsSerializer)
    @action(detail=True, methods=['get'], url_path='application-product-options', filter_backends=[])
    def application_product_options(self, request, pk=None):
        from ..application_product_services import application_product_candidates
        query = SampleApplicationProductQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        candidates = application_product_candidates(sample=self.get_object(), query=query.validated_data['q'], request=request)
        return Response({'data': SampleApplicationProductCandidateSerializer(candidates, many=True).data})

    @extend_schema(request=SampleApplicationProductsSerializer)
    @action(detail=True, methods=['patch'], url_path='application-products')
    def application_products(self, request, pk=None):
        from ..application_product_services import complete_application_products
        serializer = SampleApplicationProductsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sample = complete_application_products(sample_id=self.get_object().pk, data=serializer.validated_data, request=request)
        return self._form_response(sample)

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
