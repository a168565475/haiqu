from django.db import IntegrityError, transaction
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.api.permissions import HasActiveEmployee

from .crypto import decrypt_key
from .models import OpenAIKeyConfig
from .serializers import OpenAIKeyConfigSerializer, OpenAIKeyConfigWriteSerializer


class OpenAIKeyConfigViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = OpenAIKeyConfigSerializer
    permission_classes = [IsAuthenticated, HasActiveEmployee]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def _employee(self):
        employee = getattr(self.request, "employee", None)
        if employee is None:
            raise PermissionDenied("当前账号没有有效员工档案。")
        return employee

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return OpenAIKeyConfig.objects.none()
        return OpenAIKeyConfig.objects.filter(employee=self._employee()).order_by("-updated_at", "-id")

    def _response(self, config, *, status_code=status.HTTP_200_OK):
        response = Response({"data": OpenAIKeyConfigSerializer(config).data}, status=status_code)
        response["ETag"] = etag_for_instance(config)
        response["Cache-Control"] = "no-store"
        return response

    def create(self, request, *args, **kwargs):
        serializer = OpenAIKeyConfigWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                config = serializer.save(employee=self._employee())
        except IntegrityError as exc:
            raise Conflict("同一账号不能使用重复的 Key 标签。") from exc
        return self._response(config, status_code=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        return self._response(self.get_object())

    def partial_update(self, request, *args, **kwargs):
        config = self.get_object()
        require_matching_etag(request, config)
        if not request.data:
            raise ValidationError({"detail": "请至少提交一个需要修改的字段。"})
        with transaction.atomic():
            config = OpenAIKeyConfig.objects.select_for_update().get(pk=config.pk, employee=self._employee())
            require_matching_etag(request, config)
            serializer = OpenAIKeyConfigWriteSerializer(config, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            config = serializer.save()
        return self._response(config)

    def destroy(self, request, *args, **kwargs):
        config = self.get_object()
        require_matching_etag(request, config)
        config.delete()
        return Response({"data": {"id": str(config.pk), "deleted": True}})

    @extend_schema(responses=OpenAIKeyConfigSerializer)
    @action(detail=True, methods=["post"], url_path="test")
    def test_config(self, request, pk=None):
        config = self.get_object()
        require_matching_etag(request, config)
        decrypt_key(config.key_ciphertext)
        return self._response(config)

