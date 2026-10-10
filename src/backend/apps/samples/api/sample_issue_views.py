from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.response import Response

from .sample_issue_serializers import (
    SampleMaterialIssueConfirmSerializer,
    SampleMaterialIssueInitiateSerializer,
)
from ..sample_issue_services import (
    confirm_sample_material_issue,
    initiate_sample_material_issue,
    issue_response,
)


class SampleMaterialIssueActionsMixin:
    @extend_schema(responses=dict)
    @action(detail=True, methods=["get"], url_path="material-issue")
    def material_issue(self, request, pk=None):
        sample = self.get_object()
        result = issue_response(sample, request)
        return Response({"data": result}, headers={"ETag": result.get("etag", "")})

    @extend_schema(request=SampleMaterialIssueInitiateSerializer, responses=dict)
    @action(detail=True, methods=["post"], url_path="material-issue/initiate")
    def material_issue_initiate(self, request, pk=None):
        serializer = SampleMaterialIssueInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sample = initiate_sample_material_issue(
            sample_id=self.get_object().pk,
            request=request,
            client_request_id=serializer.validated_data.get("client_request_id"),
            note=serializer.validated_data.get("note", ""),
        )
        result = issue_response(sample, request)
        return Response({"data": result}, headers={"ETag": result["etag"]})

    @extend_schema(request=SampleMaterialIssueConfirmSerializer, responses=dict)
    @action(detail=True, methods=["post"], url_path="material-issue/confirm")
    def material_issue_confirm(self, request, pk=None):
        serializer = SampleMaterialIssueConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sample = confirm_sample_material_issue(
            sample_id=self.get_object().pk,
            data=serializer.validated_data,
            request=request,
        )
        result = issue_response(sample, request)
        return Response({"data": result}, headers={"ETag": result["etag"]})
