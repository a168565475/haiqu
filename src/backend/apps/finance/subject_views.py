from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from . import subject_services
from .subject_selectors import subjects
from .subject_serializers import SubjectQuerySerializer, SubjectResponseSerializer, SubjectSerializer, SubjectWriteSerializer


class AccountingSubjectViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = SubjectSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    action_permission_map = {
        "list": "finance.view_accountingsubject", "retrieve": "finance.view_accountingsubject",
        "create": "finance.add_accountingsubject", "partial_update": "finance.change_accountingsubject",
        "destroy": "finance.delete_accountingsubject",
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return subjects().none()
        query = SubjectQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return subjects(query.validated_data if self.action == "list" else {})

    def subject_response(self, subject, status=200):
        current = subjects().get(pk=subject.pk)
        return Response({"data": SubjectSerializer(current).data}, status=status, headers={"ETag": etag_for_instance(current)})

    @extend_schema(parameters=[SubjectQuerySerializer])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=SubjectResponseSerializer)
    def retrieve(self, request, *args, **kwargs):
        return self.subject_response(self.get_object())

    @extend_schema(request=SubjectWriteSerializer, responses={201: SubjectResponseSerializer, 200: SubjectResponseSerializer},
                   parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)])
    def create(self, request):
        subject, replayed = subject_services.create_subject(request)
        response = self.subject_response(subject, 200 if replayed else 201)
        if replayed:
            response["Idempotent-Replayed"] = "true"
        return response

    @extend_schema(request=SubjectWriteSerializer, responses=SubjectResponseSerializer,
                   parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    def partial_update(self, request, pk=None):
        serializer = SubjectWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return self.subject_response(subject_services.update_subject(request, pk, serializer.validated_data))

    @extend_schema(responses={204: None}, parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)])
    def destroy(self, request, pk=None):
        subject_services.delete_subject(request, pk)
        return Response(status=204)


class SubjectTreeViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasActiveEmployee, BusinessActionPermission]
    serializer_class = SubjectSerializer
    http_method_names = ["get", "head", "options"]
    action_permission_map = {"list": "finance.view_accountingsubject"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return subjects().none()
        query = SubjectQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return subjects({"parent_id": None, **query.validated_data})

    @extend_schema(parameters=[SubjectQuerySerializer])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
